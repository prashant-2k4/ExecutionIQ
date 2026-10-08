from django.db import transaction

from core.models import Goal, Task


@transaction.atomic
def create_goal_from_plan(user, plan, goal_text, deadline, daily_available_hours):
    """Persist a validated GoalPlan as a Goal with its Tasks.

    Runs in a single transaction so a failure never leaves a goal with only
    part of its tasks.
    """
    goal = Goal.objects.create(
        user=user,
        title=plan.goal,
        description=goal_text,
        deadline=deadline,
        daily_available_hours=daily_available_hours,
    )

    Task.objects.bulk_create(
        Task(
            goal=goal,
            title=task.title,
            estimated_hours=task.estimated_hours,
            priority=task.priority,
        )
        for task in plan.tasks
    )

    return goal
