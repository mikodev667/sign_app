from django import forms

from signing.models import Signer


class SignerForm(forms.ModelForm):
    class Meta:
        model = Signer
        fields = ["full_name", "iin", "phone", "signing_order", "signing_method"]

        widgets = {
            "full_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Example: Ivan Ivanov",
            }),
            "iin": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "12 digits",
                "maxlength": "12",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "+7 777 000 00 00",
            }),
            "signing_order": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "1",
            }),
            "signing_method": forms.Select(attrs={
                "class": "form-control",
            }),
        }