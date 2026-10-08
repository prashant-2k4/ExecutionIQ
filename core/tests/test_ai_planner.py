from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import Goal, Task
from core.services import ai_planner
from core.services.ai_planner import AIPlannerError, generate_goal_plan, parse_plan
from core.services.goal_builder import create_goal_from_plan

VALID_PLAN = """
{
  "goal": "Learn Python",
  "tasks": [
    {"title": "Basics", "estimated_hours": 10, "priority": "high"},
    {"title": "Projects", "estimated_hours": "12.5", "priority": "Critical"},
    {"title": "Review", "estimated_hours": 3, "priority": "whenever"}
  ]
}
"""


class ParsePlanTests(TestCase):
    def test_valid_plan_is_parsed_and_normalised(self):
        plan = parse_plan(VALID_PLAN)

        self.assertEqual(plan.goal, "Learn Python")
        self.assertEqual([t.priority for t in plan.tasks], ["HIGH", "HIGH", "MEDIUM"])
        self.assertEqual(plan.tasks[1].estimated_hours, Decimal("12.50"))
        self.assertEqual(plan.total_estimated_hours, Decimal("25.50"))

    def test_markdown_code_fences_are_tolerated(self):
        plan = parse_plan(f"```json\n{VALID_PLAN}\n```")
        self.assertEqual(len(plan.tasks), 3)

    def test_missing_goal_title_uses_fallback(self):
        plan = parse_plan(
            '{"tasks": [{"title": "A", "estimated_hours": 1}]}',
            fallback_title="My goal text",
        )
        self.assertEqual(plan.goal, "My goal text")

    def test_invalid_outputs_are_rejected(self):
        invalid_outputs = [
            "",
            "not json",
            "[1, 2, 3]",
            '{"goal": "X", "tasks": []}',
            '{"goal": "X", "tasks": [{"title": "A", "estimated_hours": -2}]}',
            '{"goal": "X", "tasks": [{"title": "A", "estimated_hours": "lots"}]}',
            '{"goal": "X", "tasks": [{"title": "", "estimated_hours": 2}]}',
            '{"goal": "X", "tasks": [{"estimated_hours": 2}]}',
        ]
        for raw in invalid_outputs:
            with self.subTest(raw=raw), self.assertRaises(AIPlannerError):
                parse_plan(raw)


class GenerateGoalPlanTests(TestCase):
    def tearDown(self):
        ai_planner._get_client.cache_clear()

    @override_settings(GEMINI_API_KEY="")
    def test_missing_api_key_raises_friendly_error(self):
        ai_planner._get_client.cache_clear()
        with self.assertRaisesMessage(AIPlannerError, "not configured"):
            generate_goal_plan("Learn Python")

    def test_api_failure_raises_friendly_error(self):
        client = SimpleNamespace(
            interactions=SimpleNamespace(create=Mock(side_effect=RuntimeError("boom")))
        )
        with patch.object(ai_planner, "_get_client", return_value=client),                 self.assertLogs("core.services.ai_planner", level="ERROR"):
            with self.assertRaisesMessage(AIPlannerError, "temporarily unavailable"):
                generate_goal_plan("Learn Python")

    def test_successful_response_returns_plan(self):
        client = SimpleNamespace(
            interactions=SimpleNamespace(create=lambda **kw: SimpleNamespace(output_text=VALID_PLAN))
        )
        with patch.object(ai_planner, "_get_client", return_value=client):
            plan = generate_goal_plan("Learn Python")
        self.assertEqual(plan.goal, "Learn Python")


class CreateGoalFromPlanTests(TestCase):
    def test_goal_and_tasks_are_saved(self):
        user = User.objects.create_user("alice")
        deadline = date.today() + timedelta(days=30)

        goal = create_goal_from_plan(
            user=user,
            plan=parse_plan(VALID_PLAN),
            goal_text="I want to learn Python",
            deadline=deadline,
            daily_available_hours=2,
        )

        self.assertEqual(goal.user, user)
        self.assertEqual(goal.title, "Learn Python")
        self.assertEqual(goal.deadline, deadline)
        self.assertEqual(goal.tasks.count(), 3)
        self.assertEqual(goal.tasks.filter(priority=Task.Priority.HIGH).count(), 2)

    def test_failure_rolls_back_the_goal(self):
        user = User.objects.create_user("alice")

        with patch.object(Task.objects, "bulk_create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                create_goal_from_plan(
                    user=user,
                    plan=parse_plan(VALID_PLAN),
                    goal_text="text",
                    deadline=date.today(),
                    daily_available_hours=2,
                )

        self.assertFalse(Goal.objects.exists())
