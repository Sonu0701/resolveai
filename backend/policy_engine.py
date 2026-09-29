from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.models import PolicyDecision


HIGH_VALUE_INR = 10000


def _days_since_delivery(order: dict[str, Any]) -> int | None:
    raw = order.get("delivery_date")

    if not raw:
        return None

    try:
        return (date.today() - datetime.fromisoformat(str(raw)).date()).days
    except ValueError:
        return None


def _signals(context: dict[str, Any]) -> list[str]:
    """
    Return actual risk signals from context values.

    Never convert the entire context dictionary into text. Doing that makes
    field names such as 'security_flags' look like a real security signal,
    causing safe low-risk cases to be incorrectly routed for approval.
    """
    message = str(context.get("message") or "").lower()
    security_flags = context.get("security_flags") or []
    signals: list[str] = []

    message_signals = (
        ("legal", "legal threat"),
        ("chargeback", "chargeback"),
        ("fraud", "fraud indicator"),
        ("hacked", "security concern"),
        ("account compromised", "security concern"),
        ("third time", "repeated unresolved contact"),
        ("repeated unresolved", "repeated unresolved contact"),
        ("conflicting", "conflicting data"),
    )

    for needle, label in message_signals:
        if needle in message:
            signals.append(label)

    if security_flags:
        signals.append("suspicious instruction")

    if context.get("legal_threat") is True:
        signals.append("legal threat")

    if context.get("chargeback") is True:
        signals.append("chargeback")

    if context.get("fraud_indicator") is True:
        signals.append("fraud indicator")

    if context.get("account_security") is True:
        signals.append("security concern")

    if context.get("repeated_unresolved") is True:
        signals.append("repeated unresolved contact")

    if context.get("conflicting_data") is True:
        signals.append("conflicting data")

    return list(dict.fromkeys(signals))


def _has_active_return_or_refund(order: dict[str, Any], status: str) -> bool:
    """
    Return True only if the order is genuinely in a return/refund workflow.

    Values including 'none', 'not_requested', and 'not_returned' are not
    active refund states and must not route the request incorrectly.
    """
    return_status = str(order.get("return_status") or "").strip().lower()

    active_return_statuses = {
        "returned",
        "return_initiated",
        "return_requested",
        "return_received",
        "refund_initiated",
        "refund_processing",
        "refund_completed",
    }

    return status == "returned" or return_status in active_return_statuses


