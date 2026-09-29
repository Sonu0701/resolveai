from __future__ import annotations

import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from backend.agent_nodes import (
    draft_customer_response_node,
    knowledge_retrieval_node,
    manager_approval_interrupt_node,
    order_lookup_node,
    persist_case_node,
    policy_decision_node,
    resolution_planner_node,
    risk_assessment_node,
    similar_case_search_node,
    ticket_intake_node,
    triage_node,
)
from backend.config import settings
from backend.models import AgentState


def _route_after_intake(state: AgentState) -> str:
    return "end" if not state.get("customer_message") else "triage"


def _route_approval(state: AgentState) -> str:
    """
    Route only from an explicit Boolean approval decision.

    A missing value safely defaults to the normal draft flow. Invalid values
    such as "True", "False", 1, 0, tuples, or None raise an error so the
    workflow cannot silently route risky cases incorrectly.
    """
    requires_approval = state.get("requires_approval", False)

    if requires_approval is True:
        return "approval"

    if requires_approval is False:
        return "draft"

    raise TypeError(
        "requires_approval must be a Boolean before approval routing. "
        f"Received {requires_approval!r} of type {type(requires_approval).__name__}."
    )


@lru_cache(maxsize=1)
def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("intake", ticket_intake_node)
    builder.add_node("triage", triage_node)
    builder.add_node("order_lookup", order_lookup_node)
    builder.add_node("policy_retrieval", knowledge_retrieval_node)
    builder.add_node("similar_cases", similar_case_search_node)
    builder.add_node("policy_decision", policy_decision_node)
    builder.add_node("planner", resolution_planner_node)
    builder.add_node("risk", risk_assessment_node)
    builder.add_node("approval", manager_approval_interrupt_node)
    builder.add_node("draft", draft_customer_response_node)
    builder.add_node("persist", persist_case_node)

    builder.add_edge(START, "intake")

    builder.add_conditional_edges(
        "intake",
        _route_after_intake,
        {
            "triage": "triage",
            "end": END,
        },
    )

    builder.add_edge("triage", "order_lookup")
    builder.add_edge("order_lookup", "policy_retrieval")
    builder.add_edge("policy_retrieval", "similar_cases")
    builder.add_edge("similar_cases", "policy_decision")
    builder.add_edge("policy_decision", "planner")
    builder.add_edge("planner", "risk")

    builder.add_conditional_edges(
        "risk",
        _route_approval,
        {
            "approval": "approval",
            "draft": "draft",
        },
    )

    builder.add_edge("approval", "draft")
    builder.add_edge("draft", "persist")
    builder.add_edge("persist", END)

    connection = sqlite3.connect(
        str(settings.database_path),
        check_same_thread=False,
    )

    return builder.compile(
        checkpointer=SqliteSaver(connection),
    )