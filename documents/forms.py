from django import forms

from organizations.services import get_user_managed_organizations

from .models import (
    DocumentTemplate,
    Document,
    DocumentFieldValue,
    TemplateParty,
    TemplatePartyField,
)
from .services.template_file_service import TemplateFileService


class DocumentTemplateUploadForm(forms.ModelForm):
    class Meta:
        model = DocumentTemplate
        fields = ["title", "template_file", "status"]

        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Employment Agreement Template",
            }),
            "template_file": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": ".doc,.docx",
            }),
            "status": forms.Select(attrs={
                "class": "form-control",
            }),
        }

    def clean_template_file(self):
        return clean_template_file_field(self.cleaned_data.get("template_file"))


class DocumentCreateForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user is not None:
            organizations = get_user_managed_organizations(user)
            self.fields["template"].queryset = DocumentTemplate.objects.filter(
                organization__in=organizations,
                status=DocumentTemplate.Status.ACTIVE,
            ).order_by("title")

    class Meta:
        model = Document
        fields = ["template", "title"]

        widgets = {
            "template": forms.Select(attrs={
                "class": "form-control",
            }),
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Employment Agreement with John Smith",
            }),
        }


class DocumentFieldValueForm(forms.ModelForm):
    class Meta:
        model = DocumentFieldValue
        fields = ["field_value"]

        widgets = {
            "field_value": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Enter value",
            }),
        }


class DocumentFromTemplateForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title"]

        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Employment Agreement with John Smith",
            }),
        }


class TemplatePartyForm(forms.ModelForm):
    class Meta:
        model = TemplateParty
        fields = [
            "title",
            "variable_prefix",
            "party_type",
            "signing_order",
            "is_signer",
        ]

        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Customer",
            }),
            "variable_prefix": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: customer",
            }),
            "party_type": forms.Select(attrs={
                "class": "form-control",
            }),
            "signing_order": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "1",
            }),
            "is_signer": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }


class TemplatePartyFieldForm(forms.ModelForm):
    class Meta:
        model = TemplatePartyField
        fields = [
            "label",
            "variable_name",
            "field_type",
            "is_required",
            "default_value",
            "order",
        ]

        widgets = {
            "label": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Legal address",
            }),
            "variable_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: legal_address",
            }),
            "field_type": forms.Select(attrs={
                "class": "form-control",
            }),
            "is_required": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
            "default_value": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Default value, optional",
            }),
            "order": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "1",
            }),
        }


def clean_template_file_field(template_file):
    if template_file:
        try:
            TemplateFileService.validate_file_name(template_file.name)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    return template_file
