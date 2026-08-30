"""Streamlit approval console for the churn-risk LangGraph workflow."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import streamlit as st

from graph import AUDIT_LOG_PATH, build_graph


def _initialize_session() -> None:
    if "graph" not in st.session_state:
        st.session_state.graph = build_graph()
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid4())


def _config() -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def _start_workflow(customer_id: str, income: float, churn: float) -> None:
    st.session_state.thread_id = str(uuid4())
    initial_state = {
        "customer_id": customer_id,
        "total_operating_income": income,
        "churn_probability": churn,
        "proposed_action": "",
        "confidence_score": 0.0,
        "reasoning": "",
        "human_decision": None,
    }
    st.session_state.graph.invoke(initial_state, _config())


def _resume(decision: str, reviewer_id: str, edited_action: str | None = None) -> None:
    if not reviewer_id.strip():
        raise ValueError("Reviewer ID is required")
    updates = {"human_decision": decision, "reviewer_id": reviewer_id.strip()}
    if decision == "edit":
        if not edited_action or not edited_action.strip():
            raise ValueError("Edited action must not be empty")
        updates["proposed_action"] = edited_action.strip()

    st.session_state.graph.update_state(_config(), updates)
    st.session_state.graph.invoke(None, _config())


def _render_audit_log(path: Path = AUDIT_LOG_PATH) -> None:
    with st.expander("Audit trail", expanded=False):
        if not path.exists():
            st.info("No audit entries yet.")
            return
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            st.error(f"Cannot read audit log: {exc}")
            return
        st.dataframe(entries, width="stretch")


def main() -> None:
    st.set_page_config(page_title="Churn Risk HITL", page_icon="🛡️")
    _initialize_session()

    st.title("Churn Risk Human-in-the-Loop")
    st.caption("Hard policy rules take precedence over agent confidence.")

    with st.form("customer_form"):
        customer_id = st.text_input("Customer ID", value="CUST001")
        income = st.number_input(
            "Total Operating Income (VND)", min_value=0.0, value=80_000_000.0
        )
        churn = st.slider(
            "Churn probability", min_value=0.0, max_value=1.0, value=0.80, step=0.01
        )
        submitted = st.form_submit_button("Evaluate customer", type="primary")

    if submitted:
        if not customer_id.strip():
            st.error("Customer ID is required.")
        else:
            _start_workflow(customer_id.strip(), income, churn)

    snapshot = st.session_state.graph.get_state(_config())
    values = snapshot.values
    if values and values.get("proposed_action"):
        st.subheader("Action card")
        col1, col2 = st.columns(2)
        col1.metric("Customer ID", values["customer_id"])
        col2.metric("Confidence", f"{values['confidence_score']:.0%}")
        st.code(values["proposed_action"], language=None)
        st.write(values["reasoning"])

        is_pending_review = "execute_high_risk_action" in snapshot.next
        if is_pending_review:
            st.warning("Execution is paused and requires human review.")
            reviewer_id = st.text_input("Reviewer ID", value="operator_01")
            edited_action = st.text_input(
                "Edited action", value=values["proposed_action"]
            )
            approve, reject, edit = st.columns(3)
            try:
                if approve.button("Approve", width="stretch"):
                    _resume("approve", reviewer_id)
                    st.rerun()
                if reject.button("Reject", width="stretch"):
                    _resume("reject", reviewer_id)
                    st.rerun()
                if edit.button("Edit & execute", width="stretch"):
                    _resume("edit", reviewer_id, edited_action)
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        else:
            status = values.get("execution_status", "unknown")
            if status == "aborted":
                st.error("The reviewer rejected the action. Nothing was executed.")
            elif status == "executed":
                st.success(f"Completed: {values.get('executed_action')}")

    _render_audit_log()


if __name__ == "__main__":
    main()
