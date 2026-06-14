import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage

from .docx_preview_service import DocxPreviewService
from .docx_template_service import DocxTemplateService, VARIABLE_PATTERN


class TemplateFileService:
    ALLOWED_EXTENSIONS = {".doc", ".docx"}

    @classmethod
    def get_extension(cls, file_name: str) -> str:
        return Path(file_name or "").suffix.lower()

    @classmethod
    def validate_file_name(cls, file_name: str):
        extension = cls.get_extension(file_name)

        if extension not in cls.ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(cls.ALLOWED_EXTENSIONS))
            raise ValueError(f"Unsupported template format. Allowed formats: {allowed}.")

    @classmethod
    def normalize_template_file_to_docx(cls, template) -> bool:
        if not template.template_file:
            return False

        template_path = template.template_file.path
        extension = cls.get_extension(template_path)

        if extension == ".docx":
            return False

        if extension != ".doc":
            cls.validate_file_name(template_path)
            return False

        old_file_name = template.template_file.name

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, Path(template_path).stem + ".docx")
            cls.convert_doc_to_docx(file_path=template_path, output_path=output_path)

            new_file_name = f"{Path(old_file_name).stem}_{uuid4().hex}.docx"

            with open(output_path, "rb") as converted_file:
                template.template_file.save(
                    new_file_name,
                    File(converted_file),
                    save=False,
                )

        template.save(update_fields=["template_file", "updated_at"])

        if old_file_name and old_file_name != template.template_file.name:
            default_storage.delete(old_file_name)

        return True

    @classmethod
    def extract_variables(cls, file_path: str) -> list[str]:
        with cls.as_docx_path(file_path) as docx_path:
            return DocxTemplateService.extract_variables(docx_path)

    @classmethod
    def convert_to_html(cls, file_path: str) -> str:
        with cls.as_docx_path(file_path) as docx_path:
            return DocxPreviewService.convert_docx_to_html(docx_path)

    @classmethod
    def render_to_docx(cls, *, template_path: str, output_path: str, values: dict):
        with cls.as_docx_path(template_path) as docx_path:
            DocxTemplateService.render_docx(
                template_path=docx_path,
                output_path=output_path,
                values=values,
            )

    @classmethod
    def convert_doc_to_docx(cls, *, file_path: str, output_path: str):
        extension = cls.get_extension(file_path)

        if extension == ".docx":
            shutil.copyfile(file_path, output_path)
            return

        if extension != ".doc":
            cls.validate_file_name(file_path)
            raise ValueError("Only DOC and DOCX files can be converted to DOCX.")

        soffice_path = cls.find_soffice()

        if not soffice_path:
            raise ValueError(
                "DOC files require LibreOffice on the server for conversion to DOCX."
            )

        with tempfile.TemporaryDirectory() as output_dir:
            result = cls.run_soffice_conversion(
                soffice_path=soffice_path,
                file_path=file_path,
                output_dir=output_dir,
                convert_to="docx",
                timeout=60,
                operation="converting DOC to DOCX",
            )

            converted_path = os.path.join(output_dir, Path(file_path).stem + ".docx")

            if result.returncode != 0 or not os.path.exists(converted_path):
                detail = (result.stderr or result.stdout or "").strip()
                raise ValueError(
                    "Could not convert DOC file to DOCX."
                    + (f" Converter output: {detail}" if detail else "")
                )

            shutil.copyfile(converted_path, output_path)

    @classmethod
    def run_soffice_conversion(
        cls,
        *,
        soffice_path: str,
        file_path: str,
        output_dir: str,
        convert_to: str,
        timeout: int,
        operation: str,
    ):
        try:
            return subprocess.run(
                [
                    soffice_path,
                    "--headless",
                    "--convert-to",
                    convert_to,
                    "--outdir",
                    output_dir,
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except PermissionError as exc:
            raise ValueError(
                f"LibreOffice cannot be executed: {soffice_path}. "
                "Check LIBREOFFICE_PATH and file permissions."
            ) from exc
        except FileNotFoundError as exc:
            raise ValueError(
                f"LibreOffice executable was not found: {soffice_path}."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"LibreOffice conversion timed out while {operation}."
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"LibreOffice could not be started: {exc}"
            ) from exc

    @classmethod
    def extract_variables_from_text(cls, text: str) -> list[str]:
        variables = VARIABLE_PATTERN.findall(text or "")
        result = []
        seen = set()

        for variable in variables:
            if variable not in seen:
                seen.add(variable)
                result.append(variable)

        return result

    @classmethod
    @contextmanager
    def as_docx_path(cls, file_path: str):
        extension = cls.get_extension(file_path)

        if extension == ".docx":
            yield file_path
            return

        if extension != ".doc":
            cls.validate_file_name(file_path)
            raise ValueError("Only DOC and DOCX files can be converted to DOCX.")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, Path(file_path).stem + ".docx")
            cls.convert_doc_to_docx(file_path=file_path, output_path=output_path)
            yield output_path

    @classmethod
    def find_soffice(cls) -> str:
        configured_path = getattr(settings, "LIBREOFFICE_PATH", "")
        resolved_configured_path = cls.resolve_soffice_path(configured_path)

        if resolved_configured_path:
            return resolved_configured_path

        found = shutil.which("soffice") or shutil.which("libreoffice")

        if found:
            return found

        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]

        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate

        return ""

    @classmethod
    def resolve_soffice_path(cls, configured_path: str) -> str:
        configured_path = (configured_path or "").strip().strip('"')

        if not configured_path:
            return ""

        if os.path.isfile(configured_path):
            return configured_path

        if os.path.isdir(configured_path):
            candidates = [
                os.path.join(configured_path, "soffice.exe"),
                os.path.join(configured_path, "program", "soffice.exe"),
                os.path.join(configured_path, "soffice"),
                os.path.join(configured_path, "program", "soffice"),
            ]

            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate

        return ""
