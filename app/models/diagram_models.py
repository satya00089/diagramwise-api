"""Diagram related Pydantic models."""

from typing import Any, Dict, List, Optional, cast
from pydantic import BaseModel, Field
from enum import Enum

from app.models.reasoning_models import ReasoningContext


class Permission(str, Enum):
    """Permission levels for diagram sharing."""

    READ = "read"
    EDIT = "edit"


class Collaborator(BaseModel):
    """Model for diagram collaborators."""

    userId: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    permission: Permission
    addedAt: str


class ShareRequest(BaseModel):
    """Request model for sharing a diagram."""

    email: str = Field(..., description="Email of the user to share with")
    permission: Permission = Field(..., description="Permission level to grant")


class ShareResponse(BaseModel):
    """Response model for sharing operations."""

    success: bool
    message: str
    collaborator: Optional[Collaborator] = None


class DiagramCreate(BaseModel):
    """Request model for creating a new diagram."""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    nodes: List[Any] = Field(default_factory=list)
    edges: List[Any] = Field(default_factory=list)
    reasoningContext: Optional[ReasoningContext] = None


class DiagramUpdate(BaseModel):
    """Request model for updating a diagram."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    nodes: Optional[List[Any]] = None
    edges: Optional[List[Any]] = None
    reasoningContext: Optional[ReasoningContext] = None


class DiagramResponse(BaseModel):
    """Response model for diagram data."""

    id: str
    userId: str
    title: str
    description: Optional[str] = None
    nodes: List[Any]
    edges: List[Any]
    nodeCount: int = Field(default=0, description="Number of nodes in the diagram")
    edgeCount: int = Field(default=0, description="Number of edges in the diagram")
    reasoningContext: Optional[ReasoningContext] = None
    createdAt: str
    updatedAt: str
    isPublic: bool = Field(
        default=False, description="Whether the diagram is publicly accessible"
    )
    publishedAt: Optional[str] = Field(
        default=None, description="When the diagram was last published"
    )
    viewCount: int = Field(default=0, description="Number of public views")
    collaborators: List[Collaborator] = Field(
        default_factory=lambda: cast(List[Collaborator], []),
        description="List of collaborators with access",
    )

    # Ownership and permission fields
    isOwner: Optional[bool] = Field(
        default=None, description="Whether the current user is the owner"
    )
    permission: Optional[str] = Field(
        default=None, description="Current user's permission level (owner/edit/read)"
    )
    owner: Optional[Dict[str, Any]] = Field(
        default=None, description="Owner information (id, name, email, pictureUrl)"
    )

    class Config:
        """Pydantic config."""

        from_attributes = True


class Diagram(BaseModel):
    """Internal diagram model."""

    id: str
    userId: str
    title: str
    description: Optional[str] = None
    nodes: List[Any] = Field(default_factory=list)
    edges: List[Any] = Field(default_factory=list)
    nodeCount: int = Field(default=0)
    edgeCount: int = Field(default=0)
    reasoningContext: Optional[ReasoningContext] = None
    createdAt: str
    updatedAt: str
    isPublic: bool = Field(default=False)
    publishedAt: Optional[str] = None
    viewCount: int = 0
    collaborators: List[Collaborator] = Field(
        default_factory=lambda: cast(List[Collaborator], [])
    )


class DiagramSummaryResponse(BaseModel):
    """Metadata returned by the diagram list endpoint."""

    id: str
    userId: str
    title: str
    description: Optional[str] = None
    createdAt: str
    updatedAt: str
    isPublic: bool = False
    publishedAt: Optional[str] = None
    viewCount: int = 0
    nodeCount: int = Field(..., description="Number of nodes in the diagram")
    edgeCount: int = Field(..., description="Number of edges in the diagram")
    isOwner: bool
    permission: str
    owner: Optional[Dict[str, Any]] = None


class PublicDiagramResponse(BaseModel):
    """Response model for a publicly shared free diagram."""

    id: str
    title: str
    description: Optional[str] = None
    nodes: List[Any]
    edges: List[Any]
    authorName: Optional[str] = None
    authorPicture: Optional[str] = None
    publishedAt: Optional[str] = None
    viewCount: int = 0


class PublishDiagramResponse(BaseModel):
    """Response returned after publishing a free diagram."""

    diagramId: str
    publicUrl: str
    publishedAt: str
