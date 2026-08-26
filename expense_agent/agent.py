# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from expense_agent.config import PROJECT_ID

if os.environ.get("GOOGLE_CLOUD_PROJECT", "").isdigit():
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID

import base64
import json
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.events.request_input import RequestInput
from google.adk.workflow import START, Workflow, node
from google.genai import types
from pydantic import BaseModel, Field

from expense_agent.config import EXPENSE_APPROVAL_THRESHOLD, MODEL_NAME


# ---------------------------------------------------------------------
# Schemas and Models
# ---------------------------------------------------------------------
class ExpenseReport(BaseModel):
    """Structured model representing an expense report."""

    amount: float = Field(default=0.0, description="The total amount of the expense.")
    submitter: str = Field(
        default="Unknown", description="The person who submitted the expense."
    )
    category: str = Field(default="General", description="The category of the expense.")
    description: str = Field(default="", description="Description of the expense item.")
    date: str = Field(default="", description="The date of the expense.")


class RiskAssessment(BaseModel):
    """Structured risk judgment output from the LLM."""

    risk_level: str = Field(description="Risk level evaluation: Low, Medium, or High.")
    risk_factors: list[str] = Field(
        description="List of identified risk factors, anomalies, or compliance violations."
    )
    explanation: str = Field(
        description="Detailed explanation of the risk assessment reasoning."
    )


class HumanDecision(BaseModel):
    """Schema for human approval decision."""

    decision: str = Field(description="Enter 'yes' to approve or 'no' to reject.")


# ---------------------------------------------------------------------
# Helper Utilities
# ---------------------------------------------------------------------
def parse_expense_event(node_input: Any) -> dict[str, Any]:
    """Robustly parses an incoming event that may be JSON or base64-encoded Pub/Sub.

    Handles:
      - Raw dictionary containing the expense.
      - JSON string containing the expense.
      - Dictionary with a 'data' key (which may be base64-encoded or raw JSON).
      - Pub/Sub push message format: {"message": {"data": "..."}}
    """
    raw_data = None
    if isinstance(node_input, dict):
        raw_data = node_input
    elif isinstance(node_input, str):
        try:
            raw_data = json.loads(node_input)
        except Exception:
            raw_data = node_input
    elif hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text or ""
        try:
            raw_data = json.loads(text)
        except Exception:
            raw_data = text
    else:
        try:
            raw_data = json.loads(str(node_input))
        except Exception:
            raw_data = str(node_input)

    expense_data = None
    if isinstance(raw_data, dict):
        data_val = None
        if "data" in raw_data:
            data_val = raw_data["data"]
        elif (
            "message" in raw_data
            and isinstance(raw_data["message"], dict)
            and "data" in raw_data["message"]
        ):
            data_val = raw_data["message"]["data"]
        else:
            expense_data = raw_data

        if data_val is not None:
            if isinstance(data_val, str):
                # Try base64 decoding
                try:
                    decoded = base64.b64decode(data_val).decode("utf-8")
                    expense_data = json.loads(decoded)
                except Exception:
                    # Fallback to direct JSON string parsing
                    try:
                        expense_data = json.loads(data_val)
                    except Exception:
                        expense_data = {"description": data_val}
            elif isinstance(data_val, dict):
                expense_data = data_val

    if expense_data is None:
        if isinstance(raw_data, dict):
            expense_data = raw_data
        else:
            expense_data = {}

    return expense_data


# ---------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------


# 1. Parse Event Node
def parse_expense(ctx: Context, node_input: Any) -> Event:
    """Extracts raw event details and casts them to the structured ExpenseReport schema."""
    expense_dict = parse_expense_event(node_input)

    expense = ExpenseReport(
        amount=float(expense_dict.get("amount", 0.0)),
        submitter=str(expense_dict.get("submitter", "Unknown")),
        category=str(expense_dict.get("category", "General")),
        description=str(expense_dict.get("description", "")),
        date=str(expense_dict.get("date", "")),
    )

    return Event(
        output=expense,
        actions=EventActions(state_delta={"expense": expense.model_dump()}),
    )


# 2. Routing Decision Node
def route_expense(ctx: Context, node_input: ExpenseReport) -> Event:
    """Implements routing rule using configured threshold:
    - Invalid/empty expense -> invalid
    - < $100 -> auto_approve
    - >= $100 -> llm_review
    """
    if node_input.amount <= 0.0 or not node_input.description:
        return Event(output=node_input, actions=EventActions(route="invalid"))
    elif node_input.amount < EXPENSE_APPROVAL_THRESHOLD:
        return Event(output=node_input, actions=EventActions(route="auto_approve"))
    else:
        return Event(output=node_input, actions=EventActions(route="llm_review"))


