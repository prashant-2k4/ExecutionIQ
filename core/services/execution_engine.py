from datetime import date
from decimal import Decimal

from core.models import Task


def calculate_execution_metrics(goal):
    tasks = goal.tasks.all()

    remaining_workload = sum(
        (
            task.estimated_hours
            for task in tasks
            if task.status != Task.Status.COMPLETED
        ),
        Decimal("0"),
    )

    completed_workload = sum(
        (
            task.estimated_hours
            for task in tasks
            if task.status == Task.Status.COMPLETED
        ),
        Decimal("0"),
    )

    total_workload = completed_workload + remaining_workload

    days_remaining = max((goal.deadline - date.today()).days, 0)

    available_capacity = (
        Decimal(str(goal.daily_available_hours)) * days_remaining
    )

    if remaining_workload == 0:
        feasibility_score = Decimal("100")
    elif available_capacity == 0:
        feasibility_score = Decimal("0")
    else:
        feasibility_score = min(
            Decimal("100"),
            (available_capacity / remaining_workload) * Decimal("100"),
        )

    required_daily_hours = (
        remaining_workload / days_remaining
        if days_remaining > 0
        else remaining_workload
    )

    if feasibility_score >= 80:
        risk = "LOW"
    elif feasibility_score >= 60:
        risk = "MEDIUM"
    elif feasibility_score >= 40:
        risk = "HIGH"
    else:
        risk = "CRITICAL"

    progress_percentage = (
        (completed_workload / total_workload) * Decimal("100")
        if total_workload > 0
        else Decimal("0")
    )

    return {
        "total_workload": total_workload,
        "completed_workload": completed_workload,
        "remaining_workload": remaining_workload,
        "days_remaining": days_remaining,
        "available_capacity": available_capacity,
        "required_daily_hours": required_daily_hours,
        "feasibility_score": feasibility_score,
        "risk": risk,
        "progress_percentage": progress_percentage,
    }