import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.utils.translation import gettext as _

from documents.models import StoredObject


@dataclass(frozen=True)
class ObjectPayload:
    data: bytes
    filename: str
    content_type: str
    sha256: str
    size_bytes: int


class ObjectStorageService:
    @classmethod
    def is_enabled(cls) -> bool:
        return bool(getattr(settings, "OBJECT_STORAGE_ENABLED", True))

    @classmethod
    def store_document_file(
        cls,
        *,
        document,
        file_field,
        object_type: str,
        created_by=None,
    ) -> StoredObject | None:
        if not cls.is_enabled():
            return None

        if not file_field:
            return None

        payload = cls._read_file_field(file_field)
        object_key = cls._build_object_key(
            document_id=document.id,
            object_type=object_type,
            sha256=payload.sha256,
            filename=payload.filename,
        )

        return cls._put_payload(
            document=document,
            object_type=object_type,
            object_key=object_key,
            payload=payload,
            created_by=created_by,
        )

    @classmethod
    def ensure_final_document_objects(cls, *, document, created_by=None) -> list[StoredObject]:
        stored_objects = []

        if document.rendered_pdf_file:
            stored_object = cls.store_document_file(
                document=document,
                file_field=document.rendered_pdf_file,
                object_type=StoredObject.ObjectType.FINAL_PDF,
                created_by=created_by,
            )
            if stored_object:
                stored_objects.append(stored_object)

        if document.rendered_docx_file:
            stored_object = cls.store_document_file(
                document=document,
                file_field=document.rendered_docx_file,
                object_type=StoredObject.ObjectType.FINAL_DOCX,
                created_by=created_by,
            )
            if stored_object:
                stored_objects.append(stored_object)

        return stored_objects

    @classmethod
    def verify_stored_object(cls, stored_object: StoredObject) -> bool:
        data = cls.get_stored_object_bytes(stored_object)
        return hashlib.sha256(data).hexdigest() == stored_object.sha256

    @classmethod
    def get_stored_object_bytes(cls, stored_object: StoredObject) -> bytes:
        client = cls._client()

        response = client.get_object(
            stored_object.bucket,
            stored_object.object_key,
            version_id=stored_object.version_id or None,
        )
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()

        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != stored_object.sha256:
            raise ValueError(
                _("Stored object hash mismatch: object=%(object_id)s expected=%(expected)s actual=%(actual)s")
                % {
                    "object_id": stored_object.id,
                    "expected": stored_object.sha256,
                    "actual": actual_hash,
                }
            )

        return data

    @classmethod
    def store_bytes(
        cls,
        *,
        document,
        data: bytes,
        filename: str,
        content_type: str,
        object_type: str,
        created_by=None,
    ) -> StoredObject | None:
        if not cls.is_enabled():
            return None

        sha256 = hashlib.sha256(data).hexdigest()
        payload = ObjectPayload(
            data=data,
            filename=filename,
            content_type=content_type,
            sha256=sha256,
            size_bytes=len(data),
        )
        object_key = cls._build_object_key(
            document_id=document.id,
            object_type=object_type,
            sha256=payload.sha256,
            filename=filename,
        )

        return cls._put_payload(
            document=document,
            object_type=object_type,
            object_key=object_key,
            payload=payload,
            created_by=created_by,
        )

    @classmethod
    def _put_payload(
        cls,
        *,
        document,
        object_type: str,
        object_key: str,
        payload: ObjectPayload,
        created_by=None,
    ) -> StoredObject:
        client = cls._client()
        bucket = settings.MINIO_BUCKET

        result = client.put_object(
            bucket,
            object_key,
            BytesIO(payload.data),
            length=payload.size_bytes,
            content_type=payload.content_type,
            metadata={
                "sha256": payload.sha256,
                "document-id": str(document.id),
                "object-type": object_type,
            },
        )

        retention_until = timezone.now() + timedelta(
            days=getattr(settings, "MINIO_DEFAULT_RETENTION_DAYS", 30)
        )
        retention_mode = StoredObject.RetentionMode.COMPLIANCE
        version_id = getattr(result, "version_id", "") or ""

        cls._set_object_retention(
            client=client,
            bucket=bucket,
            object_key=object_key,
            retention_mode=retention_mode,
            retention_until=retention_until,
            version_id=version_id,
        )

        stored_object, _ = StoredObject.objects.update_or_create(
            bucket=bucket,
            object_key=object_key,
            version_id=version_id,
            defaults={
                "document": document,
                "object_type": object_type,
                "etag": getattr(result, "etag", "") or "",
                "sha256": payload.sha256,
                "content_type": payload.content_type,
                "size_bytes": payload.size_bytes,
                "retention_mode": retention_mode,
                "retention_until": retention_until,
                "storage_status": StoredObject.StorageStatus.STORED,
                "created_by": created_by,
            },
        )

        return stored_object

    @classmethod
    def _read_file_field(cls, file_field) -> ObjectPayload:
        filename = PurePosixPath(file_field.name or "document.bin").name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        file_field.open("rb")
        try:
            data = file_field.read()
        finally:
            file_field.close()

        sha256 = hashlib.sha256(data).hexdigest()

        return ObjectPayload(
            data=data,
            filename=filename,
            content_type=content_type,
            sha256=sha256,
            size_bytes=len(data),
        )

    @classmethod
    def _build_object_key(
        cls,
        *,
        document_id: int,
        object_type: str,
        sha256: str,
        filename: str,
    ) -> str:
        safe_filename = filename.replace("\\", "/").split("/")[-1]
        return f"documents/{document_id}/{object_type}/{sha256}-{safe_filename}"

    @classmethod
    def _set_object_retention(
        cls,
        *,
        client,
        bucket: str,
        object_key: str,
        retention_mode: str,
        retention_until,
        version_id: str = "",
    ) -> None:
        try:
            from minio.retention import COMPLIANCE, GOVERNANCE, Retention
        except ImportError as exc:
            raise ImproperlyConfigured(
                _("The 'minio' package is required. Run: pip install -r requirements.txt")
            ) from exc

        mode_map = {
            StoredObject.RetentionMode.COMPLIANCE: COMPLIANCE,
            StoredObject.RetentionMode.GOVERNANCE: GOVERNANCE,
        }
        minio_mode = mode_map.get(retention_mode)

        if not minio_mode or not retention_until:
            return

        client.set_object_retention(
            bucket,
            object_key,
            Retention(minio_mode, retention_until),
            version_id=version_id or None,
        )

    @classmethod
    def _client(cls):
        try:
            from minio import Minio
        except ImportError as exc:
            raise ImproperlyConfigured(
                _("The 'minio' package is required. Run: pip install -r requirements.txt")
            ) from exc

        return Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
