from django.contrib import admin

# Register your models here.
from .models import Goal, Task, ExecutionLog

admin.site.register(Goal)
admin.site.register(Task)
admin.site.register(ExecutionLog)