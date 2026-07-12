from documents.models import TemplatePartyField


SYSTEM_PARTY_FIELDS = [
    {
        "label": "Full name",
        "variable_name": "full_name",
        "field_type": "text",
        "is_required": True,
        "is_system": True,
        "order": 1,
    },
    {
        "label": "IIN / BIN",
        "variable_name": "iin_bin",
        "field_type": "iin_bin",
        "is_required": True,
        "is_system": True,
        "order": 2,
    },
    {
        "label": "Phone",
        "variable_name": "phone",
        "field_type": "phone",
        "is_required": True,
        "is_system": True,
        "order": 3,
    },
    {
        "label": "Email",
        "variable_name": "email",
        "field_type": "email",
        "is_required": False,
        "is_system": True,
        "order": 4,
    },
    {
        "label": "Signing method",
        "variable_name": "signing_method",
        "field_type": "signing_method",
        "is_required": True,
        "is_system": True,
        "order": 5,
    },
]


def create_system_party_fields(party):
    for field_data in SYSTEM_PARTY_FIELDS:
        TemplatePartyField.objects.get_or_create(
            party=party,
            variable_name=field_data["variable_name"],
            defaults=field_data,
        )
