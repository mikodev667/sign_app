from django import forms

from .models import (
    DocumentTemplate,
    Document,
    DocumentFieldValue,
    TemplateParty,
    TemplatePartyField,
)


class DocumentTemplateUploadForm(forms.ModelForm):
    class Meta:
        model = DocumentTemplate
        fields = ["organization", "title", "template_file", "status"]

        widgets = {
            "organization": forms.Select(attrs={
                "class": "form-control",
            }),
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Employment Agreement Template",
            }),
            "template_file": forms.ClearableFileInput(attrs={
                "class": "form-control",
            }),
            "status": forms.Select(attrs={
                "class": "form-control",
            }),
        }


class DocumentCreateForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["organization", "template", "title"]

        widgets = {
            "organization": forms.Select(attrs={
                "class": "form-control",
            }),
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