from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from .forms import OrganizationMemberForm
from .models import OrganizationMember
from .services import get_user_managed_organizations


@login_required
def organization_list(request):
    organizations = (
        get_user_managed_organizations(request.user)
        .prefetch_related("members")
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

    if request.method == "POST":
        form = OrganizationMemberForm(request.POST, organization=organization)

        if form.is_valid():
            OrganizationMember.objects.create(
                organization=organization,
                user=form.user,
                role=form.cleaned_data["role"],
            )
            messages.success(request, _("Organization member added."))
            return redirect(
                "organizations:organization_members",
                organization_pk=organization.pk,
            )
    else:
        form = OrganizationMemberForm(organization=organization)

    members = (
        organization.members
        .select_related("user")
        .order_by("role", "user__username")
    )

    return render(request, "organizations/member_list.html", {
        "organization": organization,
        "form": form,
        "members": members,
    })
