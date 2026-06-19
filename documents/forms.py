from django import forms
from django.utils.translation import gettext_lazy as _

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
    document_file = forms.FileField(
        required=False,
        label=_("Ready DOC/DOCX file"),
        help_text=_("Upload a prepared DOC or DOCX document instead of choosing a template."),
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": ".doc,.docx",
            "data-document-file-input": "true",
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["template"].required = False
        self.fields["template"].empty_label = _("Без шаблона")
        self.fields["template"].widget.attrs["data-template-select"] = "true"
        self.fields["template"].label = _("Template")
        self.fields["template"].empty_label = _("No template")
        self.fields["title"].label = _("Document title")

        if user is not None:
            organizations = get_user_managed_organizations(user)
            self.fields["template"].queryset = DocumentTemplate.objects.filter(
                organization__in=organizations,
                status=DocumentTemplate.Status.ACTIVE,
            ).order_by("title")

    def clean_document_file(self):
        document_file = self.cleaned_data.get("document_file")

        if document_file:
            try:
                TemplateFileService.validate_file_name(document_file.name)
            except ValueError as exc:
                raise forms.ValidationError(str(exc)) from exc

        return document_file

    def clean(self):
        cleaned_data = super().clean()
        template = cleaned_data.get("template")
        document_file = cleaned_data.get("document_file")

        if bool(template) == bool(document_file):
            raise forms.ValidationError(
                _("Choose a template or upload a ready DOC/DOCX file.")
            )

        return cleaned_data

    class Meta:
        model = Document
        fields = ["template", "title", "document_file"]

        widgets = {
            "template": forms.Select(attrs={
                "class": "form-control",
            }),
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": _("Example: Employment Agreement with John Smith"),
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
