"""Execution Engine tests.

Expected values are worked out by hand from the formulas documented in
core/services/execution_engine.py, so the engine stays explainable.
"""

import json
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.models import ExecutionLog, Goal, Task
from core.services.execution_engine import (
    CPI_LOW_RISK,
    CPI_MEDIUM_RISK,
    EngineInput,
    Risk,
    TaskSnapshot,
    calculate_execution_metrics,
    classify_risk,
    completion_probability_index,
    evaluate,
)

TODAY = date(2026, 10, 9)


def make_input(
    *,
    deadline_in,
    total_hours=None,
    tasks=None,
    daily_hours=2,
    days_per_week=7,
    started_days_ago=0,
    logs=None,
    last_activity=None,
):
    if tasks is None:
        tasks = [TaskSnapshot(estimated_hours=total_hours, completed=False)]
    return EngineInput(
        today=TODAY,
        start_date=TODAY - timedelta(days=started_days_ago),
        deadline=TODAY + timedelta(days=deadline_in),
        daily_available_hours=daily_hours,
        days_per_week=days_per_week,
        tasks=tasks,
        log_hours_by_date=logs or {},
        last_activity_date=last_activity,
    )


def codes(metrics):
    return [f.code for f in metrics.factors]


class NewGoalTests(TestCase):
    """On day one there is no history, so the plan's daily hours drive the prediction."""

    def test_comfortable_plan_is_low_risk(self):
        # 40 h of work, 30 days x 2 h = 60 h capacity -> coverage 1.5
        m = evaluate(make_input(deadline_in=29, total_hours=40))

        self.assertEqual(m.days_remaining, 30)
        self.assertEqual(m.available_capacity, 60)
        self.assertAlmostEqual(m.required_daily_hours, 1.33)
        self.assertEqual(m.effective_daily_rate, 2)
        self.assertEqual(m.feasibility_score, 100)
        self.assertAlmostEqual(m.completion_probability_index, 95.3)  # 100 / (1 + e^-3)
        self.assertEqual(m.risk, Risk.LOW)
        # 40 h / 2 h per day = 20 days, today counts as day one
        self.assertEqual(m.estimated_completion_date, TODAY + timedelta(days=19))
        self.assertTrue(m.finishes_before_deadline)
        self.assertEqual(codes(m), ["ON_TRACK", "INSUFFICIENT_HISTORY"])

    def test_capacity_exactly_equal_to_work_is_medium_risk(self):
        # 60 h of work, 60 h capacity -> coverage 1.0 -> CPI 50
        m = evaluate(make_input(deadline_in=29, total_hours=60))

        self.assertEqual(m.feasibility_score, 100)
        self.assertEqual(m.completion_probability_index, 50)
        self.assertEqual(m.risk, Risk.MEDIUM)
        self.assertEqual(codes(m), ["ON_TRACK", "LOW_BUFFER", "INSUFFICIENT_HISTORY"])
        self.assertIn("0.0 h of spare capacity", m.factors[1].message)

    def test_overloaded_plan_is_high_risk(self):
        # 80 h of work, 60 h capacity -> coverage 0.75
        m = evaluate(make_input(deadline_in=29, total_hours=80))

        self.assertAlmostEqual(m.required_daily_hours, 2.67)
        self.assertEqual(m.feasibility_score, 75)
        self.assertAlmostEqual(m.completion_probability_index, 18.2)  # 100 / (1 + e^1.5)
        self.assertEqual(m.risk, Risk.HIGH)
        self.assertEqual(m.estimated_completion_date, TODAY + timedelta(days=39))
        self.assertFalse(m.finishes_before_deadline)
        self.assertIn("REQUIRED_EXCEEDS_AVAILABLE", codes(m))
        self.assertIn("PROJECTED_LATE", codes(m))

    def test_days_per_week_reduces_capacity(self):
        # 28 days at 5/7 = 20 working days x 2 h = 40 h for 30 h of work
        m = evaluate(make_input(deadline_in=27, total_hours=30, days_per_week=5))

        self.assertEqual(m.working_days_remaining, 20)
        self.assertEqual(m.available_capacity, 40)
        self.assertEqual(m.required_daily_hours, 1.5)
        # 15 working days -> exactly 21 calendar days (no float rounding extra day)
        self.assertEqual(m.estimated_completion_date, TODAY + timedelta(days=20))


