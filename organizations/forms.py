from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .models import Department, OrganizationMember


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name"]

        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": _("Example: Admissions department"),
            }),
        }


class OrganizationMemberForm(forms.Form):
    username_or_email = forms.CharField(
        label=_("Username or email"),
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": _("Registered username or email"),
        }),
    )

    role = forms.ChoiceField(
        label=_("Role"),
        choices=OrganizationMember.Role.choices,
        initial=OrganizationMember.Role.MEMBER,
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    department = forms.ModelChoiceField(
        label=_("Department"),
        queryset=Department.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.user = None
        if organization:
            self.fields["department"].queryset = organization.departments.filter(
                is_active=True,
            ).order_by("name")

    def clean_department(self):
        department = self.cleaned_data.get("department")

        if department:
            return department

        departments = self.fields["department"].queryset

        if departments.count() == 1:
            return departments.first()

        raise forms.ValidationError(_("Choose a department."))

    def clean_username_or_email(self):
        value = self.cleaned_data["username_or_email"].strip()
        User = get_user_model()

        user = (
            User.objects
            .filter(Q(username__iexact=value) | Q(email__iexact=value))
            .first()
        )

        if not user:
            raise forms.ValidationError(_("Registered user was not found."))

        current_organization_membership = OrganizationMember.objects.filter(
            organization=self.organization,
            user=user,
        )

        if self.organization and current_organization_membership.exists():
            raise forms.ValidationError(_("This user is already a member of the organization."))

        other_organization_membership = OrganizationMember.objects.filter(
            user=user,
        )

        if self.organization:
            other_organization_membership = other_organization_membership.exclude(
                organization=self.organization,
            )

        if other_organization_membership.exists():
            raise forms.ValidationError(_("This user already belongs to another organization."))

        self.user = user
        return value
