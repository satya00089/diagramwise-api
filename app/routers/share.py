"""Router for public solution sharing and leaderboard features."""

from typing import Any, Dict, List
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.models.attempt_models import (
    LeaderboardEntry,
    PublicSolutionResponse,
    PublishResponse,
)
from app.models.diagram_models import PublicDiagramResponse, PublishDiagramResponse
from app.services.dynamodb_service import dynamodb_service
from app.routers.auth import get_current_user
from app.utils.config import get_settings
from app.services.llm_client import create_llm_provider
from app.services.llm_port import LLMRequest
from app.services.diagram_preview import render_architecture_svg

router = APIRouter()


# ---------------------------------------------------------------------------
# Publish / Unpublish
# ---------------------------------------------------------------------------


@router.post(
    "/attempts/{attempt_id}/publish",
    response_model=PublishResponse,
    status_code=status.HTTP_200_OK,
)
async def publish_attempt(
    attempt_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Make a problem attempt publicly visible (owner only)."""
    user_id = current_user["user_id"]

    # attempt_id is the composite "userId#problemId" returned by the frontend
    if "#" not in attempt_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid attempt ID format. Expected 'userId#problemId'.",
        )

    _owner_id, problem_id = attempt_id.split("#", 1)

    # Security: only the owner can publish their own attempt
    if _owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only publish your own solutions.",
        )

    published = dynamodb_service.publish_attempt(
        user_id=user_id,
        problem_id=problem_id,
        author_name=current_user.get("name") or current_user.get("email", "Anonymous"),
        author_picture=current_user.get("picture"),
    )

    if not published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attempt not found.",
        )

    settings = get_settings()
    base = getattr(settings, "frontend_url", "https://diagramwise.com").rstrip("/")
    public_url = f"{base}/public/{quote(attempt_id, safe='')}"

    return PublishResponse(
        attemptId=attempt_id,
        publicUrl=public_url,
        publishedAt=published["publishedAt"],
    )


@router.post(
    "/attempts/{attempt_id}/unpublish",
    status_code=status.HTTP_200_OK,
)
async def unpublish_attempt(
    attempt_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Remove a solution from public view (owner only)."""
    user_id = current_user["user_id"]

    if "#" not in attempt_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid attempt ID format.",
        )

    _owner_id, problem_id = attempt_id.split("#", 1)

    if _owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only unpublish your own solutions.",
        )

    dynamodb_service.unpublish_attempt(user_id=user_id, problem_id=problem_id)
    return {"message": "Solution unpublished successfully."}


# ---------------------------------------------------------------------------
# Free-design diagram Publish / Unpublish / Public View
# ---------------------------------------------------------------------------


@router.post(
    "/diagrams/{diagram_id}/publish",
    response_model=PublishDiagramResponse,
    status_code=status.HTTP_200_OK,
)
async def publish_diagram(
    diagram_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Make a free-design diagram publicly visible (owner only)."""
    user_id = current_user["user_id"]

    published = dynamodb_service.publish_diagram(
        user_id=user_id,
        diagram_id=diagram_id,
        author_name=current_user.get("name") or current_user.get("email", "Anonymous"),
        author_picture=current_user.get("picture"),
    )

    if not published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagram not found or you are not the owner.",
        )

    settings = get_settings()
    base = getattr(settings, "frontend_url", "https://diagramwise.com").rstrip("/")
    public_diagram_id = published.get("diagramId", diagram_id)
    public_url = f"{base}/public/{public_diagram_id}"

    return PublishDiagramResponse(
        diagramId=public_diagram_id,
        publicUrl=public_url,
        publishedAt=published["publishedAt"],
    )


@router.post(
    "/diagrams/{diagram_id}/unpublish",
    status_code=status.HTTP_200_OK,
)
async def unpublish_diagram(
    diagram_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Remove a free-design diagram from public view (owner only)."""
    user_id = current_user["user_id"]
    dynamodb_service.unpublish_diagram(user_id=user_id, diagram_id=diagram_id)
    return {"message": "Diagram unpublished successfully."}


@router.get(
    "/public/diagrams/{diagram_id}",
    response_model=PublicDiagramResponse,
)
async def get_public_diagram(diagram_id: str):
    """Fetch a publicly shared free-design diagram. Increments view count."""
    diagram = dynamodb_service.get_public_diagram(diagram_id=diagram_id)
    if not diagram:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagram not found or not publicly available.",
        )
    return diagram


