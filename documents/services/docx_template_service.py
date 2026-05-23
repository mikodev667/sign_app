import re

from docx import Document as DocxDocument
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