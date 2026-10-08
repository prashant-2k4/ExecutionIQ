from django.urls import path
from .views import goal_list, create_goal, create_task, create_execution_log
from .views import generate_ai_plan
urlpatterns = [
    path('', goal_list),
    path('goals/create/', create_goal),
    path('goals/<int:goal_id>/tasks/create/', create_task),
    path('tasks/<int:task_id>/log/', create_execution_log),
    path("ai-plan/", generate_ai_plan),
]