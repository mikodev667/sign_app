import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings

from bs4 import BeautifulSoup
import mammoth


class DocxPreviewService:
    TWIPS_PER_CM = 567
    TWIPS_PER_PX = 15

    @classmethod
    def convert_docx_to_html(cls, file_path: str) -> str:
        libreoffice_html = cls.convert_docx_to_html_with_libreoffice(file_path)

        if libreoffice_html:
            return cls.prepare_editor_html(libreoffice_html)

        with open(file_path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
            return cls.prepare_editor_html(result.value)

    @classmethod
    def prepare_editor_html(cls, html: str) -> str:
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")
        style_blocks = []

        for style in soup.find_all("style"):
            scoped_css = cls.scope_editor_css(style.get_text() or "")

            if scoped_css:
                style_blocks.append(scoped_css)

            style.decompose()

        for tag in soup.find_all(["script", "meta", "title", "link"]):
            tag.decompose()

        source = soup.body or soup
        attrs = []

        if getattr(source, "attrs", None):
            for attr_name in ["lang", "dir"]:
                attr_value = source.attrs.get(attr_name)

                if attr_value:
                    attrs.append(f'{attr_name}="{attr_value}"')

        body_html = "".join(str(child) for child in source.contents).strip()
        wrapper_attrs = " ".join(attrs)
        wrapper_attrs = f" {wrapper_attrs}" if wrapper_attrs else ""
        style_html = ""

        if style_blocks:
            style_html = (
                '<style data-docx-preview-style="true">'
                + "\n".join(style_blocks)
                + "</style>"
            )

        return f'{style_html}<div class="q-docx-html-fragment"{wrapper_attrs}>{body_html}</div>'

    @classmethod
    def scope_editor_css(cls, css: str) -> str:
        if not css:
            return ""

        css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        css = re.sub(r"@page[^{]*\{[^{}]*\}", "", css, flags=re.IGNORECASE)
        scoped_rules = []

        for selectors, declarations in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
            declarations = declarations.strip()

            if not declarations:
                continue

            scoped_selectors = []

            for selector in selectors.split(","):
                selector = selector.strip()

                if not selector:
                    continue

                if selector.lower() in {"html", "body", "html body"}:
                    continue

                if selector.startswith(".q-docx-html-fragment"):
                    scoped_selectors.append(selector)
                else:
                    scoped_selectors.append(f".q-docx-html-fragment {selector}")

            if scoped_selectors:
                scoped_rules.append(f"{', '.join(scoped_selectors)} {{ {declarations} }}")

        return "\n".join(scoped_rules)

    @classmethod
    def get_page_layout(cls, file_path: str) -> dict:
        try:
            with zipfile.ZipFile(file_path) as docx_zip:
                document_xml = docx_zip.read("word/document.xml")
        except (KeyError, OSError, zipfile.BadZipFile):
            return {}

        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError:
            return {}

        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        section = root.find(".//w:sectPr", namespace)

        if section is None:
            return {}

        page_size = section.find("w:pgSz", namespace)
        page_margins = section.find("w:pgMar", namespace)

        if page_size is None or page_margins is None:
            return {}

        def read_twips(element, attr, default):
            value = element.get(f"{{{namespace['w']}}}{attr}")

            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        width_twips = read_twips(page_size, "w", 11906)
        height_twips = read_twips(page_size, "h", 16838)

        return {
            "width_px": cls.format_number(width_twips / cls.TWIPS_PER_PX, precision=0),
            "height_px": cls.format_number(height_twips / cls.TWIPS_PER_PX, precision=0),
            "margin_top": cls.format_number(read_twips(page_margins, "top", 1134) / cls.TWIPS_PER_CM),
            "margin_right": cls.format_number(read_twips(page_margins, "right", 1134) / cls.TWIPS_PER_CM),
            "margin_bottom": cls.format_number(read_twips(page_margins, "bottom", 1134) / cls.TWIPS_PER_CM),
            "margin_left": cls.format_number(read_twips(page_margins, "left", 1134) / cls.TWIPS_PER_CM),
        }

    @staticmethod
    def format_number(value, *, precision=2):
        if precision == 0:
            return str(int(round(value)))

        formatted = f"{value:.{precision}f}".rstrip("0").rstrip(".")
        return formatted or "0"

    @classmethod
    def convert_docx_to_html_with_libreoffice(cls, file_path: str) -> str:
        if "test" in sys.argv:
            return ""

        soffice_path = cls.find_soffice()

        if not soffice_path:
            return ""

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, Path(file_path).name)
            shutil.copyfile(file_path, source_path)

            result = cls.run_soffice_conversion(
                soffice_path=soffice_path,
                file_path=source_path,
                output_dir=temp_dir,
            )

            html_path = os.path.join(temp_dir, Path(source_path).stem + ".html")

            if result.returncode != 0 or not os.path.exists(html_path):
                return ""

            with open(html_path, "r", encoding="utf-8", errors="ignore") as html_file:
                html = html_file.read()

            media_url = getattr(settings, "MEDIA_URL", "/media/")
            return cls.inline_generated_assets(
                html=html,
                html_path=html_path,
                media_url=media_url,
            )

    @classmethod
    def inline_generated_assets(cls, *, html: str, html_path: str, media_url: str) -> str:
        # LibreOffice may emit sibling image files. Keep the HTML usable in the
        # browser by rewriting relative image references to data URLs when small.
        html_dir = os.path.dirname(html_path)

        for image_path in Path(html_dir).glob("*"):
            if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif"}:
                continue

            if image_path.stat().st_size > 1024 * 1024:
                continue

            import base64

            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
            }[image_path.suffix.lower()]
            data = base64.b64encode(image_path.read_bytes()).decode("ascii")
            html = html.replace(
                image_path.name,
                f"data:{mime};base64,{data}",
            )

        return html

    @classmethod
    def run_soffice_conversion(cls, *, soffice_path: str, file_path: str, output_dir: str):
        profile_dir = os.path.join(output_dir, "lo_profile")
        profile_uri = Path(profile_dir).as_posix()

        try:
            return subprocess.run(
                [
                    soffice_path,
                    "--headless",
                    "--invisible",
                    "--nodefault",
                    "--nofirststartwizard",
                    "--nolockcheck",
                    "--norestore",
                    f"-env:UserInstallation=file:///{profile_uri}",
                    "--convert-to",
                    "html",
                    "--outdir",
                    output_dir,
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (PermissionError, FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return subprocess.CompletedProcess(args=[], returncode=1)

    @classmethod
    def find_soffice(cls) -> str:
        configured_path = getattr(settings, "LIBREOFFICE_PATH", "")
        configured_path = (configured_path or "").strip().strip('"')

        candidates = []

        if configured_path:
            if os.path.isfile(configured_path):
                return configured_path

            if os.path.isdir(configured_path):
                candidates.extend([
                    os.path.join(configured_path, "soffice.exe"),
                    os.path.join(configured_path, "program", "soffice.exe"),
                    os.path.join(configured_path, "soffice"),
                    os.path.join(configured_path, "program", "soffice"),
                ])

        found = shutil.which("soffice") or shutil.which("libreoffice")

        if found:
            return found

        candidates.extend([
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ])

        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate

        return ""
