from django.contrib.auth.models import User
from django.db import models

# Create your models here.

class Goal(models.Model):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        ARCHIVED = "ARCHIVED", "Archived"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="goals"
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    deadline = models.DateField()

    daily_available_hours = models.DecimalField(
        max_digits=4,
        decimal_places=2
    )

    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Task(models.Model):
    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    class Status(models.TextChoices):
        TODO = "TODO", "To Do"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"

    goal = models.ForeignKey(
        Goal,
        on_delete=models.CASCADE,
        related_name="tasks"
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    estimated_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2
    )

    actual_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.TODO
    )

    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM
    )

    due_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

class ExecutionLog(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="execution_logs"
    )

    date = models.DateField()
    duration_minutes = models.PositiveIntegerField()
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)