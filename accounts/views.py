from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from organizations.services import (
    get_user_managed_organizations,
    get_user_organization_memberships,
)

from .forms import AdmissionLoginForm, AdmissionRegisterForm, LoginForm, RegisterForm


class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class AdmissionViceRectorLoginView(LoginView):
    template_name = "accounts/admission_login.html"
    authentication_form = AdmissionLoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return get_admission_success_url(self.request.user)


def get_admission_success_url(user):
    return reverse("admissions:dashboard")


def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, _("Account created successfully."))
            return redirect("documents:document_list")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {
        "form": form,
    })


def admission_register_view(request):
    if request.method == "POST":
        form = AdmissionRegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, _("Account created successfully."))
            return redirect(get_admission_success_url(user))
    else:
        form = AdmissionRegisterForm()

    return render(request, "accounts/admission_register.html", {
        "form": form,
    })


@login_required
def profile_view(request):
    return render(request, "accounts/profile.html", {
        "managed_organizations": get_user_managed_organizations(request.user),
        "organization_memberships": get_user_organization_memberships(request.user),
    })
