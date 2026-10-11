"""Response models for the super-admin dashboard."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AdminFeedbackItem(BaseModel):
    id: str
    createdAt: str
    updatedAt: Optional[str] = None
    status: str = "new"
    source: str
    category: str
    rating: Optional[int] = None
    helpful: Optional[bool] = None
    reasons: List[str] = Field(default_factory=list)
    message: str = ""
    contactEmail: Optional[str] = None
    route: Optional[str] = None
    appVersion: Optional[str] = None
    userId: Optional[str] = None
    authorName: Optional[str] = None
    authorEmail: Optional[str] = None
    authorPicture: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class AdminFeedbackSummary(BaseModel):
    total: int = 0
    new: int = 0
    averageRating: Optional[float] = None
    helpfulRate: Optional[float] = None
    categories: Dict[str, int] = Field(default_factory=dict)


class AdminAnalyticsSummary(BaseModel):
    totalEvents: int = 0
    pageViews: int = 0
    daily: List[Dict[str, Any]] = Field(default_factory=list)
    topEvents: List[Dict[str, Any]] = Field(default_factory=list)
    topRoutes: List[Dict[str, Any]] = Field(default_factory=list)


class AdminOverviewResponse(BaseModel):
    fromDate: str
    toDate: str
    analytics: AdminAnalyticsSummary
    feedback: AdminFeedbackSummary
    recentFeedback: List[AdminFeedbackItem] = Field(default_factory=list)


class GoogleAnalyticsChannelGroup(BaseModel):
    name: str
    sessions: int = 0


class GoogleAnalyticsReferralSource(BaseModel):
    sourceMedium: str
    sessions: int = 0


class GoogleAnalyticsCity(BaseModel):
    country: str
    region: str
    city: str
    sessions: int = 0


class AdminGoogleAnalyticsReport(BaseModel):
    status: Literal["not_configured", "connected", "error"]
    propertyId: Optional[str] = None
    activeUsers: Optional[int] = None
    newUsers: Optional[int] = None
    sessions: Optional[int] = None
    screenPageViews: Optional[int] = None
    channelGroups: List[GoogleAnalyticsChannelGroup] = Field(default_factory=list)
    referralSources: List[GoogleAnalyticsReferralSource] = Field(
        default_factory=list
    )
    cities: List[GoogleAnalyticsCity] = Field(default_factory=list)
    message: Optional[str] = None


class AdminApiLatencyRoute(BaseModel):
    route: str
    sampleCount: int = 0
    p50Ms: Optional[int] = None
    p95Ms: Optional[int] = None
    p99Ms: Optional[int] = None


class AdminApiLatencyReport(BaseModel):
    fromDate: str
    toDate: str
    collectionEnabled: bool = True
    sampleCount: int = 0
    p50Ms: Optional[int] = None
    p95Ms: Optional[int] = None
    p99Ms: Optional[int] = None
    routes: List[AdminApiLatencyRoute] = Field(default_factory=list)


class AdminAccessUser(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    roles: List[str] = Field(default_factory=list)


class GrantAdminRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


class UpdateFeedbackStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(new|reviewing|resolved)$")
