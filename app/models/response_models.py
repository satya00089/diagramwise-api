"""Models for system design assessment responses."""

from typing import Dict, List, Optional, cast
from enum import Enum
from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    """Enumeration for feedback types."""

    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


class FindingSeverity(str, Enum):
    """Severity used for actionable architecture findings."""

    CRITICAL = "critical"
    IMPORTANT = "important"
    IMPROVEMENT = "improvement"
    POSITIVE = "positive"


class AssessmentSource(str, Enum):
    """How the assessment was produced."""

    AI = "ai"
    RULE_BASED = "rule_based"


class FeedbackCategory(str, Enum):
    """Enumeration for feedback categories."""

    SCALABILITY = "scalability"
    RELIABILITY = "reliability"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"
    PERFORMANCE = "performance"
    COST = "cost"
    REQUIREMENTS = "requirements"
    CONSTRAINTS = "constraints"
    COMPONENT_DESCRIPTION = "component_description"
    CONNECTION_REASONING = "connection_reasoning"
    OBSERVABILITY = "observability"
    DELIVERABILITY = "deliverability"


class ValidationFeedback(BaseModel):
    """Model for validation feedback."""

    type: FeedbackType
    message: str
    category: FeedbackCategory
    priority: Optional[int] = Field(default=1, ge=1, le=5)


class ReviewFinding(BaseModel):
    """A structured finding that explains and prioritises an observation."""

    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    recommendation: Optional[str] = None
    severity: FindingSeverity = FindingSeverity.IMPROVEMENT


class ScoreBreakdown(BaseModel):
    """Model for detailed score breakdown."""

    scalability: int = Field(ge=0, le=100)
    reliability: int = Field(ge=0, le=100)
    security: int = Field(ge=0, le=100)
    maintainability: int = Field(ge=0, le=100)
    performance: Optional[int] = Field(default=None, ge=0, le=100)
    cost_efficiency: Optional[int] = Field(default=None, ge=0, le=100)
    observability: Optional[int] = Field(default=None, ge=0, le=100)
    deliverability: Optional[int] = Field(default=None, ge=0, le=100)
    requirements_alignment: Optional[int] = Field(default=None, ge=0, le=100)
    constraint_compliance: Optional[int] = Field(default=None, ge=0, le=100)
    component_justification: Optional[int] = Field(default=None, ge=0, le=100)
    connection_clarity: Optional[int] = Field(default=None, ge=0, le=100)


class AssessmentResponse(BaseModel):
    """Model for system design assessment response."""

    is_valid: bool
    overall_score: int = Field(ge=0, le=100)
    scores: ScoreBreakdown
    feedback: List[ValidationFeedback]
    summary: Optional[str] = None
    findings: List[ReviewFinding] = Field(
        default_factory=lambda: cast(List[ReviewFinding], [])
    )
    strengths: List[str]
    improvements: List[str]
    missing_components: List[str]
    missing_descriptions: Optional[List[str]] = None
    unclear_connections: Optional[List[str]] = None
    suggestions: List[str]
    detailed_analysis: Optional[Dict[str, str]] = None
    interview_questions: Optional[List[str]] = None
    assessment_id: Optional[str] = None
    trace_id: Optional[str] = None
    processing_time_ms: Optional[int] = None
    source: AssessmentSource = AssessmentSource.AI
