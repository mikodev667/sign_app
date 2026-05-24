from bs4 import BeautifulSoup
from docx import Document as DocxDocument


class HtmlToDocxService:
    @classmethod
    def render_html_to_docx(cls, html: str, output_path: str):
        soup = BeautifulSoup(html or "", "html.parser")
        doc = DocxDocument()

        body_elements = soup.find_all(["h1", "h2", "h3", "p", "div", "table"], recursive=True)

        for element in body_elements:
            if element.name == "h1":
                doc.add_heading(element.get_text(" ", strip=True), level=1)

            elif element.name == "h2":
                doc.add_heading(element.get_text(" ", strip=True), level=2)

            elif element.name == "h3":
                doc.add_heading(element.get_text(" ", strip=True), level=3)

            elif element.name in ["p", "div"]:
                text = element.get_text(" ", strip=True)
                if text:
                    doc.add_paragraph(text)

            elif element.name == "table":
                rows = element.find_all("tr")
                if not rows:
                    continue

                first_row_cells = rows[0].find_all(["td", "th"])
                if not first_row_cells:
                    continue

                table = doc.add_table(
                    rows=len(rows),
                    cols=len(first_row_cells)
                )

                table.style = "Table Grid"

                for row_index, row in enumerate(rows):
                    cells = row.find_all(["td", "th"])

                    for cell_index, cell in enumerate(cells):
                        if cell_index < len(table.rows[row_index].cells):
                            table.rows[row_index].cells[cell_index].text = cell.get_text(" ", strip=True)

        doc.save(output_path)