from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from organizations.services import (
    get_user_managed_organizations,
    get_user_organization_memberships,
)

from .forms import LoginForm, RegisterForm


class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Account created successfully.")
            return redirect("documents:document_list")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {
        "form": form,
    })


@login_required
def profile_view(request):
    return render(request, "accounts/profile.html", {
        "managed_organizations": get_user_managed_organizations(request.user),
        "organization_memberships": get_user_organization_memberships(request.user),
    })
