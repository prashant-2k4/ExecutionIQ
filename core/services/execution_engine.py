"""ExecutionIQ Execution Engine.

A deterministic, explainable algorithm (not an AI model) that answers:
"Given the remaining work, the time left and the pace so far, will this goal
be finished by its deadline?"

The engine is a pure function, ``evaluate``, over plain data
(``EngineInput``), so every number can be reproduced by hand and unit-tested.
``calculate_execution_metrics`` adapts a Goal from the database to that input.

Model summary (all hours are planned/estimated task hours unless noted):

1. Workload
   completed work = estimates of completed tasks
                    + logged hours on unfinished tasks, capped at
                      PARTIAL_CREDIT_CAP of each task's estimate
   remaining work = total estimate - completed work

2. Time
   days remaining         = calendar days from today to deadline, inclusive
   working days remaining = days remaining x (days per week / 7)
   available capacity     = working days remaining x daily available hours
   required daily hours   = remaining work / working days remaining

3. Pace
   execution rate     = completed work / elapsed working days
                        (planned hours delivered per working day)
   effective rate     = blend of the planned daily hours and the observed
                        execution rate; trust in the observed rate is 0 on
                        the first day and grows linearly to 1 over the next
                        PACE_RAMP_DAYS days
   expected progress  = elapsed days / total planned days (linear plan)
   schedule variance  = actual progress - expected progress (points)

4. Prediction
   projected coverage = effective rate x working days remaining / remaining work
   feasibility score  = min(100, 100 x projected coverage)
   Completion Probability Index (CPI)
                      = 100 / (1 + e^(-CPI_STEEPNESS x (coverage - 1)))
     A deterministic score, not a statistically calibrated probability:
     50 when projected capacity exactly equals the remaining work, rising
     as the buffer grows and falling as the shortfall grows.
   risk               = LOW if CPI >= 70, MEDIUM if CPI >= 40, else HIGH
   estimated completion date = today + remaining work / effective rate,
                               converted from working to calendar days
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

PARTIAL_CREDIT_CAP = 0.9
PACE_RAMP_DAYS = 7
MIN_HISTORY_DAYS = 3
CPI_STEEPNESS = 6.0
CPI_LOW_RISK = 70
CPI_MEDIUM_RISK = 40
BEHIND_SCHEDULE_POINTS = 10
INACTIVITY_DAYS = 3
LOW_INVESTMENT_RATIO = 0.5


class Risk:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class TaskSnapshot:
    estimated_hours: float
    completed: bool
    logged_hours: float = 0.0


@dataclass(frozen=True)
class EngineInput:
    today: date
    start_date: date
    deadline: date
    daily_available_hours: float
    days_per_week: int
    tasks: list[TaskSnapshot]
    log_hours_by_date: dict[date, float] = field(default_factory=dict)
    last_activity_date: date | None = None


@dataclass(frozen=True)
class Factor:
    """A deterministic reason behind the assessment.

    ``code`` is stable and machine-readable (for the AI Recommendation Engine);
    ``message`` is a plain-language fallback explanation.
    """

    code: str
    severity: str  # "positive", "info", "warning" or "critical"
    message: str


@dataclass(frozen=True)
class ExecutionMetrics:
    # Workload
    total_workload: float
    completed_workload: float
    remaining_workload: float
    progress_percentage: float
    logged_hours: float
    # Time
    days_remaining: int
    working_days_remaining: float
    available_capacity: float
    required_daily_hours: float | None
    # Pace
    elapsed_days: int
    execution_rate: float
    effective_daily_rate: float
    average_daily_logged_hours: float
    expected_progress_percentage: float
    schedule_variance: float
    current_streak: int
    has_sufficient_history: bool
    # Prediction
    feasibility_score: float | None
    completion_probability_index: float | None
    risk: str | None
    estimated_completion_date: date | None
    finishes_before_deadline: bool | None
    is_complete: bool
    factors: list[Factor]

    def as_dict(self):
        """JSON-friendly representation (used later by the AI layer and API)."""
        data = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "factors"
        }
        if self.estimated_completion_date:
            data["estimated_completion_date"] = self.estimated_completion_date.isoformat()
        data["factors"] = [vars(f) for f in self.factors]
        return data


def _round(value, places=2):
    return None if value is None else round(value, places)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _current_streak(today, log_dates):
    """Consecutive days with logged work, ending today (or yesterday)."""
    day = today if today in log_dates else today - timedelta(days=1)
    streak = 0
    while day in log_dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def completion_probability_index(coverage):
    """Map projected coverage (capacity / remaining work) to a 0-100 score."""
    return 100 / (1 + math.exp(-CPI_STEEPNESS * (coverage - 1)))


def classify_risk(cpi):
    if cpi >= CPI_LOW_RISK:
        return Risk.LOW
    if cpi >= CPI_MEDIUM_RISK:
        return Risk.MEDIUM
    return Risk.HIGH


def evaluate(data: EngineInput) -> ExecutionMetrics:
    week_share = _clamp(data.days_per_week, 1, 7) / 7
    daily_hours = max(data.daily_available_hours, 0.0)

    # 1. Workload
    total = sum(t.estimated_hours for t in data.tasks)
    completed = sum(
        t.estimated_hours
        if t.completed
        else min(t.logged_hours, t.estimated_hours * PARTIAL_CREDIT_CAP)
        for t in data.tasks
    )
    remaining = max(total - completed, 0.0)
    progress = (completed / total * 100) if total > 0 else 0.0
    logged_total = sum(data.log_hours_by_date.values())
    is_complete = total > 0 and remaining == 0

    # 2. Time
    deadline_passed = data.deadline < data.today
    days_remaining = 0 if deadline_passed else (data.deadline - data.today).days + 1
    working_days_remaining = days_remaining * week_share
    capacity = working_days_remaining * daily_hours
    if remaining == 0:
        required_daily = 0.0
    elif working_days_remaining > 0:
        required_daily = remaining / working_days_remaining
    else:
        required_daily = None  # No working time left: cannot be met.

    # 3. Pace
    start = min(data.start_date, data.today)
    elapsed_days = (data.today - start).days + 1
    total_days = max((data.deadline - start).days + 1, 1)
    elapsed_working_days = elapsed_days * week_share

    execution_rate = completed / elapsed_working_days
    avg_logged = logged_total / elapsed_working_days
    has_history = elapsed_days >= MIN_HISTORY_DAYS
    trust = _clamp((elapsed_days - 1) / PACE_RAMP_DAYS, 0.0, 1.0)
    effective_rate = trust * execution_rate + (1 - trust) * daily_hours

    expected_progress = _clamp(elapsed_days / total_days * 100, 0.0, 100.0)
    variance = progress - expected_progress if total > 0 else 0.0

    # 4. Prediction
    if total == 0:
        coverage = feasibility = cpi = risk = None
    elif is_complete:
        coverage, feasibility, cpi, risk = None, 100.0, 100.0, Risk.LOW
    elif working_days_remaining == 0:
        coverage, feasibility, cpi, risk = 0.0, 0.0, 0.0, Risk.HIGH
    else:
        coverage = effective_rate * working_days_remaining / remaining
        feasibility = min(100.0, coverage * 100)
        cpi = completion_probability_index(coverage)
        risk = classify_risk(cpi)

    if total == 0:
        estimated_completion = None
    elif is_complete:
        estimated_completion = data.last_activity_date or data.today
    elif effective_rate > 0:
        working_days_needed = remaining / effective_rate
        # Round first so float noise (e.g. 21.000000000000004) does not add a day.
        calendar_days_needed = math.ceil(round(working_days_needed / week_share, 6))
        estimated_completion = data.today + timedelta(days=max(calendar_days_needed - 1, 0))
    else:
        estimated_completion = None
    finishes_on_time = (
        None if estimated_completion is None else estimated_completion <= data.deadline
    )

    factors = _explain(
        data=data,
        total=total,
        remaining=remaining,
        is_complete=is_complete,
        deadline_passed=deadline_passed,
        daily_hours=daily_hours,
        required_daily=required_daily,
        effective_rate=effective_rate,
        avg_logged=avg_logged,
        has_history=has_history,
        variance=variance,
        estimated_completion=estimated_completion,
        risk=risk,
        spare_hours=(
            effective_rate * working_days_remaining - remaining if coverage is not None else None
        ),
    )

    return ExecutionMetrics(
        total_workload=_round(total),
        completed_workload=_round(completed),
        remaining_workload=_round(remaining),
        progress_percentage=_round(progress, 1),
        logged_hours=_round(logged_total),
        days_remaining=days_remaining,
        working_days_remaining=_round(working_days_remaining, 1),
        available_capacity=_round(capacity),
        required_daily_hours=_round(required_daily),
        elapsed_days=elapsed_days,
        execution_rate=_round(execution_rate),
        effective_daily_rate=_round(effective_rate),
        average_daily_logged_hours=_round(avg_logged),
        expected_progress_percentage=_round(expected_progress, 1),
        schedule_variance=_round(variance, 1),
        current_streak=_current_streak(data.today, set(data.log_hours_by_date)),
        has_sufficient_history=has_history,
        feasibility_score=_round(feasibility, 1),
        completion_probability_index=_round(cpi, 1),
        risk=risk,
        estimated_completion_date=estimated_completion,
        finishes_before_deadline=finishes_on_time,
        is_complete=is_complete,
        factors=factors,
    )


def _explain(
    *,
    data,
    total,
    remaining,
    is_complete,
    deadline_passed,
    daily_hours,
    required_daily,
    effective_rate,
    avg_logged,
    has_history,
    variance,
    estimated_completion,
    risk,
    spare_hours,
):
    """Deterministic reasons behind the numbers, most important first."""
    if total == 0:
        return [Factor("NO_TASKS", "info", "Add tasks so the workload can be evaluated.")]
    if is_complete:
        return [Factor("GOAL_COMPLETE", "positive", "All planned work is complete.")]

    factors = []

    if deadline_passed:
        factors.append(Factor(
            "DEADLINE_PASSED", "critical",
            f"The deadline has passed with {remaining:.1f} hours of work remaining.",
        ))
    elif required_daily is not None and required_daily > daily_hours:
        factors.append(Factor(
            "REQUIRED_EXCEEDS_AVAILABLE", "critical",
            f"You need {required_daily:.1f} h per working day but planned only "
            f"{daily_hours:.1f} h.",
        ))

    if has_history and not deadline_passed and required_daily is not None \
            and effective_rate < required_daily:
        factors.append(Factor(
            "PACE_BELOW_REQUIRED", "warning",
            f"Your effective pace is {effective_rate:.1f} h of planned work per "
            f"working day, below the {required_daily:.1f} h required.",
        ))

    if has_history and variance <= -BEHIND_SCHEDULE_POINTS:
        factors.append(Factor(
            "BEHIND_SCHEDULE", "warning",
            f"Progress is {abs(variance):.0f} points behind the expected pace.",
        ))

    inactive_since = data.last_activity_date or data.start_date
    if has_history and (data.today - inactive_since).days >= INACTIVITY_DAYS:
        factors.append(Factor(
            "NO_RECENT_ACTIVITY", "warning",
            f"No work logged or completed in the last "
            f"{(data.today - inactive_since).days} days.",
        ))

    if has_history and daily_hours > 0 and avg_logged < daily_hours * LOW_INVESTMENT_RATIO:
        factors.append(Factor(
            "LOW_TIME_INVESTMENT", "warning",
            f"You are logging {avg_logged:.1f} h per working day against "
            f"{daily_hours:.1f} h planned.",
        ))

    if estimated_completion and estimated_completion > data.deadline and not deadline_passed:
        factors.append(Factor(
            "PROJECTED_LATE", "warning",
            f"At the current pace the goal finishes on {estimated_completion:%d %b %Y}, "
            f"after the {data.deadline:%d %b %Y} deadline.",
        ))

    if not has_history:
        factors.append(Factor(
            "INSUFFICIENT_HISTORY", "info",
            "Too little execution history yet; predictions mainly use your planned hours.",
        ))

    if not any(f.severity in ("critical", "warning") for f in factors):
        if risk == Risk.MEDIUM and spare_hours is not None:
            factors.insert(0, Factor(
                "LOW_BUFFER", "info",
                f"On pace, but with only {max(spare_hours, 0):.1f} h of spare capacity "
                f"before the deadline; a few missed days would put the goal at risk.",
            ))
        factors.insert(0, Factor(
            "ON_TRACK", "positive",
            "Your available time and current pace are enough to meet the deadline.",
        ))

    return factors


def build_engine_input(goal, today=None):
    """Collect a Goal's tasks and execution logs into an EngineInput.

    Uses ``goal.tasks.all()`` and ``task.execution_logs.all()`` so callers can
    prefetch them (``prefetch_related("tasks__execution_logs")``) and avoid
    per-goal queries.
    """
    today = today or timezone.localdate()
    tasks = []
    log_hours_by_date = {}
    activity_dates = []

    for task in goal.tasks.all():
        task_minutes = 0
        for log in task.execution_logs.all():
            task_minutes += log.duration_minutes
            log_hours_by_date[log.date] = (
                log_hours_by_date.get(log.date, 0.0) + log.duration_minutes / 60
            )
            activity_dates.append(log.date)

        if task.completed_at:
            activity_dates.append(timezone.localdate(task.completed_at))

        tasks.append(TaskSnapshot(
            estimated_hours=float(task.estimated_hours),
            completed=task.is_completed,
            logged_hours=task_minutes / 60,
        ))

    return EngineInput(
        today=today,
        start_date=timezone.localdate(goal.created_at) if goal.created_at else today,
        deadline=goal.deadline,
        daily_available_hours=float(goal.daily_available_hours),
        days_per_week=goal.available_days_per_week,
        tasks=tasks,
        log_hours_by_date=log_hours_by_date,
        last_activity_date=max(activity_dates) if activity_dates else None,
    )


def calculate_execution_metrics(goal, today=None):
    return evaluate(build_engine_input(goal, today=today))
