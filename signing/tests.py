from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from documents.models import Document, StoredObject
from organizations.models import Organization
from signing.models import Signer, SigningSession, Signature
from signing.services.ecp_signing_service import EcpSigningService


class EcpCmsFileTests(TestCase):
    def test_ecp_signing_stores_cms_in_object_storage(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            signer = self.create_ecp_signer()
            cms_signature = "-----BEGIN CMS-----\nTEST-CMS\n-----END CMS-----"
            stored_object = SimpleNamespace(
                id=10,
                bucket="test-bucket",
                object_key="documents/1/signature/hash-document_1_signature_1_signer_1.cms",
                version_id="version-1",
                sha256="b" * 64,
                retention_until=None,
            )

            verify_patch = patch(
                "signing.services.ecp_signing_service.EcpValidationClient.verify",
                return_value={
                    "ok": True,
                    "certificate_iin": signer.iin,
                    "certificate_subject": "CN=Test Signer",
                    "certificate_serial": "123",
                },
            )
            storage_patch = patch(
                "signing.services.ecp_signing_service.ObjectStorageService.store_bytes",
                return_value=stored_object,
            )

            with verify_patch, storage_patch as store_bytes:
                signature = EcpSigningService.complete_signing(
                    signer=signer,
                    cms_signature=cms_signature,
                    signed_payload={"cms_signature": cms_signature},
                )

            self.assertEqual(signature.provider, SigningSession.Provider.ECP)
            store_bytes.assert_called_once()

            _, kwargs = store_bytes.call_args
            self.assertEqual(kwargs["document"], signature.document)
            self.assertEqual(kwargs["data"], cms_signature.encode("utf-8"))
            self.assertEqual(kwargs["content_type"], "application/pkcs7-mime")
            self.assertEqual(kwargs["object_type"], StoredObject.ObjectType.SIGNATURE)
            self.assertEqual(
                kwargs["filename"],
                f"document_{signature.document_id}_signature_{signature.id}_signer_{signature.signer_id}.cms",
            )

    def test_ecp_cms_download_returns_stored_object_file(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            signer = self.create_ecp_signer()
            cms_signature = "-----BEGIN CMS-----\nDOWNLOAD-CMS\n-----END CMS-----"
            stored_object = SimpleNamespace(
                id=10,
                bucket="test-bucket",
                object_key="documents/1/signature/hash-document_1_signature_1_signer_1.cms",
                version_id="version-1",
                sha256="b" * 64,
                retention_until=None,
            )

            verify_patch = patch(
                "signing.services.ecp_signing_service.EcpValidationClient.verify",
                return_value={
                    "ok": True,
                    "certificate_iin": signer.iin,
                    "certificate_subject": "CN=Test Signer",
                    "certificate_serial": "123",
                },
            )
            storage_patch = patch(
                "signing.services.ecp_signing_service.ObjectStorageService.store_bytes",
                return_value=stored_object,
            )

            with verify_patch, storage_patch:
                signature = EcpSigningService.complete_signing(
                    signer=signer,
                    cms_signature=cms_signature,
                    signed_payload={"cms_signature": cms_signature},
                )

            stored_cms_object = StoredObject.objects.create(
                document=signature.document,
                object_type=StoredObject.ObjectType.SIGNATURE,
                bucket="test-bucket",
                object_key=(
                    "documents/"
                    f"{signature.document_id}/signature/hash-"
                    f"document_{signature.document_id}_signature_{signature.id}_"
                    f"signer_{signature.signer_id}.cms"
                ),
                version_id="version-1",
                sha256="b" * 64,
                content_type="application/pkcs7-mime",
                size_bytes=len(cms_signature.encode("utf-8")),
            )

            with patch(
                "signing.views.ObjectStorageService.get_stored_object_bytes",
                return_value=cms_signature.encode("utf-8"),
            ) as get_stored_object_bytes:
                response = self.client.get(
                    reverse("signing:signature_cms_download", args=[signature.pk])
                )

            get_stored_object_bytes.assert_called_once_with(stored_cms_object)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pkcs7-mime")
            self.assertIn(".cms", response["Content-Disposition"])
            self.assertEqual(response.content.decode("utf-8"), cms_signature)

    def test_ecp_cms_download_falls_back_to_signature_value(self):
        signer = self.create_ecp_signer()
        session = SigningSession.objects.create(
            signer=signer,
            provider=SigningSession.Provider.ECP,
            status=SigningSession.Status.SIGNED,
            document_hash=signer.document.content_hash,
        )
        signature = Signature.objects.create(
            signer=signer,
            document=signer.document,
            signing_session=session,
            provider=SigningSession.Provider.ECP,
            signature_value="-----BEGIN CMS-----\nOLD-CMS\n-----END CMS-----",
            signed_content_hash=signer.document.content_hash,
            signed_at=timezone.now(),
            is_valid=True,
        )

        response = self.client.get(
            reverse("signing:signature_cms_download", args=[signature.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content.decode("utf-8"),
            "-----BEGIN CMS-----\nOLD-CMS\n-----END CMS-----",
        )

    def test_ecp_cms_download_404_when_object_and_legacy_value_missing(self):
        signer = self.create_ecp_signer()
        session = SigningSession.objects.create(
            signer=signer,
            provider=SigningSession.Provider.ECP,
            status=SigningSession.Status.SIGNED,
            document_hash=signer.document.content_hash,
        )
        signature = Signature.objects.create(
            signer=signer,
            document=signer.document,
            signing_session=session,
            provider=SigningSession.Provider.ECP,
            signature_value="",
            signed_content_hash=signer.document.content_hash,
            signed_at=timezone.now(),
            is_valid=True,
        )

        response = self.client.get(
            reverse("signing:signature_cms_download", args=[signature.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_cms_download_rejects_non_ecp_signature(self):
        signer = self.create_ecp_signer(signing_method=Signer.SigningMethod.SMS)
        session = SigningSession.objects.create(
            signer=signer,
            provider=SigningSession.Provider.SMS,
            status=SigningSession.Status.SIGNED,
            document_hash=signer.document.content_hash,
        )
        signature = Signature.objects.create(
            signer=signer,
            document=signer.document,
            signing_session=session,
            provider=SigningSession.Provider.SMS,
            signature_value="SMS_CONFIRMATION",
            signed_content_hash=signer.document.content_hash,
            signed_at=timezone.now(),
            is_valid=True,
        )

        response = self.client.get(
            reverse("signing:signature_cms_download", args=[signature.pk])
        )

        self.assertEqual(response.status_code, 404)

    @staticmethod
    def create_ecp_signer(signing_method=Signer.SigningMethod.ECP):
        user = get_user_model().objects.create_user(
            username=f"user-{signing_method}",
            password="password",
        )
        organization = Organization.objects.create(
            name=f"Organization {signing_method}",
            created_by=user,
        )
        document = Document.objects.create(
            organization=organization,
            created_by=user,
            title=f"Document {signing_method}",
            content_hash="a" * 64,
        )
        return Signer.objects.create(
            document=document,
            full_name="Test Signer",
            iin="123456789012",
            phone="77071234567",
            signing_method=signing_method,
        )
