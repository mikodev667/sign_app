from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from .forms import DepartmentForm, OrganizationMemberForm
from .models import OrganizationMember
from .services import ensure_default_department, get_user_managed_organizations


@login_required
def organization_list(request):
    organizations = (
        get_user_managed_organizations(request.user)
        .prefetch_related("members", "departments")
        .order_by("name")
    )

    return render(request, "organizations/organization_list.html", {
        "organizations": organizations,
    })


@login_required
def organization_members(request, organization_pk):
    organization = get_object_or_404(
        get_user_managed_organizations(request.user),
        pk=organization_pk,
    )
    ensure_default_department(organization)

    member_form = OrganizationMemberForm(organization=organization)
    department_form = DepartmentForm()

    action = request.POST.get("action", "add_member") if request.method == "POST" else ""

    if request.method == "POST" and action == "add_member":
        form = OrganizationMemberForm(request.POST, organization=organization)

        if form.is_valid():
            OrganizationMember.objects.create(
                organization=organization,
                user=form.user,
                role=form.cleaned_data["role"],
                department=form.cleaned_data["department"],
            )
            messages.success(request, _("Organization member added."))
            return redirect(
                "organizations:organization_members",
                organization_pk=organization.pk,
            )
        member_form = form

    elif request.method == "POST" and action == "add_department":
        form = DepartmentForm(request.POST)

        if form.is_valid():
            department = form.save(commit=False)
            department.organization = organization
            department.save()
            messages.success(request, _("Department added."))
            return redirect(
                "organizations:organization_members",
                organization_pk=organization.pk,
            )
        department_form = form

    members = (
        organization.members
        .select_related("user", "department")
        .order_by("department__name", "role", "user__username")
    )
    departments = organization.departments.order_by("name")

    return render(request, "organizations/member_list.html", {
        "organization": organization,
        "form": member_form,
        "department_form": department_form,
        "members": members,
        "departments": departments,
    })
