import mammoth


class DocxPreviewService:
    @classmethod
    def convert_docx_to_html(cls, file_path: str) -> str:
        with open(file_path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
            return result.value