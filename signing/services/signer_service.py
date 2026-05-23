import re

from django.db import transaction

from documents.models import Document
from signing.models import Signer


class SignerService:
    IIN_PATTERN = re.compile(r"^\d{12}$")

    @classmethod
    def validate_iin(cls, iin: str) -> None:
        if not iin:
            raise ValueError("IIN is required.")

        if not cls.IIN_PATTERN.match(iin):
            raise ValueError("IIN must contain exactly 12 digits.")

    @classmethod
    def validate_phone(cls, phone: str) -> None:
        if not phone or not phone.strip():
            raise ValueError("Phone is required.")

    @classmethod
    def validate_signing_order(cls, signing_order: int) -> None:
        if signing_order < 1:
            raise ValueError("Signing order must be greater than or equal to 1.")

    @classmethod
    def ensure_document_can_be_edited(cls, document: Document) -> None:
        if document.status != Document.Status.DRAFT:
            raise ValueError("Signers can be edited only while document is draft.")

    @classmethod
    @transaction.atomic
    def add_signer(
        cls,
        *,
        document: Document,
        full_name: str,
        iin: str,
        phone: str,
        signing_order: int = 1,
    ) -> Signer:
        cls.ensure_document_can_be_edited(document)

        full_name = full_name.strip() if full_name else ""
        iin = iin.strip() if iin else ""
        phone = phone.strip() if phone else ""

        if not full_name:
            raise ValueError("Full name is required.")

        cls.validate_iin(iin)
        cls.validate_phone(phone)
        cls.validate_signing_order(signing_order)

        existing_signer = Signer.objects.filter(
            document=document,
            iin=iin,
        ).first()

        if existing_signer:
            raise ValueError("Signer with this IIN already exists for this document.")

        signer = Signer.objects.create(
            document=document,
            full_name=full_name,
            iin=iin,
            phone=phone,
            signing_order=signing_order,
            status=Signer.Status.PENDING,
        )

        return signer

    @classmethod
    @transaction.atomic
    def add_signers(
        cls,
        *,
        document: Document,
        signers_data: list[dict],
    ) -> list[Signer]:
        created_signers = []

        for item in signers_data:
            signer = cls.add_signer(
                document=document,
                full_name=item.get("full_name", ""),
                iin=item.get("iin", ""),
                phone=item.get("phone", ""),
                signing_order=int(item.get("signing_order", 1)),
            )

            created_signers.append(signer)

        return created_signers

    @classmethod
    def get_current_signing_order(cls, *, document: Document) -> int | None:
        unsigned_signer = (
            document.signers
            .exclude(status=Signer.Status.SIGNED)
            .order_by("signing_order", "created_at")
            .first()
        )

        if not unsigned_signer:
            return None

        return unsigned_signer.signing_order

    @classmethod
    def get_current_order_signers(cls, *, document: Document):
        current_order = cls.get_current_signing_order(document=document)

        if current_order is None:
            return Signer.objects.none()

        return document.signers.filter(
            signing_order=current_order,
        ).exclude(
            status=Signer.Status.SIGNED,
        ).order_by("created_at")