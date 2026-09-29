from __future__ import annotations

import json
from typing import Any

from langgraph.types import interrupt

from backend.config import settings
from backend.models import AgentState, PolicyDecision, ResolutionRecommendation, TriageResult
from backend.policy_engine import assess_additional_risk, evaluate_policy
from backend.prompts import DRAFT_SYSTEM, PLANNER_SYSTEM, TRIAGE_SYSTEM
from backend.rag import search_historical, search_policies
from backend.security import detect_prompt_injection, sanitize_text, validate_order_id
from backend.ticket_service import add_message, log_event, save_approval, upsert_ticket
from backend.tools import create_escalation_draft, save_resolution_draft


def _event(
    state: AgentState,
    name: str,
    detail: str,
) -> list[dict[str, Any]]:
    return [
        *state.get("tool_events", []),
        {"event": name, "detail": detail},
    ]


def _llm():
    if settings.demo_mode:
        return None

    from langchain_mistralai import ChatMistralAI

    return ChatMistralAI(
        model=settings.mistral_model,
        temperature=0,
        max_retries=2,
    )


def ticket_intake_node(state: AgentState) -> dict[str, Any]:
    message = sanitize_text(
        state.get("customer_message", ""),
        settings.max_message_chars,
    )

    if not message:
        return {
            "error_messages": ["Customer message is required."],
            "tool_events": _event(
                state,
                "intake_failed",
                "Empty message",
            ),
        }

    order_id = (state.get("order_id") or "").strip().upper() or None
    errors: list[str] = []

    if order_id and not validate_order_id(order_id):
        errors.append("Order ID must match NC-######.")

    security_flags = detect_prompt_injection(message)

    upsert_ticket(
        state["ticket_id"],
        state["thread_id"],
        order_id,
        message,
        "open",
    )
    add_message(state["ticket_id"], "customer", message)
    log_event(
        state["ticket_id"],
        "ticket_intake",
        {
            "order_id": order_id or "missing",
            "security_flags": security_flags,
        },
    )

    return {
        "customer_message": message,
        "order_id": order_id,
        "security_flags": security_flags,
        "error_messages": errors,
        "tool_events": _event(
            state,
            "ticket_triaged",
            "Ticket validated and saved",
        ),
    }


def _fallback_triage(
    message: str,
    order_id: str | None,
) -> TriageResult:
    normalized_message = message.lower()

    mapping = [
        (
            ("not received", "says delivered", "marked delivered"),
            "delivered_not_received",
        ),
        (("wrong item", "different item"), "wrong_item"),
        (("damaged", "broken"), "damaged_product"),
        (("defect", "not working"), "product_defect"),
        (("delayed", "late", "where is"), "delayed_delivery"),
        (("refund", "money back"), "refund_request"),
        (("cancel",), "cancellation"),
        (("hacked", "account"), "account_or_security"),
    ]

    issue_type = next(
        (
            value
            for keywords, value in mapping
            if any(keyword in normalized_message for keyword in keywords)
        ),
        "other",
    )

    needed_information = [] if order_id else ["order ID"]

    sentiment = (
        "angry"
        if any(
            word in normalized_message
            for word in ["angry", "unacceptable", "furious"]
        )
        else (
            "frustrated"
            if any(
                word in normalized_message
                for word in ["please", "still", "late"]
            )
            else "calm"
        )
    )

    urgency = (
        "critical"
        if any(
            word in normalized_message
            for word in ["fraud", "hacked", "legal"]
        )
        else (
            "high"
            if any(
                word in normalized_message
                for word in ["damaged", "not received", "chargeback"]
            )
            else "normal"
        )
    )

    return TriageResult(
        issue_type=issue_type,
        summary=message[:180],
        sentiment=sentiment,
        urgency=urgency,
        needed_information=needed_information,
        policy_categories=[issue_type],
    )


def triage_node(state: AgentState) -> dict[str, Any]:
    triage: TriageResult | None = None

    try:
        llm = _llm()

        if llm:
            triage = llm.with_structured_output(TriageResult).invoke(
                [
                    ("system", TRIAGE_SYSTEM),
                    (
                        "human",
                        f"Order ID supplied: {bool(state.get('order_id'))}\n"
                        f"Customer message: {state['customer_message']}",
                    ),
                ]
            )
    except Exception as exc:
        log_event(
            state["ticket_id"],
            "llm_fallback",
            {
                "node": "triage",
                "error": type(exc).__name__,
            },
        )

    triage = triage or _fallback_triage(
        state["customer_message"],
        state.get("order_id"),
    )

    data = triage.model_dump()

    upsert_ticket(
        state["ticket_id"],
        state["thread_id"],
        state.get("order_id"),
        state["customer_message"],
        "open",
        data["issue_type"],
        data["summary"],
    )

    return {
        "ticket_summary": data["summary"],
        "issue_type": data["issue_type"],
        "sentiment": data["sentiment"],
        "urgency": data["urgency"],
        "needed_information": data["needed_information"],
        "policy_categories": data["policy_categories"],
        "tool_events": _event(
            state,
            "ticket_triaged",
            f"Issue classified as {data['issue_type']}",
        ),
    }


