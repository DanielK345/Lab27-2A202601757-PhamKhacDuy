import json
from pathlib import Path

import pytest

import graph as graph_module
from graph import (
    CONFIDENCE_THRESHOLD,
    build_graph,
    evaluate_customer,
    route_action,
)
from models import AuditEntry


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _state(action: str, confidence: float) -> dict:
    return {
        "customer_id": "CUST-TEST",
        "proposed_action": action,
        "confidence_score": confidence,
        "reasoning": "test",
        "human_decision": None,
    }


def test_audit_entry_validates_confidence() -> None:
    with pytest.raises(ValueError):
        AuditEntry(
            timestamp="2026-01-01T00:00:00Z",
            agent_id="agent",
            action="send_email",
            confidence=1.1,
            reviewer_id="system",
            decision="auto_execute",
        )


def test_evaluate_customer_outputs_required_fields() -> None:
    result = evaluate_customer(
        {
            **_state("", 0.0),
            "total_operating_income": 80_000_000,
            "churn_probability": 0.9,
        }
    )
    assert result["proposed_action"] == "increase_credit_limit"
    assert 0.0 <= result["confidence_score"] <= 1.0
    assert result["reasoning"]


def test_hard_policy_overrides_high_confidence() -> None:
    assert (
        route_action(_state("increase_credit_limit", 0.99))
        == "execute_high_risk_action"
    )


def test_high_confidence_low_risk_auto_executes() -> None:
    assert (
        route_action(_state("send_email", CONFIDENCE_THRESHOLD))
        == "execute_low_risk_action"
    )


def test_low_confidence_low_risk_escalates() -> None:
    assert route_action(_state("send_email", 0.82)) == "execute_high_risk_action"


def test_low_risk_flow_auto_executes_and_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_path = tmp_path / "audit.json"
    monkeypatch.setattr(graph_module, "AUDIT_LOG_PATH", audit_path)
    workflow = build_graph()
    config = _config("auto")

    result = workflow.invoke(
        {
            **_state("", 0.0),
            "total_operating_income": 20_000_000,
            "churn_probability": 0.2,
        },
        config,
    )

    assert result["execution_status"] == "executed"
    assert result["executed_action"] == "send_email"
    assert workflow.get_state(config).next == ()
    entries = json.loads(audit_path.read_text(encoding="utf-8"))
    assert entries[0]["decision"] == "auto_execute"


@pytest.mark.parametrize(
    ("decision", "expected_status", "expected_action"),
    [
        ("approve", "executed", "increase_credit_limit"),
        ("reject", "aborted", None),
        ("edit", "executed", "send_email_with_discount"),
    ],
)
def test_high_risk_interrupt_resume_and_audit(
    decision: str,
    expected_status: str,
    expected_action: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_path = tmp_path / "audit.json"
    monkeypatch.setattr(graph_module, "AUDIT_LOG_PATH", audit_path)
    workflow = build_graph()
    config = _config(decision)

    workflow.invoke(
        {
            **_state("", 0.0),
            "total_operating_income": 80_000_000,
            "churn_probability": 0.9,
        },
        config,
    )
    interrupted = workflow.get_state(config)
    assert interrupted.next == ("execute_high_risk_action",)
    assert interrupted.values["customer_id"] == "CUST-TEST"
    assert interrupted.values.get("execution_status") == "evaluated"
    assert not audit_path.exists()

    updates = {"human_decision": decision, "reviewer_id": "operator_01"}
    if decision == "edit":
        updates["proposed_action"] = "send_email_with_discount"
    workflow.update_state(config, updates)
    result = workflow.invoke(None, config)

    assert result["execution_status"] == expected_status
    assert result["executed_action"] == expected_action
    assert workflow.get_state(config).next == ()
    entries = json.loads(audit_path.read_text(encoding="utf-8"))
    assert entries[0]["decision"] == decision
    assert entries[0]["reviewer_id"] == "operator_01"
    assert entries[0]["action"] == (expected_action or "increase_credit_limit")


def test_audit_history_is_appended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_path = tmp_path / "audit.json"
    monkeypatch.setattr(graph_module, "AUDIT_LOG_PATH", audit_path)
    for thread_id in ("first", "second"):
        workflow = build_graph()
        workflow.invoke(
            {
                **_state("", 0.0),
                "total_operating_income": 10_000_000,
                "churn_probability": 0.1,
            },
            _config(thread_id),
        )

    assert len(json.loads(audit_path.read_text(encoding="utf-8"))) == 2
