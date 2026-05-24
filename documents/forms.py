from django import forms

from .models import DocumentTemplate, Document, DocumentFieldValue


class DocumentTemplateUploadForm(forms.ModelForm):
    class Meta:
        model = DocumentTemplate
        fields = ["organization", "title", "template_file", "status"]


class DocumentCreateForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["organization", "template", "title"]


class DocumentFieldValueForm(forms.ModelForm):
    class Meta:
        model = DocumentFieldValue
        fields = ["field_value"]


class DocumentFromTemplateForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title"]