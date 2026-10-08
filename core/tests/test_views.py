from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import ExecutionLog, Goal, Task
from core.services.ai_planner import AIPlannerError, parse_plan


class GoalTaskViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pass-12345")
        self.client.force_login(self.user)
        self.goal = Goal.objects.create(
            user=self.user,
            title="Learn Django",
            deadline=date.today() + timedelta(days=10),
            daily_available_hours=2,
        )
        self.task = Task.objects.create(goal=self.goal, title="Models", estimated_hours=4)

    def test_goal_list_renders_metrics(self):
        response = self.client.get(reverse("goal_list"))
        self.assertContains(response, "Learn Django")
        self.assertContains(response, "Feasibility")

    def test_create_goal(self):
        response = self.client.post(reverse("create_goal"), {
            "title": "Learn React",
            "deadline": (date.today() + timedelta(days=20)).isoformat(),
            "daily_available_hours": "1.5",
            "available_days_per_week": 5,
            "priority": "HIGH",
            "status": "ACTIVE",
        })
        self.assertRedirects(response, reverse("goal_list"))
        self.assertEqual(Goal.objects.get(title="Learn React").user, self.user)

    def test_create_goal_rejects_past_deadline_and_bad_hours(self):
        response = self.client.post(reverse("create_goal"), {
            "title": "Too late",
            "deadline": (date.today() - timedelta(days=1)).isoformat(),
            "daily_available_hours": "30",
            "priority": "HIGH",
            "status": "ACTIVE",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be in the past")
        self.assertContains(response, "between 0 and 24")
        self.assertFalse(Goal.objects.filter(title="Too late").exists())

    def test_create_goal_rejects_invalid_days_per_week(self):
        for days in (0, 8):
            with self.subTest(days=days):
                response = self.client.post(reverse("create_goal"), {
                    "title": "Bad week",
                    "deadline": (date.today() + timedelta(days=20)).isoformat(),
                    "daily_available_hours": "2",
                    "available_days_per_week": days,
                    "priority": "HIGH",
                    "status": "ACTIVE",
                })
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Goal.objects.filter(title="Bad week").exists())

    def test_create_task_for_missing_goal_returns_404(self):
        response = self.client.get(reverse("create_task", args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_edit_task(self):
        response = self.client.post(reverse("edit_task", args=[self.task.id]), {
            "title": "Models and migrations",
            "estimated_hours": "5",
            "status": "TODO",
            "priority": "LOW",
        })
        self.assertRedirects(response, reverse("goal_list"))
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Models and migrations")

    def test_toggle_completion_sets_and_clears_completed_at(self):
        url = reverse("toggle_task", args=[self.task.id])

        self.client.post(url)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.COMPLETED)
        self.assertIsNotNone(self.task.completed_at)

        self.client.post(url)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)
        self.assertIsNone(self.task.completed_at)

    def test_toggle_requires_post(self):
        response = self.client.get(reverse("toggle_task", args=[self.task.id]))
        self.assertEqual(response.status_code, 405)

    def test_logging_work_marks_task_in_progress(self):
        response = self.client.post(reverse("log_work", args=[self.task.id]), {
            "date": date.today().isoformat(),
            "duration_minutes": 90,
        })
        self.assertRedirects(response, reverse("goal_list"))
        self.assertEqual(ExecutionLog.objects.get().duration_minutes, 90)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.IN_PROGRESS)

    def test_logging_work_rejects_future_date_and_zero_minutes(self):
        response = self.client.post(reverse("log_work", args=[self.task.id]), {
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "duration_minutes": 0,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "future date")
        self.assertContains(response, "between 1 and 1440")
        self.assertFalse(ExecutionLog.objects.exists())


class AIPlanViewTests(TestCase):
    PLAN = '{"goal": "Learn Python", "tasks": [{"title": "Basics", "estimated_hours": 10, "priority": "HIGH"}]}'

    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.client.force_login(self.user)

    def test_successful_plan_creates_goal_and_tasks(self):
        with patch("core.views.generate_goal_plan", return_value=parse_plan(self.PLAN)):
            response = self.client.post(reverse("ai_plan"), {"goal_text": "I want to learn Python"})

        self.assertRedirects(response, reverse("goal_list"))
        goal = Goal.objects.get()
        self.assertEqual(goal.user, self.user)
        self.assertEqual(goal.title, "Learn Python")
        self.assertEqual(goal.tasks.count(), 1)

    def test_planner_error_is_shown_without_saving(self):
        with patch("core.views.generate_goal_plan", side_effect=AIPlannerError("AI is down")):
            response = self.client.post(reverse("ai_plan"), {"goal_text": "I want to learn Python"})

        self.assertContains(response, "AI is down")
        self.assertFalse(Goal.objects.exists())

    def test_blank_goal_text_is_rejected(self):
        with patch("core.views.generate_goal_plan") as planner:
            response = self.client.post(reverse("ai_plan"), {"goal_text": "   "})

        planner.assert_not_called()
        self.assertEqual(response.status_code, 200)
