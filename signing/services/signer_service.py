import re

from django.db import transaction

from documents.models import Document
from signing.models import Signer, SigningAuditLog
from signing.services.audit_log_service import SigningAuditLogService


class SignerService:
    IIN_PATTERN = re.compile(r"^\d{12}$")

    @classmethod
    def validate_iin(cls, iin: str) -> None:
        if not iin:
            raise ValueError("ИИН обязателен.")

        if not cls.IIN_PATTERN.match(iin):
            raise ValueError("ИИН должен содержать ровно 12 цифр.")

    @classmethod
    def normalize_phone(cls, phone: str) -> str:
        cleaned = re.sub(r"\D", "", phone or "")

        if cleaned.startswith("8") and len(cleaned) == 11:
            cleaned = "7" + cleaned[1:]

        return cleaned

    @classmethod
    def validate_phone(cls, phone: str) -> None:
        if not phone or not phone.strip():
            raise ValueError("Телефон обязателен.")

        normalized_phone = cls.normalize_phone(phone)

        if not re.fullmatch(r"7\d{10}", normalized_phone):
            raise ValueError("Телефон должен быть корректным номером Казахстана, например +77071234567.")

    @classmethod
    def validate_signing_order(cls, signing_order: int) -> None:
        if signing_order < 1:
            raise ValueError("Порядок подписания должен быть не меньше 1.")

    @classmethod
    def ensure_document_can_be_edited(cls, document: Document) -> None:
        if hasattr(document, "can_be_edited"):
            if not document.can_be_edited():
                raise ValueError("Signers can be edited only before signer invitation.")
            return

        if document.status != Document.Status.DRAFT:
            raise ValueError("Подписантов можно редактировать только пока документ находится в черновике.")

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
        signing_method: str = Signer.SigningMethod.EGOV_MOBILE,
        template_party=None,
        role_title: str = "",
        request=None,
    ) -> Signer:
        cls.ensure_document_can_be_edited(document)

        full_name = full_name.strip() if full_name else ""
        iin = iin.strip() if iin else ""
        phone = phone.strip() if phone else ""
        role_title = role_title.strip() if role_title else ""

        if not full_name:
            raise ValueError("ФИО обязательно.")

        try:
            signing_order = int(signing_order)
        except (TypeError, ValueError):
            raise ValueError("Порядок подписания должен быть числом.")

        cls.validate_iin(iin)
        cls.validate_phone(phone)
        cls.validate_signing_order(signing_order)

        normalized_phone = cls.normalize_phone(phone)

        if signing_method not in Signer.SigningMethod.values:
            raise ValueError("Некорректный способ подписания.")

        existing_signer = Signer.objects.filter(
            document=document,
            iin=iin,
        ).first()

        if existing_signer:
            raise ValueError("Подписант с таким ИИН уже добавлен к этому документу.")

        signer = Signer.objects.create(
            document=document,
            full_name=full_name,
            iin=iin,
            phone=normalized_phone,
            signing_order=signing_order,
            signing_method=signing_method,
            status=Signer.Status.PENDING,
            template_party=template_party,
            role_title=role_title,
        )

        SigningAuditLogService.log_signer_event(
            signer=signer,
            event=SigningAuditLog.Event.SIGNER_ADDED,
            request=request,
            metadata={
                "signing_order": signer.signing_order,
                "signing_method": signer.signing_method,
                "template_party_id": signer.template_party_id,
                "role_title": signer.role_title,
            },
        )

        return signer

    @classmethod
    @transaction.atomic
    def add_signers(
        cls,
        *,
        document: Document,
        signers_data: list[dict],
        request=None,
    ) -> list[Signer]:
        cls.ensure_document_can_be_edited(document)

        created_signers = []

        for item in signers_data:
            signer = cls.add_signer(
                document=document,
                full_name=item.get("full_name", ""),
                iin=item.get("iin", ""),
                phone=item.get("phone", ""),
                signing_order=item.get("signing_order", 1),
                signing_method=item.get(
                    "signing_method",
                    Signer.SigningMethod.EGOV_MOBILE,
                ),
                template_party=item.get("template_party"),
                role_title=item.get("role_title", ""),
                request=request,
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

        return (
            document.signers
            .filter(signing_order=current_order)
            .exclude(status=Signer.Status.SIGNED)
            .order_by("created_at")
        )

    @classmethod
    def can_sign_now(cls, *, signer: Signer) -> bool:
        """
        Проверка очередности подписания.

        Если есть подписанты с меньшим signing_order,
        которые ещё не подписали, текущий подписант ждать должен.
        """

        previous_unsigned_exists = (
            signer.document.signers
            .filter(signing_order__lt=signer.signing_order)
            .exclude(status=Signer.Status.SIGNED)
            .exists()
        )

        return not previous_unsigned_exists

    @classmethod
    def ensure_can_sign_now(cls, *, signer: Signer) -> None:
        if signer.status == Signer.Status.SIGNED:
            raise ValueError("Этот подписант уже подписал документ.")

        if not cls.can_sign_now(signer=signer):
            raise ValueError("Сначала документ должны подписать предыдущие подписанты.")
