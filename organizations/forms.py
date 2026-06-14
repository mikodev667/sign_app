from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import OrganizationMember


class OrganizationMemberForm(forms.Form):
    username_or_email = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Registered username or email",
        }),
    )

    role = forms.ChoiceField(
        label="Role",
        choices=OrganizationMember.Role.choices,
        initial=OrganizationMember.Role.MEMBER,
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.user = None

    def clean_username_or_email(self):
        value = self.cleaned_data["username_or_email"].strip()
        User = get_user_model()

        user = (
            User.objects
            .filter(Q(username__iexact=value) | Q(email__iexact=value))
            .first()
        )

        if not user:
            raise forms.ValidationError("Registered user was not found.")

        current_organization_membership = OrganizationMember.objects.filter(
            organization=self.organization,
            user=user,
        )

        if self.organization and current_organization_membership.exists():
            raise forms.ValidationError("This user is already a member of the organization.")

        other_organization_membership = OrganizationMember.objects.filter(
            user=user,
        )

        if self.organization:
            other_organization_membership = other_organization_membership.exclude(
                organization=self.organization,
            )

        if other_organization_membership.exists():
            raise forms.ValidationError("This user already belongs to another organization.")

        self.user = user
        return value
