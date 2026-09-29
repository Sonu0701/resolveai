from __future__ import annotations
from typing import Any, Literal, TypedDict
from pydantic import BaseModel, Field

IssueType = Literal["damaged_product","refund_request","delayed_delivery","wrong_item","delivered_not_received","product_defect","account_or_security","cancellation","other"]

class TriageResult(BaseModel):
    issue_type: IssueType = "other"
    summary: str
    sentiment: Literal["calm","frustrated","angry","distressed"] = "calm"
    urgency: Literal["low","normal","high","critical"] = "normal"
    needed_information: list[str] = Field(default_factory=list)
    policy_categories: list[str] = Field(default_factory=list)

class PolicyDecision(BaseModel):
    recommended_action: str
    eligibility: Literal["eligible","not_eligible","conditional","needs_information"]
    decision_reason: str
    policy_rule_applied: str
    requires_approval: bool = False
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

class ResolutionRecommendation(BaseModel):
    action: str
    customer_safe_explanation: str
    next_steps: list[str] = Field(default_factory=list)
    status: str = "draft"

class AgentState(TypedDict, total=False):
    thread_id: str
    ticket_id: str
    customer_message: str
    order_id: str | None
    conversation_messages: list[dict[str, str]]
    ticket_summary: str
    extracted_entities: dict[str, Any]
    issue_type: str
    sentiment: str
    urgency: str
    needed_information: list[str]
    policy_categories: list[str]
    order_details: dict[str, Any]
    retrieved_policy_docs: list[dict[str, Any]]
    similar_cases: list[dict[str, Any]]
    policy_decision: dict[str, Any]
    recommendation: dict[str, Any]
    confidence: float
    requires_approval: bool
    approval_payload: dict[str, Any]
    approval_decision: dict[str, Any]
    drafted_customer_response: str
    final_response: str
    sources: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    error_messages: list[str]
    risk_reasons: list[str]
    security_flags: list[str]