class WorkloadTests(TestCase):
    def test_partial_credit_from_logged_hours_is_capped(self):
        m = evaluate(make_input(deadline_in=9, tasks=[
            TaskSnapshot(estimated_hours=10, completed=True),
            TaskSnapshot(estimated_hours=10, completed=False, logged_hours=4),
            TaskSnapshot(estimated_hours=10, completed=False, logged_hours=12),  # capped at 9
            TaskSnapshot(estimated_hours=10, completed=False),
        ]))

        self.assertEqual(m.total_workload, 40)
        self.assertEqual(m.completed_workload, 23)
        self.assertEqual(m.remaining_workload, 17)
        self.assertEqual(m.progress_percentage, 57.5)

    def test_completed_goal(self):
        last = TODAY - timedelta(days=2)
        m = evaluate(make_input(
            deadline_in=5,
            tasks=[TaskSnapshot(estimated_hours=5, completed=True)],
            last_activity=last,
        ))

        self.assertTrue(m.is_complete)
        self.assertEqual(m.progress_percentage, 100)
        self.assertEqual(m.required_daily_hours, 0)
        self.assertEqual(m.completion_probability_index, 100)
        self.assertEqual(m.risk, Risk.LOW)
        self.assertEqual(m.estimated_completion_date, last)
        self.assertEqual(codes(m), ["GOAL_COMPLETE"])

    def test_goal_without_tasks_is_not_assessed(self):
        m = evaluate(make_input(deadline_in=5, tasks=[]))

        self.assertIsNone(m.feasibility_score)
        self.assertIsNone(m.completion_probability_index)
        self.assertIsNone(m.risk)
        self.assertIsNone(m.estimated_completion_date)
        self.assertEqual(codes(m), ["NO_TASKS"])


class DeadlineEdgeCaseTests(TestCase):
    def test_deadline_today_counts_today(self):
        m = evaluate(make_input(deadline_in=0, total_hours=3))

        self.assertEqual(m.days_remaining, 1)
        self.assertEqual(m.required_daily_hours, 3)
        self.assertEqual(m.risk, Risk.HIGH)

    def test_deadline_passed_with_work_remaining(self):
        m = evaluate(make_input(deadline_in=-1, total_hours=10, started_days_ago=10))

        self.assertEqual(m.days_remaining, 0)
        self.assertEqual(m.available_capacity, 0)
        self.assertIsNone(m.required_daily_hours)
        self.assertEqual(m.feasibility_score, 0)
        self.assertEqual(m.completion_probability_index, 0)
        self.assertEqual(m.risk, Risk.HIGH)
        self.assertEqual(codes(m)[0], "DEADLINE_PASSED")
        self.assertNotIn("PROJECTED_LATE", codes(m))


class ExecutionPaceTests(TestCase):
    """Day 15 of a 29-day goal: the observed pace now fully drives the prediction."""

    def test_falling_behind_is_detected(self):
        # Only 6 of 60 h done after 15 days, nothing logged.
        m = evaluate(make_input(
            deadline_in=14,
            started_days_ago=14,
            tasks=[
                TaskSnapshot(estimated_hours=6, completed=True),
                TaskSnapshot(estimated_hours=54, completed=False),
            ],
        ))

        self.assertEqual(m.elapsed_days, 15)
        self.assertEqual(m.progress_percentage, 10)
        self.assertEqual(m.expected_progress_percentage, 51.7)  # 15 / 29 days
        self.assertEqual(m.schedule_variance, -41.7)
        self.assertEqual(m.execution_rate, 0.4)  # 6 h / 15 days
        self.assertEqual(m.effective_daily_rate, 0.4)
        self.assertEqual(m.required_daily_hours, 3.6)  # 54 h / 15 days
        self.assertEqual(m.feasibility_score, 11.1)  # 0.4 x 15 / 54
        self.assertLess(m.completion_probability_index, 1)
        self.assertEqual(m.risk, Risk.HIGH)
        self.assertEqual(m.estimated_completion_date, TODAY + timedelta(days=134))  # 54 / 0.4 = 135 days
        self.assertEqual(codes(m), [
            "REQUIRED_EXCEEDS_AVAILABLE",
            "PACE_BELOW_REQUIRED",
            "BEHIND_SCHEDULE",
            "NO_RECENT_ACTIVITY",
            "LOW_TIME_INVESTMENT",
            "PROJECTED_LATE",
        ])

    def test_ahead_of_schedule_is_on_track(self):
        logs = {TODAY - timedelta(days=i): 3.0 for i in range(15)}
        m = evaluate(make_input(
            deadline_in=14,
            started_days_ago=14,
            tasks=[
                TaskSnapshot(estimated_hours=40, completed=True),
                TaskSnapshot(estimated_hours=20, completed=False),
            ],
            logs=logs,
            last_activity=TODAY,
        ))

        self.assertAlmostEqual(m.progress_percentage, 66.7)
        self.assertAlmostEqual(m.execution_rate, 2.67)
        self.assertEqual(m.logged_hours, 45)
        self.assertEqual(m.average_daily_logged_hours, 3)
        self.assertEqual(m.current_streak, 15)
        self.assertEqual(m.feasibility_score, 100)
        self.assertGreater(m.completion_probability_index, 99)
        self.assertEqual(m.risk, Risk.LOW)
        self.assertEqual(codes(m), ["ON_TRACK"])

    def test_trust_in_observed_pace_ramps_up(self):
        # Day 4 (3 full days of history): trust = 3/7, observed rate 0, planned 2 h
        m = evaluate(make_input(deadline_in=26, total_hours=60, started_days_ago=3))
        self.assertAlmostEqual(m.effective_daily_rate, round(4 / 7 * 2, 2))


