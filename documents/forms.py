from django import forms

from .models import DocumentTemplate, Document, DocumentFieldValue


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