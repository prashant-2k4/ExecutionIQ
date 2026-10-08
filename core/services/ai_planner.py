"""AI Goal Interpreter / Smart Task Breakdown.

The AI layer only turns natural language into a structured plan. Every value
it returns is validated here before anything is saved; numerical prediction
is left entirely to the Execution Engine.
"""

import json
import logging
import re
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from django.conf import settings
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

MAX_TASKS = 30


class AIPlannerError(Exception):
    """Raised when a plan cannot be generated or the AI output is unusable.

    The message is safe to show to users.
    """


class PlannedTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    estimated_hours: Decimal = Field(gt=0, le=200)
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("priority", mode="before")
    @classmethod
    def normalise_priority(cls, value):
        if not isinstance(value, str):
            return "MEDIUM"
        value = value.strip().upper()
        if value in ("CRITICAL", "URGENT"):
            return "HIGH"
        return value if value in ("LOW", "MEDIUM", "HIGH") else "MEDIUM"

    @field_validator("estimated_hours", mode="after")
    @classmethod
    def round_hours(cls, value):
        return value.quantize(Decimal("0.01"))


class GoalPlan(BaseModel):
    goal: str = Field(min_length=1, max_length=200)
    tasks: list[PlannedTask] = Field(min_length=1, max_length=MAX_TASKS)

    @field_validator("goal", mode="before")
    @classmethod
    def strip_goal(cls, value):
        return value.strip() if isinstance(value, str) else value

    @property
    def total_estimated_hours(self):
        return sum((task.estimated_hours for task in self.tasks), Decimal("0"))


PROMPT_TEMPLATE = """
You are the AI planning component of ExecutionIQ.

User goal:
{goal_text}

Break this goal into realistic, meaningful tasks (at most {max_tasks}).

Return ONLY a JSON object with exactly this shape:
{{
  "goal": "<short goal title, max 200 characters>",
  "tasks": [
    {{"title": "<task title>", "estimated_hours": <positive number>, "priority": "LOW" | "MEDIUM" | "HIGH"}}
  ]
}}
"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_plan(raw_text, fallback_title=""):
    """Parse and validate raw AI output into a GoalPlan.

    Tolerates markdown code fences and a missing goal title (falls back to
    ``fallback_title``). Raises AIPlannerError on anything unusable.
    """
    text = _FENCE_RE.sub("", (raw_text or "").strip())

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIPlannerError("The AI returned a plan that could not be read.") from exc

    if not isinstance(data, dict):
        raise AIPlannerError("The AI returned a plan in an unexpected format.")

    if not data.get("goal") and fallback_title:
        data["goal"] = fallback_title[:200]

    try:
        return GoalPlan.model_validate(data)
    except ValidationError as exc:
        raise AIPlannerError("The AI returned an incomplete or invalid plan.") from exc


@lru_cache(maxsize=1)
def _get_client():
    if not settings.GEMINI_API_KEY:
        raise AIPlannerError("The AI planner is not configured (missing GEMINI_API_KEY).")

    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=60000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def generate_goal_plan(goal_text):
    """Ask Gemini for a task breakdown and return a validated GoalPlan."""
    prompt = PROMPT_TEMPLATE.format(goal_text=goal_text, max_tasks=MAX_TASKS)

    try:
        interaction = _get_client().interactions.create(
            model=settings.GEMINI_MODEL,
            input=prompt,
        )
    except AIPlannerError:
        raise
    except Exception as exc:
        logger.exception("Gemini request failed")
        raise AIPlannerError(
            "The AI planner is temporarily unavailable. Please try again."
        ) from exc

    try:
        return parse_plan(interaction.output_text, fallback_title=goal_text)
    except AIPlannerError:
        logger.warning("Rejected AI plan output: %.500s", interaction.output_text)
        raise
