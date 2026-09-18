from django.shortcuts import render, redirect, get_object_or_404
# Create your views here.
from .models import Goal, Task, ExecutionLog
from django import forms

def home(request):
    return render(request, 'core/home.html')


def goal_list(request):
    goals = Goal.objects.all()

    return render(
        request,
        'core/goal_list.html',
        {'goals': goals}
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