def evaluate_policy(
    issue_type: str,
    order: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> PolicyDecision:
    context = context or {}

    if not order:
        return PolicyDecision(
            recommended_action="ask_customer_for_missing_information",
            eligibility="needs_information",
            decision_reason=(
                "A valid order is required before an order-specific resolution "
                "can be recommended."
            ),
            policy_rule_applied="ORDER.REQUIRED",
            missing_information=["valid order ID"],
            confidence=0.98,
        )

    amount = float(order.get("amount_inr") or 0)
    status = str(order.get("status") or "").strip().lower()
    days = _days_since_delivery(order)
    high_value_order = amount > HIGH_VALUE_INR
    risk_signals = _signals(context)
    notes = str(order.get("notes") or "").lower()

    base_approval = (
        high_value_order
        or bool(risk_signals)
        or context.get("policy_exception") is True
        or context.get("low_confidence") is True
        or context.get("conflicting_data") is True
    )

    if issue_type in {"damaged_product", "product_defect"}:
        if "intentional misuse" in notes or "customer misuse" in notes:
            return PolicyDecision(
                recommended_action="escalate_to_human_manager",
                eligibility="not_eligible",
                decision_reason=(
                    "Order notes indicate possible misuse; automatic damaged-item "
                    "resolution is blocked."
                ),
                policy_rule_applied="DAMAGE.MISUSE_REVIEW",
                requires_approval=True,
                confidence=0.93,
            )

        if status != "delivered" or days is None:
            return PolicyDecision(
                recommended_action="ask_customer_for_missing_information",
                eligibility="needs_information",
                decision_reason=(
                    "Delivery must be confirmed before applying the damaged-product window."
                ),
                policy_rule_applied="DAMAGE.DELIVERY_REQUIRED",
                requires_approval=base_approval,
                missing_information=["delivery confirmation", "damage photos"],
                confidence=0.88,
            )

        if days <= 30:
            stock_available = bool(order.get("replacement_stock_available"))
            action = "replacement" if stock_available else "refund"

            return PolicyDecision(
                recommended_action=action,
                eligibility="conditional",
                decision_reason=(
                    "Damage was reported within the 30-day window; "
                    f"{'replacement stock is available' if stock_available else 'replacement stock is unavailable'}."
                ),
                policy_rule_applied="DAMAGE.WITHIN_30_DAYS",
                requires_approval=base_approval,
                missing_information=["damage photos"],
                confidence=0.96,
            )

        return PolicyDecision(
            recommended_action="escalate_to_human_manager",
            eligibility="not_eligible",
            decision_reason=(
                f"Delivery was {days} days ago, outside the standard "
                "30-day damaged-item window."
            ),
            policy_rule_applied="DAMAGE.OUTSIDE_30_DAYS",
            requires_approval=True,
            confidence=0.95,
        )

    if issue_type == "refund_request":
        if status in {"in_transit", "delayed"}:
            action = (
                "shipment_investigation"
                if status == "delayed"
                else "wait_provide_delivery_update"
            )

            return PolicyDecision(
                recommended_action=action,
                eligibility="not_eligible",
                decision_reason=(
                    "An undelivered order cannot receive a normal post-delivery refund."
                ),
                policy_rule_applied="REFUND.UNDELIVERED",
                requires_approval=base_approval,
                confidence=0.97,
            )

        if _has_active_return_or_refund(order, status):
            return_status = order.get("return_status") or status

            return PolicyDecision(
                recommended_action="wait_provide_refund_update",
                eligibility="conditional",
                decision_reason=(
                    f"Return status is {return_status}; provide the current "
                    "refund status rather than duplicating it."
                ),
                policy_rule_applied="REFUND.RETURN_STATUS",
                requires_approval=base_approval,
                confidence=0.94,
            )

        if days is not None and days <= 30:
            return PolicyDecision(
                recommended_action="refund",
                eligibility="conditional",
                decision_reason=(
                    "The delivered order is within the standard 30-day return window."
                ),
                policy_rule_applied="REFUND.WITHIN_30_DAYS",
                requires_approval=base_approval,
                missing_information=["return condition confirmation"],
                confidence=0.94,
            )

        return PolicyDecision(
            recommended_action="reject_automatic_refund",
            eligibility="not_eligible",
            decision_reason=(
                "The request is outside the standard 30-day return window; "
                "any exception needs manager approval."
            ),
            policy_rule_applied="REFUND.OUTSIDE_30_DAYS",
            requires_approval=True,
            confidence=0.96,
        )

    if issue_type == "delayed_delivery":
        expected_delivery = order.get("expected_delivery_date")
        delay_days = 0

        if expected_delivery:
            try:
                delay_days = max(
                    0,
                    (
                        date.today()
                        - datetime.fromisoformat(str(expected_delivery)).date()
                    ).days,
                )
            except ValueError:
                delay_days = 0

        action = (
            "shipment_investigation"
            if status == "delayed" or delay_days >= 7
            else "wait_provide_delivery_update"
        )

        return PolicyDecision(
            recommended_action=action,
            eligibility="conditional",
            decision_reason=(
                f"Latest shipping state is {status}; estimated delay is {delay_days} days."
            ),
            policy_rule_applied="SHIPPING.DELAY",
            requires_approval=base_approval or delay_days >= 14,
            confidence=0.92,
        )

    if issue_type == "delivered_not_received":
        missing_information = (
            [] if order.get("address_verified") else ["address verification"]
        )

        return PolicyDecision(
            recommended_action="shipment_investigation",
            eligibility="conditional",
            decision_reason=(
                "A delivered scan with a non-receipt claim requires carrier "
                "investigation and address verification."
            ),
            policy_rule_applied="SHIPPING.DNR_INVESTIGATION",
            requires_approval=base_approval,
            missing_information=missing_information,
            confidence=0.96,
        )

    if issue_type == "wrong_item":
        if days is not None and days <= 30:
            return PolicyDecision(
                recommended_action="replacement",
                eligibility="conditional",
                decision_reason=(
                    "The wrong-item claim is within 30 days and can proceed "
                    "after item verification."
                ),
                policy_rule_applied="WRONG_ITEM.WITHIN_30_DAYS",
                requires_approval=base_approval,
                missing_information=["photo of received item and shipping label"],
                confidence=0.94,
            )

        return PolicyDecision(
            recommended_action="escalate_to_human_manager",
            eligibility="not_eligible",
            decision_reason=(
                "The wrong-item claim is outside the standard claim window "
                "or the delivery date is unavailable."
            ),
            policy_rule_applied="WRONG_ITEM.REVIEW",
            requires_approval=True,
            confidence=0.88,
        )

    if issue_type == "account_or_security":
        return PolicyDecision(
            recommended_action="escalate_to_human_manager",
            eligibility="conditional",
            decision_reason=(
                "Account or security concerns require specialist human review."
            ),
            policy_rule_applied="ESCALATION.SECURITY",
            requires_approval=True,
            confidence=0.98,
        )

    return PolicyDecision(
        recommended_action="ask_customer_for_missing_information",
        eligibility="needs_information",
        decision_reason=(
            "The issue needs more details before a safe policy decision can be made."
        ),
        policy_rule_applied="GENERAL.MORE_INFO",
        requires_approval=base_approval,
        missing_information=["issue details"],
        confidence=0.75,
    )


def assess_additional_risk(
    message: str,
    order: dict[str, Any] | None,
    decision: PolicyDecision,
    security_flags: list[str] | None = None,
    *,
    policy_exception: bool = False,
    conflicting_data: bool = False,
) -> tuple[bool, list[str]]:
    """
    Return a strict Boolean approval decision and the corresponding reasons.

    Approval is required only when a real risk signal exists. The function
    intentionally returns a Boolean rather than letting downstream code infer
    approval from string truthiness or incomplete state.
    """
    text = (message or "").lower()
    reasons: list[str] = []

    if order and float(order.get("amount_inr") or 0) > HIGH_VALUE_INR:
        reasons.append("Order value exceeds ₹10,000")

    risk_signals = (
        ("legal", "Legal threat"),
        ("chargeback", "Chargeback mentioned"),
        ("fraud", "Fraud indicator"),
        ("hacked", "Account compromise"),
        ("account compromised", "Account compromise"),
        ("third time", "Repeated unresolved contact"),
        ("repeated unresolved", "Repeated unresolved contact"),
    )

    for needle, label in risk_signals:
        if needle in text:
            reasons.append(label)

    if decision.requires_approval is True:
        reasons.append("Policy rule requires approval")

    if policy_exception is True:
        reasons.append("Policy exception requires approval")

    if decision.confidence < 0.75:
        reasons.append("Low decision confidence")

    if security_flags:
        reasons.append("Suspicious instruction or prompt-injection pattern")

    order_notes = str((order or {}).get("notes") or "").lower()
    order_status = str((order or {}).get("status") or "").lower()
    tracking_status = str(
        (order or {}).get("shipping_tracking_status") or ""
    ).lower()

    status_conflict = bool(
        order_status
        and tracking_status
        and order_status != tracking_status
        and {order_status, tracking_status} != {"delayed", "in_transit"}
    )

    if (
        conflicting_data is True
        or "conflicting" in order_notes
        or status_conflict
    ):
        reasons.append("Conflicting order or tracking data")

    unique_reasons = list(dict.fromkeys(reasons))
    requires_approval: bool = bool(unique_reasons)

    return requires_approval, unique_reasons