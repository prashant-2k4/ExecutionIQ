from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import RegistrationForm


def register(request):
    if request.user.is_authenticated:
        return redirect("goal_list")

    if request.method == "POST":
        form = RegistrationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome to ExecutionIQ, {user.username}.")
            return redirect("goal_list")
    else:
        form = RegistrationForm()

    return render(request, "registration/register.html", {"form": form})
