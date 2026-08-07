from django import forms
from django.utils.translation import gettext_lazy as _

from organizations.models import Department
from organizations.services import (
    get_department_access_filter,
    get_user_accessible_departments,
)

from .models import (
    DocumentTemplate,
    Document,
    DocumentFieldValue,
    TemplateParty,
    TemplatePartyField,
)
from .services.template_file_service import TemplateFileService


class DocumentTemplateUploadForm(forms.ModelForm):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label=_("Department"),
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    def __init__(self, *args, user=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)

        departments = Department.objects.none()
        if user is not None and organization is not None:
            departments = get_user_accessible_departments(user, organization)

        self.fields["department"].queryset = departments

        if departments.count() == 1:
            self.fields["department"].initial = departments.first()

    class Meta:
        model = DocumentTemplate
        fields = ["title", "department", "template_file", "status"]

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

    def clean_department(self):
        department = self.cleaned_data.get("department")

        if department:
            return department

        departments = self.fields["department"].queryset

        if departments.count() == 1:
            return departments.first()

        raise forms.ValidationError(_("Choose a department."))


class DocumentCreateForm(forms.ModelForm):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        label=_("Department"),
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

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
            self.fields["template"].queryset = DocumentTemplate.objects.filter(
                get_department_access_filter(user),
                status=DocumentTemplate.Status.ACTIVE,
            ).order_by("title").distinct()

            departments = get_user_accessible_departments(user)
            self.fields["department"].queryset = departments

            if departments.count() == 1:
                self.fields["department"].initial = departments.first()

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

        department = cleaned_data.get("department")

        if not department:
            departments = self.fields["department"].queryset
            if departments.count() == 1:
                department = departments.first()
                cleaned_data["department"] = department

        if document_file and not department:
            self.add_error("department", _("Choose a department for the uploaded document."))

        return cleaned_data

    class Meta:
        model = Document
        fields = ["template", "department", "title", "document_file"]

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
