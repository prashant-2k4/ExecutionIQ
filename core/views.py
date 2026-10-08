from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.services.ai_planner import AIPlannerError, generate_goal_plan
from core.services.execution_engine import calculate_execution_metrics
from core.services.goal_builder import create_goal_from_plan

from .forms import AIPlanForm, ExecutionLogForm, GoalForm, TaskForm
from .models import Goal, Task

# Temporary planner defaults until natural-language extraction and clarifying
# questions replace them (roadmap P3).
AI_PLAN_DEFAULT_DAYS = 30
AI_PLAN_DEFAULT_DAILY_HOURS = 2


def get_user_goal(request, goal_id):
    # Another user's goal is reported as missing so its existence is not leaked.
    return get_object_or_404(Goal, id=goal_id, user=request.user)


def get_user_task(request, task_id):
    return get_object_or_404(
        Task.objects.select_related("goal"),
        id=task_id,
        goal__user=request.user,
    )


@login_required
def goal_list(request):
    goals = (
        Goal.objects.filter(user=request.user)
        .prefetch_related("tasks__execution_logs")
        .order_by("deadline", "id")
    )

    for goal in goals:
        goal.execution_metrics = calculate_execution_metrics(goal)

    return render(request, "core/goal_list.html", {"goals": goals})


@login_required
def create_goal(request):
    if request.method == "POST":
        form = GoalForm(request.POST)

        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            goal.save()
            messages.success(request, "Goal created.")
            return redirect("goal_list")
    else:
        form = GoalForm()

    return render(request, "core/goal_form.html", {"form": form})


@login_required
def create_task(request, goal_id):
    goal = get_user_goal(request, goal_id)

    if request.method == "POST":
        form = TaskForm(request.POST)

        if form.is_valid():
            task = form.save(commit=False)
            task.goal = goal
            task.save()
            messages.success(request, "Task added.")
            return redirect("goal_list")
    else:
        form = TaskForm()

    return render(request, "core/task_form.html", {"form": form, "goal": goal})


@login_required
def edit_task(request, task_id):
    task = get_user_task(request, task_id)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)

        if form.is_valid():
            form.save()
            messages.success(request, "Task updated.")
            return redirect("goal_list")
    else:
        form = TaskForm(instance=task)

    return render(
        request,
        "core/task_form.html",
        {"form": form, "goal": task.goal, "task": task},
    )


@login_required
@require_POST
def toggle_task_completion(request, task_id):
    task = get_user_task(request, task_id)

    if task.is_completed:
        has_logs = task.execution_logs.exists()
        task.status = Task.Status.IN_PROGRESS if has_logs else Task.Status.TODO
    else:
        task.status = Task.Status.COMPLETED

    task.save()
    return redirect("goal_list")


@login_required
def create_execution_log(request, task_id):
    task = get_user_task(request, task_id)

    if request.method == "POST":
        form = ExecutionLogForm(request.POST)

        if form.is_valid():
            log = form.save(commit=False)
            log.task = task
            log.save()

            if task.status == Task.Status.TODO:
                task.status = Task.Status.IN_PROGRESS
                task.save()

            messages.success(request, "Work logged.")
            return redirect("goal_list")
    else:
        form = ExecutionLogForm()

    return render(
        request,
        "core/execution_log_form.html",
        {"form": form, "task": task},
    )


@login_required
def generate_ai_plan(request):
    error = None

    if request.method == "POST":
        form = AIPlanForm(request.POST)

        if form.is_valid():
            goal_text = form.cleaned_data["goal_text"]

            try:
                plan = generate_goal_plan(goal_text)
            except AIPlannerError as exc:
                error = str(exc)
            else:
                create_goal_from_plan(
                    user=request.user,
                    plan=plan,
                    goal_text=goal_text,
                    deadline=timezone.localdate() + timedelta(days=AI_PLAN_DEFAULT_DAYS),
                    daily_available_hours=AI_PLAN_DEFAULT_DAILY_HOURS,
                )
                messages.success(
                    request,
                    f"AI plan created with {len(plan.tasks)} tasks "
                    f"({plan.total_estimated_hours} estimated hours).",
                )
                return redirect("goal_list")
    else:
        form = AIPlanForm()

    return render(request, "core/ai_plan.html", {"form": form, "error": error})