@router.get(
    "/public/diagrams/{diagram_id}/preview.svg",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}}},
)
async def get_public_diagram_preview(diagram_id: str):
    """Render a cacheable visual preview for a public diagram."""

    diagram = dynamodb_service.get_public_diagram(diagram_id=diagram_id)
    if not diagram:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diagram not found or not publicly available.",
        )
    svg = render_architecture_svg(
        title=diagram.title,
        nodes=diagram.nodes,
        edges=diagram.edges,
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


# ---------------------------------------------------------------------------
# Public Solution View  (no auth required)
# ---------------------------------------------------------------------------


@router.get(
    "/solutions/{attempt_id}",
    response_model=PublicSolutionResponse,
)
async def get_public_solution(attempt_id: str):
    """Fetch a publicly shared solution.  Increments view count."""
    if "#" not in attempt_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid solution ID format.",
        )

    user_id, problem_id = attempt_id.split("#", 1)

    solution = dynamodb_service.get_public_solution(
        user_id=user_id, problem_id=problem_id
    )

    if not solution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solution not found or not publicly available.",
        )

    return solution


# ---------------------------------------------------------------------------
# Leaderboard  (no auth required)
# ---------------------------------------------------------------------------


@router.get(
    "/problems/{problem_id}/leaderboard",
    response_model=List[LeaderboardEntry],
)
async def get_problem_leaderboard(problem_id: str):
    """Top 10 public solutions for a problem, sorted by score descending."""
    entries = dynamodb_service.get_problem_leaderboard(problem_id=problem_id)
    return entries


# ---------------------------------------------------------------------------
# AI Article / Post Generator
# ---------------------------------------------------------------------------


class ShareArticlePayload(BaseModel):
    problemTitle: str
    problemDescription: str = ""
    score: int
    strengths: List[str] = []
    improvements: List[str] = []
    nodeCount: int = 0
    edgeCount: int = 0
    scores: Dict[str, Any] = {}


class ShareArticleResponse(BaseModel):
    linkedinPost: str
    twitterPost: str
    mediumArticle: str


@router.post(
    "/share/generate-article",
    response_model=ShareArticleResponse,
)
async def generate_share_article(
    payload: ShareArticlePayload,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Generate platform-specific share content using AI."""
    settings = get_settings()
    llm = create_llm_provider(settings)

    author_name = (
        current_user.get("name") or current_user.get("email", "I").split("@")[0]
    )

    strengths_text = (
        "\n".join(f"- {s}" for s in payload.strengths[:5]) if payload.strengths else "- Strong architectural decisions"
    )

    prompt = f"""You are a technical-content writer helping a software engineer share their achievement.

They just solved "{payload.problemTitle}" on Diagramwise and scored {payload.score}/100.

Design stats: {payload.nodeCount} components, {payload.edgeCount} connections.
Strengths: {strengths_text}

Generate three things:
1. A LinkedIn post (max 1200 chars) — professional, celebratory, uses 2-3 relevant emojis, ends with 3-5 hashtags like #SystemDesign #SoftwareArchitecture #TechLearning. Reference the score. Encourage others to try.
2. A Twitter/X post (max 270 chars) — punchy, exciting, includes the score, 2 hashtags.
3. A Medium article (500-700 words, Markdown format) — titled "How I Solved: {payload.problemTitle}", covers the problem, approach, key architectural decisions, lessons learned, and what to do differently. Written in first person by {author_name}.

Return JSON with keys: linkedinPost, twitterPost, mediumArticle."""

    response = await llm.generate(
        LLMRequest(
            task="share.generate-article",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful technical content writer. Always respond with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=settings.llm_max_tokens,
            response_format={"type": "json_object"},
            temperature=settings.llm_temperature,
            tags=("share", "content"),
            metadata={
                "node_count": payload.nodeCount,
                "edge_count": payload.edgeCount,
            },
        )
    )

    import json
    result = json.loads(response.content or "{}")

    return ShareArticleResponse(
        linkedinPost=result.get("linkedinPost", ""),
        twitterPost=result.get("twitterPost", ""),
        mediumArticle=result.get("mediumArticle", ""),
    )
