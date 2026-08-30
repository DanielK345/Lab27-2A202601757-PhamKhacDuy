"""LangGraph workflow for churn-risk decisions with human approval."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from models import AuditEntry

CONFIDENCE_THRESHOLD = 0.85
HIGH_RISK_ACTION = "increase_credit_limit"
AGENT_ID = "churn-risk-agent"
AUDIT_LOG_PATH = Path(__file__).with_name("audit_log.json")


class RequiredGraphState(TypedDict):
    """Fields required by the assignment and retained across interruptions."""

    customer_id: str
    proposed_action: str
    confidence_score: float
    reasoning: str
    human_decision: str | None


class GraphState(RequiredGraphState, total=False):
    """Complete workflow state, including inputs and execution metadata."""

    total_operating_income: float
    churn_probability: float
    reviewer_id: str
    execution_status: str
    executed_action: str | None


_audit_lock = RLock()


def _bounded_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 2)


def evaluate_customer(state: GraphState) -> dict[str, Any]:
    """Produce a deterministic mock-agent recommendation from customer data.

    The implementation deliberately avoids an external LLM/API, so the lab is
    reproducible and does not require credentials.
    """

    income = max(0.0, float(state.get("total_operating_income", 0.0)))
    churn = _bounded_score(float(state.get("churn_probability", 0.0)))

    if churn >= 0.70 and income >= 50_000_000:
        action = HIGH_RISK_ACTION
        confidence = _bounded_score(0.82 + (churn * 0.16))
        reasoning = (
            "Customer has high churn probability and sufficient operating "
            "income; a credit-limit increase may improve retention. This is "
            "a financial action and still requires human approval."
        )
    elif churn >= 0.45:
        action = "send_email"
        confidence = _bounded_score(0.80 + (abs(churn - 0.60) * 0.30))
        reasoning = (
            "Customer has moderate churn probability. A retention email is a "
            "low-impact intervention, but confidence determines whether it "
            "can be executed automatically."
        )
    else:
        action = "send_email"
        confidence = _bounded_score(0.90 + ((0.45 - churn) * 0.12))
        reasoning = (
            "Customer has low churn probability; a routine engagement email "
            "is an appropriate low-risk action."
        )

    return {
        "proposed_action": action,
        "confidence_score": confidence,
        "reasoning": reasoning,
        "human_decision": None,
        "execution_status": "evaluated",
        "executed_action": None,
    }


def route_action(state: GraphState) -> str:
    """Apply the hard policy first, then confidence-based routing."""

    action = state.get("proposed_action", "")
    confidence = float(state.get("confidence_score", 0.0))

    # update_state() recomputes edges from the interrupted evaluation node.
    # Once a reviewer has decided, keep the workflow on the reviewed branch;
    # an edited low-risk action must not accidentally become an auto-execution.
    if state.get("human_decision") in {"approve", "reject", "edit"}:
        return "execute_high_risk_action"
    if action == HIGH_RISK_ACTION:
        return "execute_high_risk_action"
    if confidence >= CONFIDENCE_THRESHOLD:
        return "execute_low_risk_action"
    return "execute_high_risk_action"


def _append_audit_entry(entry: AuditEntry, path: Path | None = None) -> None:
    """Append an entry without silently discarding the existing history."""

    destination = path or AUDIT_LOG_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)

    with _audit_lock:
        if destination.exists():
            raw = destination.read_text(encoding="utf-8").strip()
            entries = json.loads(raw) if raw else []
            if not isinstance(entries, list):
                raise ValueError("audit log must contain a JSON array")
        else:
            entries = []

        entries.append(entry.model_dump())
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        temporary.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)


def _audit(state: GraphState, *, reviewer_id: str, decision: str) -> None:
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        agent_id=AGENT_ID,
        action=state["proposed_action"],
        confidence=state["confidence_score"],
        reviewer_id=reviewer_id,
        decision=decision,
    )
    _append_audit_entry(entry)


def execute_low_risk_action(state: GraphState) -> dict[str, Any]:
    """Auto-execute an allowed, high-confidence low-risk action."""

    _audit(state, reviewer_id="system", decision="auto_execute")
    return {
        "execution_status": "executed",
        "executed_action": state["proposed_action"],
    }


def execute_high_risk_action(state: GraphState) -> dict[str, Any]:
    """Execute, abort, or execute an edited action after human review."""

    decision = (state.get("human_decision") or "").lower()
    if decision not in {"approve", "reject", "edit"}:
        raise ValueError("high-risk action requires approve, reject, or edit")

    reviewer_id = state.get("reviewer_id", "unknown-reviewer")
    _audit(state, reviewer_id=reviewer_id, decision=decision)

    if decision == "reject":
        return {"execution_status": "aborted", "executed_action": None}
    return {
        "execution_status": "executed",
        "executed_action": state["proposed_action"],
    }


def build_graph() -> Any:
    """Build a fresh graph with an in-memory persistent checkpointer."""

    builder = StateGraph(GraphState)
    builder.add_node("evaluate_customer", evaluate_customer)
    builder.add_node("execute_low_risk_action", execute_low_risk_action)
    builder.add_node("execute_high_risk_action", execute_high_risk_action)

    builder.add_edge(START, "evaluate_customer")
    builder.add_conditional_edges(
        "evaluate_customer",
        route_action,
        {
            "execute_low_risk_action": "execute_low_risk_action",
            "execute_high_risk_action": "execute_high_risk_action",
        },
    )
    builder.add_edge("execute_low_risk_action", END)
    builder.add_edge("execute_high_risk_action", END)

    memory = MemorySaver()
    return builder.compile(
        checkpointer=memory,
        interrupt_before=["execute_high_risk_action"],
    )


# Convenient import for scripts and basic exercises. The Streamlit app creates
# one graph per browser session so that its in-memory checkpoints are isolated.
graph = build_graph()