def invalid_input(ctx: Context, node_input: ExpenseReport):
    """Handles cases where the input message couldn't be parsed into a valid expense."""
    msg = (
        "⚠️ I couldn't parse any valid expense details from your message. "
        "Please provide the expense amount, description, and date (e.g., 'Spent $50 on lunch')."
    )
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    )
    yield Event(output={"status": "Invalid Input", "approved": False})


# 3. LLM Risk Analyzer Node (Only for expenses >= threshold)
risk_analyzer = LlmAgent(
    name="risk_analyzer",
    model=MODEL_NAME,
    instruction=(
        "Analyze the provided expense report for potential risk factors, anomalies, or compliance violations.\n"
        "1. Check description alignment with category.\n"
        "2. Check if the amount seems reasonable for the description.\n"
        "Determine the risk level (Low, Medium, or High), list any risk factors, and explain your reasoning."
    ),
    output_schema=RiskAssessment,
)


# 4. Auto-Approval Node
def auto_approve(node_input: ExpenseReport) -> Event:
    """Auto-approves expenses under the threshold without LLM involvement."""
    msg = f"Auto-Approved: Expense of ${node_input.amount} for '{node_input.description}' is under the limit."
    return Event(
        output={"approved": True, "reason": "Under threshold", "message": msg},
        actions=EventActions(
            state_delta={"approved": True, "reason": "Under threshold"}
        ),
    )


# 5. Human-in-the-Loop Review Node
@node(rerun_on_resume=True)
async def human_review(ctx: Context, node_input: Any):
    """Raises alert and pauses for human decision (yes/no) before LLM risk assessment."""
    expense_dict = {}
    if isinstance(node_input, ExpenseReport):
        expense_dict = node_input.model_dump()
    elif isinstance(node_input, dict):
        expense_dict = node_input
    else:
        expense_dict = ctx.state.get("expense", {})

    amount = expense_dict.get("amount", 0.0)
    submitter = expense_dict.get("submitter", "Unknown")
    desc = expense_dict.get("description", "")

    if not ctx.resume_inputs or "decision" not in ctx.resume_inputs:
        msg = (
            f"⚠️ [ALERT] Expense of ${amount} by {submitter} for '{desc}' requires human approval.\n\n"
            f"Approve or reject this expense? (reply 'yes' to approve, 'no' to reject)"
        )
        # Yield the message as a chat event so it appears in the playground/console
        yield Event(
            content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
        )
        # Yield the RequestInput to pause the workflow
        yield RequestInput(
            interrupt_id="decision",
            message=msg,
            response_schema=HumanDecision,
        )
        return

    decision_input = ctx.resume_inputs["decision"]
    if isinstance(decision_input, dict):
        decision = decision_input.get("decision", "").strip().lower()
    else:
        decision = str(decision_input).strip().lower()

    approved = decision in ["yes", "approve", "approved"]

    state_delta = {
        "approved": approved,
        "reason": f"Manager decision: {decision}",
    }

    if approved:
        # If approved, go to risk_analyzer and pass the expense data
        yield Event(
            output=node_input,
            actions=EventActions(route="approved", state_delta=state_delta),
        )
    else:
        # If rejected, go directly to record_outcome
        yield Event(
            output={"approved": False, "reason": f"Manager decision: {decision}"},
            actions=EventActions(route="rejected", state_delta=state_delta),
        )


# 6. Record Outcome Node
def record_outcome(ctx: Context, node_input: Any):
    """Records the final decision (approved/rejected) and emits completion output."""
    expense = ctx.state.get("expense", {})
    amount = expense.get("amount", 0.0)
    submitter = expense.get("submitter", "Unknown")
    desc = expense.get("description", "")

    approved = ctx.state.get("approved", False)
    reason = ctx.state.get("reason", "")

    status = "Approved" if approved else "Rejected"
    msg = f"Outcome recorded: Expense of ${amount} by {submitter} for '{desc}' was {status} ({reason})."

    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    )
    yield Event(output={"status": status, "approved": approved, "expense": expense})


# ---------------------------------------------------------------------
# Workflow Graph Wiring
# ---------------------------------------------------------------------
root_agent = Workflow(
    name="root_agent",
    edges=[
        (START, parse_expense),
        (parse_expense, route_expense),
        (
            route_expense,
            {
                "auto_approve": auto_approve,
                "llm_review": human_review,
                "invalid": invalid_input,
            },
        ),
        (
            human_review,
            {"approved": risk_analyzer, "rejected": record_outcome},
        ),
        (risk_analyzer, record_outcome),
        (auto_approve, record_outcome),
    ],
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