class StreakTests(TestCase):
    def streak(self, *days_ago):
        logs = {TODAY - timedelta(days=d): 1.0 for d in days_ago}
        return evaluate(make_input(deadline_in=5, total_hours=5, logs=logs)).current_streak

    def test_streak(self):
        self.assertEqual(self.streak(), 0)
        self.assertEqual(self.streak(0, 1, 3), 2)
        self.assertEqual(self.streak(1, 2), 2)  # today not logged yet still counts
        self.assertEqual(self.streak(2, 3), 0)


class ScoringFunctionTests(TestCase):
    def test_cpi_is_monotonic_and_centred_on_full_coverage(self):
        values = [completion_probability_index(c / 10) for c in range(0, 30)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(completion_probability_index(1.0), 50)

    def test_risk_thresholds(self):
        self.assertEqual(classify_risk(CPI_LOW_RISK), Risk.LOW)
        self.assertEqual(classify_risk(CPI_LOW_RISK - 0.1), Risk.MEDIUM)
        self.assertEqual(classify_risk(CPI_MEDIUM_RISK), Risk.MEDIUM)
        self.assertEqual(classify_risk(CPI_MEDIUM_RISK - 0.1), Risk.HIGH)

    def test_metrics_are_json_serialisable(self):
        m = evaluate(make_input(deadline_in=29, total_hours=40))
        data = json.loads(json.dumps(m.as_dict()))
        self.assertEqual(data["risk"], "LOW")
        self.assertEqual(data["factors"][0]["code"], "ON_TRACK")


class DynamicRecalculationTests(TestCase):
    """Metrics are recomputed from the database whenever work is logged or completed."""

    def setUp(self):
        self.user = User.objects.create_user("alice")
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.goal = Goal.objects.create(
            user=self.user,
            title="Learn Django",
            deadline=self.today + timedelta(days=9),
            daily_available_hours=1,
        )
        self.task_a = Task.objects.create(goal=self.goal, title="A", estimated_hours=6)
        self.task_b = Task.objects.create(goal=self.goal, title="B", estimated_hours=6)

    def metrics(self):
        goal = Goal.objects.prefetch_related("tasks__execution_logs").get(id=self.goal.id)
        return calculate_execution_metrics(goal, today=self.today)

    def test_logging_and_completing_work_updates_metrics(self):
        before = self.metrics()
        self.assertEqual(before.remaining_workload, 12)
        self.assertEqual(before.risk, Risk.HIGH)  # 12 h needed, 10 h available

        self.client.post(reverse("log_work", args=[self.task_a.id]), {
            "date": self.today.isoformat(),
            "duration_minutes": 180,
        })
        after_log = self.metrics()
        self.assertEqual(after_log.logged_hours, 3)
        self.assertEqual(after_log.completed_workload, 3)
        self.assertEqual(after_log.remaining_workload, 9)
        self.assertEqual(after_log.current_streak, 1)
        self.assertGreater(after_log.completion_probability_index, before.completion_probability_index)

        self.client.post(reverse("toggle_task", args=[self.task_a.id]))
        after_complete = self.metrics()
        self.assertEqual(after_complete.completed_workload, 6)
        self.assertEqual(after_complete.remaining_workload, 6)
        self.assertEqual(after_complete.risk, Risk.LOW)  # 6 h needed, 10 h available

    def test_start_date_comes_from_goal_creation(self):
        Goal.objects.filter(id=self.goal.id).update(
            created_at=datetime(2026, 1, 1, 12, tzinfo=dt_timezone.utc)
        )
        goal = Goal.objects.get(id=self.goal.id)
        m = calculate_execution_metrics(goal, today=date(2026, 1, 10))
        self.assertEqual(m.elapsed_days, 10)

    def test_goal_list_query_count_does_not_grow_per_goal(self):
        ExecutionLog.objects.create(task=self.task_a, date=self.today, duration_minutes=30)

        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("goal_list"))
        baseline = len(ctx.captured_queries)

        for i in range(3):
            goal = Goal.objects.create(
                user=self.user, title=f"G{i}",
                deadline=self.today + timedelta(days=5), daily_available_hours=1,
            )
            task = Task.objects.create(goal=goal, title="T", estimated_hours=2)
            ExecutionLog.objects.create(task=task, date=self.today, duration_minutes=30)

        with self.assertNumQueries(baseline):
            self.client.get(reverse("goal_list"))