def order_lookup_node(state: AgentState) -> dict[str, Any]:
    if not state.get("order_id"):
        return {
            "order_details": {},
            "tool_events": _event(
                state,
                "order_lookup_skipped",
                "Order ID missing",
            ),
        }

    from backend.tools import get_order_details

    result = get_order_details.invoke(
        {"order_id": state["order_id"]}
    )
    order = result.get("order", {}) if result.get("found") else {}

    errors = [
        *state.get("error_messages", []),
    ]

    if not result.get("found") and result.get("error"):
        errors.append(result["error"])

    return {
        "order_details": order,
        "error_messages": errors,
        "tool_events": _event(
            state,
            "order_lookup_completed",
            "Order facts found" if order else "Order not found",
        ),
    }


def knowledge_retrieval_node(state: AgentState) -> dict[str, Any]:
    query = (
        f"{state.get('issue_type', '')} "
        f"{state.get('customer_message', '')}"
    )

    documents = search_policies(query, None, 4)

    sources = [
        {
            "source": document["metadata"].get("source"),
            "category": document["metadata"].get("category"),
            "section": document["metadata"].get("section"),
            "page_number": document["metadata"].get("page_number"),
            "chunk_id": document["metadata"].get("chunk_id"),
        }
        for document in documents
    ]

    return {
        "retrieved_policy_docs": documents,
        "sources": sources,
        "tool_events": _event(
            state,
            "policy_retrieved",
            f"Retrieved {len(documents)} policy chunks",
        ),
    }


def similar_case_search_node(state: AgentState) -> dict[str, Any]:
    cases = search_historical(
        state.get("customer_message", ""),
        state.get("issue_type"),
        3,
    )

    return {
        "similar_cases": cases,
        "tool_events": _event(
            state,
            "similar_cases_compared",
            f"Found {len(cases)} historical cases",
        ),
    }


def policy_decision_node(state: AgentState) -> dict[str, Any]:
    context = {
        "message": state.get("customer_message", ""),
        "security_flags": state.get("security_flags") or [],
        "policy_exception": state.get("policy_exception") is True,
        "low_confidence": state.get("low_confidence") is True,
        "conflicting_data": state.get("conflicting_data") is True,
    }

    decision = evaluate_policy(
        state.get("issue_type", "other"),
        state.get("order_details") or None,
        context,
    )

    return {
        "policy_decision": decision.model_dump(),
        "confidence": decision.confidence,
        "requires_approval": decision.requires_approval is True,
        "tool_events": _event(
            state,
            "eligibility_checked",
            decision.policy_rule_applied,
        ),
    }


def resolution_planner_node(state: AgentState) -> dict[str, Any]:
    policy_decision = state["policy_decision"]
    recommendation: ResolutionRecommendation | None = None

    try:
        llm = _llm()

        if llm:
            recommendation = llm.with_structured_output(
                ResolutionRecommendation
            ).invoke(
                [
                    ("system", PLANNER_SYSTEM),
                    (
                        "human",
                        json.dumps(
                            {
                                "policy_decision": policy_decision,
                                "order_facts": state.get("order_details"),
                                "sources": state.get("sources"),
                                "historical_cases": state.get("similar_cases"),
                            },
                            default=str,
                        ),
                    ),
                ]
            )
    except Exception as exc:
        log_event(
            state["ticket_id"],
            "llm_fallback",
            {
                "node": "planner",
                "error": type(exc).__name__,
            },
        )

    recommendation = recommendation or ResolutionRecommendation(
        action=policy_decision["recommended_action"],
        customer_safe_explanation=policy_decision["decision_reason"],
        next_steps=(
            policy_decision.get("missing_information", [])
            or ["Review and save the draft response"]
        ),
        status=(
            "pending_approval"
            if policy_decision.get("requires_approval") is True
            else "draft"
        ),
    )

    return {
        "recommendation": recommendation.model_dump(),
        "tool_events": _event(
            state,
            "recommendation_generated",
            f"Recommended {recommendation.action}",
        ),
    }


def _draft_text(
    state: AgentState,
    pending: bool = False,
    rejected: bool = False,
) -> str:
    opening = (
        "Thank you for contacting NovaCart. "
        "I’m sorry about the trouble with your order."
    )

    policy_decision = state.get("policy_decision", {})
    missing_information = policy_decision.get("missing_information", [])

    if rejected:
        return (
            f"{opening} A manager reviewed the proposed resolution but did not "
            "approve it. We’re escalating the case for the next safe step and "
            "will update you after review."
        )

    if pending:
        return (
            f"{opening} Based on the order details, we recommend "
            f"{policy_decision.get('recommended_action', 'a resolution')}. "
            "This is pending manager approval; no refund or replacement has "
            "been processed."
        )

    if policy_decision.get("eligibility") == "needs_information":
        return (
            f"{opening} To investigate safely, please provide "
            f"{', '.join(missing_information or ['the missing order details'])}."
        )

    suffix = (
        f" Please also provide {', '.join(missing_information)}."
        if missing_information
        else ""
    )

    return (
        f"{opening} Based on the available order details, the recommended "
        f"next step is "
        f"{policy_decision.get('recommended_action', 'further review').replace('_', ' ')}."
        f"{suffix} No financial action has been processed."
    )


