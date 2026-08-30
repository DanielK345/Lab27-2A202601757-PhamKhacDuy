"""Data models used by the churn-risk workflow."""

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    """One traceable decision made by the agent or a human reviewer."""

    timestamp: str
    agent_id: str
    action: str
    confidence: float = Field(ge=0.0, le=1.0)
    reviewer_id: str
    decision: str
