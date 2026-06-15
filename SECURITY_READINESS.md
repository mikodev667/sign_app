# Security Readiness

## Current Dev Evidence Storage

The project now has a local immutable-object-storage development contour:

- PostgreSQL stores metadata and evidence references.
- MinIO stores final document bytes.
- MinIO bucket is created with Object Lock.
- Bucket versioning is enabled.
- Default retention is configured in COMPLIANCE mode.
- Django records `bucket`, `object_key`, `version_id`, `sha256`, `size_bytes`, `content_type`, `retention_mode`, and `retention_until` in `documents.StoredObject`.

## Local Services

- Django: `http://127.0.0.1:8000/`
- MinIO API: `http://127.0.0.1:9000`
- MinIO Console: `http://127.0.0.1:9002`
- MinIO bucket: `sign-app-documents`

## Verification Commands

Start MinIO:

```powershell
docker compose up -d minio minio-init
```

Check container status:

```powershell
docker compose ps
```

Verify the newest stored object hash through Django:

```powershell
.\venv\Scripts\python.exe manage.py shell -c "from documents.models import StoredObject; from documents.services.object_storage_service import ObjectStorageService; obj=StoredObject.objects.latest('created_at'); print(obj.id, obj.version_id, ObjectStorageService.verify_stored_object(obj))"
```

Expected result: `True`.

## Implemented Controls

- Final rendered PDF/DOCX is stored in MinIO before a signing access link is issued.
- Signing access link creation fails if object storage is enabled and no final file can be stored.
- Stored object integrity is verified using SHA-256.
- Object version id is persisted in PostgreSQL.
- Object retention metadata is persisted in PostgreSQL.
- `SigningAuditLog` has per-document hash-chain fields: `previous_hash`, `payload_hash`, `entry_hash`.
- Existing signing audit records are backfilled into a verifiable hash chain.
- PostgreSQL triggers block direct `UPDATE` and `DELETE` on `signing_signingauditlog`.
- Django model methods block ordinary application-level update/delete attempts for `SigningAuditLog`.
- `verify_audit_chain` management command verifies audit-chain integrity.
- PostgreSQL triggers block direct `UPDATE` and `DELETE` on `signing_signature`.
- PostgreSQL triggers block direct `UPDATE` and `DELETE` on documents after their status becomes `signed`.
- Django model methods block ordinary application-level update/delete attempts for signatures and signed documents.
- Evidence bundles can be generated as ZIP archives with manifest, stored object metadata, signatures, audit trail, integrity report, and final document files.
- Evidence bundle generation verifies MinIO object SHA-256 and audit hash-chain before returning the archive.
- Generated evidence bundles are stored back in MinIO as `StoredObject` records with `object_type=evidence_bundle`.

## Still Pending

- PostgreSQL runtime roles (`sign_app_app`, `sign_app_migrator`, `sign_app_readonly`, `sign_app_backup`).
- PITR/WAL backup and restore-drill protocol.
- Admin access log and access matrix.
- Production TLS/encryption/KMS decisions.
