import re

from docx import Document as DocxDocument
from docx.shared import RGBColor
from docxtpl import DocxTemplate


VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class DocxTemplateService:
    @classmethod
    def extract_text_from_docx(cls, file_path: str) -> str:
        doc = DocxDocument(file_path)
        parts = []

        for paragraph in doc.paragraphs:
            parts.append(paragraph.text)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)

        return "\n".join(parts)

    @classmethod
    def extract_variables(cls, file_path: str) -> list[str]:
        text = cls.extract_text_from_docx(file_path)
        variables = VARIABLE_PATTERN.findall(text)

        result = []
        seen = set()

        for variable in variables:
            if variable not in seen:
                seen.add(variable)
                result.append(variable)

        return result

    @classmethod
    def render_docx(cls, *, template_path: str, output_path: str, values: dict):
        doc = DocxTemplate(template_path)
        doc.render(values)
        doc.save(output_path)
        cls.normalize_rendered_value_styles(output_path, values)

    @classmethod
    def normalize_rendered_value_styles(cls, file_path: str, values: dict):
        value_texts = [
            str(value).strip()
            for value in (values or {}).values()
            if str(value or "").strip()
        ]

        if not value_texts:
            return

        doc = DocxDocument(file_path)
        changed = False

        for paragraph in cls.iter_all_paragraphs(doc):
            for run in paragraph.runs:
                if not run.text:
                    continue

                if any(value in run.text for value in value_texts):
                    run.font.color.rgb = RGBColor(0, 0, 0)
                    run.font.highlight_color = None
                    changed = True

        if changed:
            doc.save(file_path)

    @classmethod
    def iter_all_paragraphs(cls, doc):
        yield from doc.paragraphs

        for table in doc.tables:
            yield from cls.iter_table_paragraphs(table)

        for section in doc.sections:
            for header_footer in [
                section.header,
                section.first_page_header,
                section.even_page_header,
                section.footer,
                section.first_page_footer,
                section.even_page_footer,
            ]:
                yield from header_footer.paragraphs

                for table in header_footer.tables:
                    yield from cls.iter_table_paragraphs(table)

    @classmethod
    def iter_table_paragraphs(cls, table):
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs

                for nested_table in cell.tables:
                    yield from cls.iter_table_paragraphs(nested_table)
