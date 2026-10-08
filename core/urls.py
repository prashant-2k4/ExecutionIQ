from django.urls import path

from . import views

urlpatterns = [
    path("", views.goal_list, name="goal_list"),
    path("goals/create/", views.create_goal, name="create_goal"),
    path("goals/<int:goal_id>/tasks/create/", views.create_task, name="create_task"),
    path("tasks/<int:task_id>/edit/", views.edit_task, name="edit_task"),
    path("tasks/<int:task_id>/toggle/", views.toggle_task_completion, name="toggle_task"),
    path("tasks/<int:task_id>/log/", views.create_execution_log, name="log_work"),
    path("ai-plan/", views.generate_ai_plan, name="ai_plan"),
]
