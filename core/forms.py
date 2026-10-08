from django import forms
from django.utils import timezone

from .models import ExecutionLog, Goal, Task

MAX_MINUTES_PER_LOG = 24 * 60


class DateInput(forms.DateInput):
    input_type = "date"


class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = [
            "title",
            "description",
            "deadline",
            "daily_available_hours",
            "available_days_per_week",
            "priority",
            "status",
        ]
        widgets = {"deadline": DateInput()}

    def clean_deadline(self):
        deadline = self.cleaned_data["deadline"]
        # Only new goals must have a future deadline; existing goals may be overdue.
        if self.instance.pk is None and deadline < timezone.localdate():
            raise forms.ValidationError("The deadline cannot be in the past.")
        return deadline

    def clean_daily_available_hours(self):
        hours = self.cleaned_data["daily_available_hours"]
        if hours <= 0 or hours > 24:
            raise forms.ValidationError("Daily available hours must be between 0 and 24.")
        return hours


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "estimated_hours",
            "status",
            "priority",
            "due_date",
        ]
        widgets = {"due_date": DateInput()}

    def clean_estimated_hours(self):
        hours = self.cleaned_data["estimated_hours"]
        if hours <= 0:
            raise forms.ValidationError("Estimated hours must be greater than 0.")
        return hours


class ExecutionLogForm(forms.ModelForm):
    class Meta:
        model = ExecutionLog
        fields = [
            "date",
            "duration_minutes",
            "notes",
        ]
        widgets = {"date": DateInput()}
        labels = {"duration_minutes": "Duration (minutes)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["date"].initial = timezone.localdate

    def clean_date(self):
        log_date = self.cleaned_data["date"]
        if log_date > timezone.localdate():
            raise forms.ValidationError("You cannot log work for a future date.")
        return log_date

    def clean_duration_minutes(self):
        minutes = self.cleaned_data["duration_minutes"]
        if minutes < 1 or minutes > MAX_MINUTES_PER_LOG:
            raise forms.ValidationError("Duration must be between 1 and 1440 minutes.")
        return minutes


class AIPlanForm(forms.Form):
    goal_text = forms.CharField(
        max_length=1000,
        widget=forms.TextInput(
            attrs={"placeholder": "Example: I want to learn Python in 30 days"}
        ),
    )

    def clean_goal_text(self):
        text = self.cleaned_data["goal_text"].strip()
        if len(text) < 5:
            raise forms.ValidationError("Please describe your goal in a few more words.")
        return text
