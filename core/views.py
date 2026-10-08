from django.shortcuts import render, redirect, get_object_or_404
# Create your views here.
from .models import Goal, Task, ExecutionLog
from django import forms
from core.services.execution_engine import calculate_execution_metrics
from core.services.ai_planner import generate_goal_plan
from datetime import date, timedelta

def home(request):
    return render(request, 'core/home.html')


def goal_list(request):
    goals = Goal.objects.all()

    for goal in goals:
        goal.execution_metrics = calculate_execution_metrics(goal)

    return render(
        request,
        "core/goal_list.html",
        {"goals": goals},
    )

class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = [
            'title',
            'description',
            'deadline',
            'daily_available_hours',
            'priority',
            'status',
        ]

class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            'title',
            'description',
            'estimated_hours',
            'actual_hours',
            'status',
            'priority',
            'due_date',
        ]

class ExecutionLogForm(forms.ModelForm):
    class Meta:
        model = ExecutionLog
        fields = [
            'date',
            'duration_minutes',
            'notes',
        ]

def create_goal(request):
    if request.method == 'POST':
        form = GoalForm(request.POST)

        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            goal.save()

            return redirect('/')
    else:
        form = GoalForm()

    return render(request, 'core/goal_form.html', {'form': form})

def create_task(request, goal_id):
    goal = Goal.objects.get(id=goal_id)

    if request.method == 'POST':
        form = TaskForm(request.POST)

        if form.is_valid():
            task = form.save(commit=False)
            task.goal = goal
            task.save()

            return redirect('/')
    else:
        form = TaskForm()

    return render(request, 'core/task_form.html', {'form': form, 'goal': goal})

def create_execution_log(request, task_id):
    task = get_object_or_404(Task, id=task_id)

    if request.method == 'POST':
        form = ExecutionLogForm(request.POST)

        if form.is_valid():
            log = form.save(commit=False)
            log.task = task
            log.save()

            return redirect('/')

    else:
        form = ExecutionLogForm()

    return render(
        request,
        'core/execution_log_form.html',
        {'form': form, 'task': task}
    )

def generate_ai_plan(request):
    if request.method == "POST":
        goal_text = request.POST.get("goal_text", "").strip()

        if goal_text:
            try:
                plan = generate_goal_plan(goal_text)

                goal = Goal.objects.create(
                    title=plan["goal"],
                    description=goal_text,
                    deadline=date.today() + timedelta(days=30),
                    daily_available_hours=2,
                )

                for task_data in plan["tasks"]:
                    priority = task_data["priority"].upper()

                    Task.objects.create(
                        goal=goal,
                        title=task_data["title"],
                        estimated_hours=task_data["estimated_hours"],
                        priority=priority,
                    )

                return redirect("/")

            except Exception:
                error = (
                    "The AI planner is temporarily unavailable. "
                    "Please try again."
                )

                return render(
                    request,
                    "core/ai_plan.html",
                    {
                        "goal_text": goal_text,
                        "error": error,
                    },
                )

    return render(request, "core/ai_plan.html")

    return render(
        request,
        "core/ai_plan.html",
        {
            "goal_text": goal_text,
            "plan": plan,
            "error": error,
        },
    )