def risk_assessment_node(state: AgentState) -> dict[str, Any]:
    decision = PolicyDecision.model_validate(
        state["policy_decision"]
    )

    requires_approval, reasons = assess_additional_risk(
        state.get("customer_message", ""),
        state.get("order_details"),
        decision,
        state.get("security_flags") or [],
        policy_exception=state.get("policy_exception") is True,
        conflicting_data=state.get("conflicting_data") is True,
    )

    requires_approval = requires_approval is True

    proposed_response = _draft_text(
        state,
        pending=requires_approval,
    )
    amount = (state.get("order_details") or {}).get("amount_inr")

    approval_payload = {
        "ticket_id": state["ticket_id"],
        "recommended_action": decision.recommended_action,
        "amount": amount,
        "reasons": reasons,
        "policy_citations": state.get("sources", []),
        "proposed_customer_reply": proposed_response,
        "options": [
            "approve",
            "reject",
            "edit_and_approve",
        ],
    }

    return {
        "requires_approval": requires_approval,
        "risk_reasons": reasons,
        "approval_payload": approval_payload,
        "drafted_customer_response": proposed_response,
        "tool_events": _event(
            state,
            (
                "approval_requested"
                if requires_approval
                else "risk_check_passed"
            ),
            (
                ", ".join(reasons)
                if reasons
                else "No approval trigger"
            ),
        ),
    }


def manager_approval_interrupt_node(
    state: AgentState,
) -> dict[str, Any]:
    response = interrupt(state["approval_payload"])

    response = (
        response
        if isinstance(response, dict)
        else {"decision": str(response)}
    )

    decision = response.get("decision", "reject")
    edited_response = response.get("edited_response", "")

    save_approval(
        state["ticket_id"],
        decision,
        response.get("reason", ""),
        edited_response,
    )
    log_event(
        state["ticket_id"],
        "manager_decision",
        {"decision": decision},
    )

    if decision == "reject":
        draft = _draft_text(state, rejected=True)
    elif decision == "edit_and_approve" and edited_response.strip():
        draft = sanitize_text(edited_response)
    else:
        draft = state["approval_payload"][
            "proposed_customer_reply"
        ].replace(
            "pending manager approval",
            "approved as a draft for the support agent",
        )

    return {
        "approval_decision": response,
        "drafted_customer_response": draft,
        "final_response": draft,
        "tool_events": _event(
            state,
            "manager_decision_recorded",
            decision,
        ),
    }


def draft_customer_response_node(state: AgentState) -> dict[str, Any]:
    if (
        state.get("drafted_customer_response")
        and state.get("requires_approval") is True
    ):
        draft = state["drafted_customer_response"]
    else:
        draft = _draft_text(state)

    return {
        "drafted_customer_response": draft,
        "final_response": draft,
        "tool_events": _event(
            state,
            "response_drafted",
            "Customer-safe response drafted",
        ),
    }


def persist_case_node(state: AgentState) -> dict[str, Any]:
    rejected = (
        state.get("approval_decision", {}).get("decision")
        == "reject"
    )

    status = (
        "escalated"
        if rejected
        else "resolved"
    )

    upsert_ticket(
        state["ticket_id"],
        state["thread_id"],
        state.get("order_id"),
        state["customer_message"],
        status,
        state.get("issue_type"),
        state.get("ticket_summary"),
    )

    add_message(
        state["ticket_id"],
        "assistant",
        state.get("final_response")
        or state.get("drafted_customer_response", ""),
    )

    save_resolution_draft.invoke(
        {
            "ticket_id": state["ticket_id"],
            "recommendation": state.get("recommendation", {}),
            "customer_response": (
                state.get("final_response")
                or state.get("drafted_customer_response", "")
            ),
            "sources": state.get("sources", []),
        }
    )

    if rejected:
        create_escalation_draft.invoke(
            {
                "ticket_id": state["ticket_id"],
                "reason": "Manager rejected proposed resolution",
                "recommendation": state.get("recommendation", {}),
                "evidence": state.get("sources", []),
            }
        )

    log_event(
        state["ticket_id"],
        "case_persisted",
        {
            "status": status,
            "tools": state.get("tool_events", []),
        },
    )

    return {
        "tool_events": _event(
            state,
            "case_persisted",
            f"Case saved as {status}",
        ),
    }