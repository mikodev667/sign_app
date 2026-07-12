from django import forms

from signing.models import Signer


class SignerForm(forms.ModelForm):
    class Meta:
        model = Signer
        fields = ["full_name", "iin", "phone", "email", "signing_order"]

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
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "signer@example.com",
            }),
            "signing_order": forms.NumberInput(attrs={
                "class": "form-control",
                "min": "1",
            }),
        }
