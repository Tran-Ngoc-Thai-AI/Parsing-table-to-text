
from pathlib import Path
from html import escape
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter


class DocxProcessor:
    """
    Process one DOCX file.

    Flow:
        DOCX
        -> extract tables using python-docx
        -> convert each extracted table to HTML
        -> Docling: HTML -> Markdown
        -> Markdown -> Semantic Text
        -> replace original tables with Semantic Text
        -> save DOCX
    """

    def __init__(self, settings_path=Path("local.settings.json")):
        # Giữ tham số settings_path để không ảnh hưởng code đang khởi tạo class.
        # Không còn sử dụng Azure OpenAI.
        self.converter = DocumentConverter()

    # ---------------------------------------------------------
    # 1. LOAD DOCUMENT
    # ---------------------------------------------------------

    def load_document(self, input_path):
        input_path = Path(input_path)

        if not input_path.exists():
            raise FileNotFoundError(f"File not found: {input_path}")

        if input_path.suffix.lower() != ".docx":
            raise ValueError("Input file must be a DOCX file.")

        return Document(input_path)

    # ---------------------------------------------------------
    # 2. DETECT TABLES
    # ---------------------------------------------------------

    def detect_tables(self, doc):
        tables_need_docling = []
        tables_skipped = []

        for table_index, table in enumerate(doc.tables):
            rows = [
                [
                    cell.text.strip()
                    for cell in row.cells
                ]
                for row in table.rows
            ]

            has_content = any(
                value
                for row in rows
                for value in row
            )

            if len(rows) >= 2 and has_content:
                tables_need_docling.append(table_index)
            else:
                tables_skipped.append(table_index)

        return tables_need_docling, tables_skipped

    # ---------------------------------------------------------
    # 3. EXTRACT TABLE -> HTML
    # ---------------------------------------------------------

    def table_to_html(self, table):
        """
        Extract only one table and convert it to HTML.

        Preserve basic horizontal and vertical merged-cell
        information through colspan and rowspan.
        """

        grid = table._tbl.tblGrid
        total_columns = len(grid.gridCol_lst)

        if total_columns == 0:
            total_columns = max(
                (len(row.cells) for row in table.rows),
                default=0
            )

        active_vertical_merges = {}
        html_rows = []

        for row in table.rows:
            row_cells = []
            column_index = 0

            for tc in row._tr.tc_lst:
                tc_pr = tc.tcPr

                # Horizontal merge: gridSpan
                colspan = 1

                if tc_pr is not None and tc_pr.gridSpan is not None:
                    colspan = int(tc_pr.gridSpan.val)

                # Vertical merge: vMerge
                vmerge_value = None

                if tc_pr is not None and tc_pr.vMerge is not None:
                    vmerge_value = tc_pr.vMerge.val

                cell_text = "\n".join(
                    paragraph.text.strip()
                    for paragraph in tc.xpath("./w:p")
                    if paragraph.text.strip()
                )

                cell_text = escape(cell_text).replace("\n", "<br>")

                if vmerge_value is not None and str(vmerge_value) == "continue":
                    origin = active_vertical_merges.get(column_index)

                    if origin is not None:
                        origin["rowspan"] += 1

                    column_index += colspan
                    continue

                cell = {
                    "text": cell_text,
                    "colspan": colspan,
                    "rowspan": 1,
                }

                if vmerge_value is not None:
                    for col in range(column_index, column_index + colspan):
                        active_vertical_merges[col] = cell
                else:
                    for col in range(column_index, column_index + colspan):
                        active_vertical_merges.pop(col, None)

                row_cells.append(cell)
                column_index += colspan

            html_rows.append(row_cells)

        html = [
            "<html>",
            "<body>",
            "<table border='1'>",
        ]

        for row_cells in html_rows:
            html.append("<tr>")

            for cell in row_cells:
                attrs = []

                if cell["colspan"] > 1:
                    attrs.append(f'colspan="{cell["colspan"]}"')

                if cell["rowspan"] > 1:
                    attrs.append(f'rowspan="{cell["rowspan"]}"')

                attr_text = " " + " ".join(attrs) if attrs else ""

                html.append(
                    f"<td{attr_text}>{cell['text']}</td>"
                )

            html.append("</tr>")

        html.extend([
            "</table>",
            "</body>",
            "</html>",
        ])

        return "\n".join(html)

    def prepare_tables_for_docling(self, doc, tables_need_docling):
        tables_for_docling = []

        for table_index in tables_need_docling:
            table = doc.tables[table_index]

            table_html = self.table_to_html(table)

            tables_for_docling.append({
                "table_index": table_index,
                "html": table_html,
            })

        return tables_for_docling

    # ---------------------------------------------------------
    # 4. DOCLING: HTML -> MARKDOWN
    # ---------------------------------------------------------

    def convert_table_to_markdown(self, table_html):
        result = self.converter.convert_string(
            content=table_html,
            format=InputFormat.HTML,
            name="extracted_table.html",
        )

        if result.document is None:
            raise ValueError("Docling could not convert the extracted table.")

        markdown = result.document.export_to_markdown()

        if not markdown or not markdown.strip():
            raise ValueError("Docling returned empty Markdown.")

        return markdown.strip()


    def reconstruct_tables(self, tables_for_docling):
        reconstructed_tables = []

        for table_item in tables_for_docling:
            markdown = self.convert_table_to_markdown(
                table_item["html"]
            )

            try:
                semantic_text = self.markdown_to_semantic_text(markdown)

                if not semantic_text or not semantic_text.strip():
                    raise ValueError("Semantic Text is empty.")

            except Exception as e:
                print("\n" + "=" * 80)
                print("TABLE PROCESSING ERROR")
                print(f"Table index: {table_item['table_index']}")
                print(f"Error: {e}")

                print("\n--- INPUT HTML ---")
                print(table_item["html"])

                print("\n--- DOCLING MARKDOWN ---")
                print(markdown)

                print("\n" + "=" * 80)

                raise

            reconstructed_tables.append({
                "table_index": table_item["table_index"],
                "markdown": markdown,
                "semantic_text": semantic_text,
            })

        return reconstructed_tables


    # ---------------------------------------------------------
    # 5. MARKDOWN -> SEMANTIC TEXT
    # ---------------------------------------------------------

    # def extract_markdown_table(self, markdown):
    #     """
    #     Extract Markdown table rows.
    #     """

    #     table_lines = []

    #     for line in markdown.splitlines():
    #         line = line.strip()

    #         if line.startswith("|") and line.endswith("|"):
    #             table_lines.append(line)

    #     rows = []

    #     for line in table_lines:
    #         cells = [
    #             cell.strip()
    #             for cell in line.strip("|").split("|")
    #         ]

    #         # Ignore Markdown separator row
    #         is_separator = all(
    #             re.fullmatch(r":?-{3,}:?", cell.replace(" ", ""))
    #             for cell in cells
    #         )

    #         if not is_separator:
    #             rows.append(cells)

    #     return rows

    def extract_markdown_table(self, markdown):
        table_lines = []

        for line in markdown.splitlines():
            line = line.strip()

            if "|" not in line:
                continue

            if line.startswith("|"):
                line = line[1:]

            if line.endswith("|"):
                line = line[:-1]

            cells = [cell.strip() for cell in line.split("|")]

            if len(cells) >= 2:
                table_lines.append(cells)

        rows = []

        for cells in table_lines:
            is_separator = all(
                re.fullmatch(r":?-{3,}:?", cell.replace(" ", ""))
                for cell in cells
            )

            if not is_separator:
                rows.append(cells)

        return rows


    # def markdown_to_semantic_text(self, markdown):
    #     """
    #     Convert Markdown table into structured Semantic Text.

    #     Output:
    #         **Block 1 — Tổng Giám đốc**

    #         - **Tên chức danh:** Tổng Giám đốc
    #         - **Tên chức danh tiếng Anh:** Chief Executive Officer
    #         - **Phân luồng:** Kinh doanh trực tiếp
    #         - **Phân loại:** Nhân sự quản lý
    #     """

    #     rows = self.extract_markdown_table(markdown)

    #     if len(rows) < 2:
    #         return markdown.strip()

    #     headers = [header.strip() for header in rows[0]]

    #     # Find the entity column
    #     entity_column = next(
    #         (
    #             index
    #             for index, header in enumerate(headers)
    #             if header.lower() in [
    #                 "tên chức danh",
    #                 "tên",
    #                 "chức danh",
    #                 "tên đơn vị",
    #                 "tên phòng ban",
    #             ]
    #         ),
    #         0,
    #     )

    #     blocks = []

    #     for row in rows[1:]:
    #         # Normalize row length
    #         row = row + [""] * (len(headers) - len(row))

    #         entity_name = (
    #             row[entity_column].strip()
    #             if entity_column < len(row)
    #             else ""
    #         )

    #         if not entity_name:
    #             continue

    #         block_lines = [
    #             f"**Block {len(blocks) + 1} — {entity_name}**"
    #         ]

    #         for index, value in enumerate(row):
    #             value = value.strip()

    #             if not value:
    #                 continue

    #             header = (
    #                 headers[index]
    #                 if index < len(headers)
    #                 else f"Column {index + 1}"
    #             )

    #             block_lines.append(
    #                 f"- **{header}:** {value}"
    #             )

    #         blocks.append("\n\n".join(block_lines))

    #     return "\n\n---\n\n".join(blocks)

    
    def markdown_to_semantic_text(self, markdown):
        """
        Convert Markdown table into structured Semantic Text.

        Supports merged headers such as:
        'Bộ máy Tên chức danh trực thuộc'

        Expected output:
            **Block 1 — Chuyên gia Thúc đẩy bán khách hàng doanh nghiệp**

            - **Bộ máy:** Bộ phận Thúc đẩy bán
            - **Tên chức danh trực thuộc:** Chuyên gia Thúc đẩy bán khách hàng doanh nghiệp
            ...
        """

        rows = self.extract_markdown_table(markdown)

        if len(rows) < 2:
            return markdown.strip()

        headers = [
            re.sub(r"\s+", " ", header).strip()
            for header in rows[0]
        ]

        # -----------------------------------------------------
        # 1. Normalize duplicated merged headers
        # -----------------------------------------------------

        merged_header = "Bộ máy Tên chức danh trực thuộc"

        merged_indexes = [
            i for i, header in enumerate(headers)
            if header.lower() == merged_header.lower()
        ]

        if len(merged_indexes) >= 2:
            headers[merged_indexes[0]] = "Bộ máy"
            headers[merged_indexes[-1]] = "Tên chức danh trực thuộc"

        # -----------------------------------------------------
        # 2. Find entity column
        # -----------------------------------------------------

        entity_candidates = [
            i for i, header in enumerate(headers)
            if "tên chức danh trực thuộc" in header.lower()
            or header.lower() == "tên chức danh"
        ]

        if not entity_candidates:
            entity_candidates = [
                i for i, header in enumerate(headers)
                if header.lower() in [
                    "tên",
                    "chức danh",
                    "tên đơn vị",
                    "tên phòng ban",
                ]
            ]

        if not entity_candidates:
            raise ValueError(
                f"Cannot identify entity column. Headers: {headers}"
            )

        entity_column = entity_candidates[-1]

        # -----------------------------------------------------
        # 3. Generate Semantic Text blocks
        # -----------------------------------------------------

        blocks = []

        for row in rows[1:]:

            # Normalize row length
            row = row[:len(headers)]
            row += [""] * (len(headers) - len(row))

            # Normalize values
            row = [
                re.sub(r"\s+", " ", value).strip()
                for value in row
            ]

            entity_name = row[entity_column]

            if not entity_name:
                continue

            block_lines = [
                f"**Block {len(blocks) + 1} — {entity_name}**"
            ]

            for index, value in enumerate(row):

                if not value:
                    continue

                header = headers[index] or f"Column {index + 1}"

                block_lines.append(
                    f"- **{header}:** {value}"
                )

            blocks.append("\n\n".join(block_lines))

        return "\n\n---\n\n".join(blocks)



    # ---------------------------------------------------------
    # 6. VALIDATE RESULTS
    # ---------------------------------------------------------

    def validate_results(
        self,
        tables_need_docling,
        reconstructed_tables,
    ):
        if len(tables_need_docling) != len(reconstructed_tables):
            raise ValueError(
                "The number of reconstructed tables does not match "
                "the number of input tables."
            )

        expected_indexes = set(tables_need_docling)
        actual_indexes = {
            item["table_index"]
            for item in reconstructed_tables
        }

        if expected_indexes != actual_indexes:
            raise ValueError("Table indexes do not match.")

        for item in reconstructed_tables:
            if not item["semantic_text"].strip():
                raise ValueError(
                    f"Empty Semantic Text at table index "
                    f"{item['table_index']}."
                )

    # ---------------------------------------------------------
    # 7. REPLACE TABLE WITH SEMANTIC TEXT
    # ---------------------------------------------------------

    def insert_paragraph_before_table(self, table, text):
        paragraph_element = OxmlElement("w:p")
        table._tbl.addprevious(paragraph_element)

        paragraph = Paragraph(
            paragraph_element,
            table._parent
        )

        paragraph.add_run(text)

        return paragraph

    def replace_tables(self, doc, reconstructed_tables):
        # Reverse order to avoid changing the indexes
        # of tables that have not been replaced yet.
        for item in sorted(
            reconstructed_tables,
            key=lambda x: x["table_index"],
            reverse=True,
        ):
            table_index = item["table_index"]
            semantic_text = item["semantic_text"]

            table = doc.tables[table_index]

            self.insert_paragraph_before_table(
                table,
                semantic_text
            )

            table._element.getparent().remove(table._element)

    # ---------------------------------------------------------
    # 8. PROCESS
    # ---------------------------------------------------------

    def process(self, input_path, output_path):
        input_path = Path(input_path)
        output_path = Path(output_path)

        # Load DOCX
        doc = self.load_document(input_path)

        # Detect tables
        tables_need_docling, tables_skipped = self.detect_tables(doc)

        if not tables_need_docling:
            output_path.parent.mkdir(
                parents=True,
                exist_ok=True
            )
            doc.save(output_path)

            return {
                "input_path": str(input_path),
                "output_path": str(output_path),
                "tables_processed": 0,
                "tables_skipped": len(tables_skipped),
            }

        # Extract only selected tables
        tables_for_docling = self.prepare_tables_for_docling(
            doc,
            tables_need_docling
        )

        # Docling: HTML -> Markdown
        # Markdown -> Semantic Text
        reconstructed_tables = self.reconstruct_tables(
            tables_for_docling
        )

        # Validate before modifying the DOCX
        self.validate_results(
            tables_need_docling,
            reconstructed_tables
        )

        # Replace original tables
        self.replace_tables(
            doc,
            reconstructed_tables
        )

        # Save output
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        doc.save(output_path)

        return {
            "input_path": str(input_path),
            "output_path": str(output_path),
            "tables_processed": len(reconstructed_tables),
            "tables_skipped": len(tables_skipped),
        }


# ---------------------------------------------------------
# MANUAL TEST
# ---------------------------------------------------------

if __name__ == "__main__":
    processor = DocxProcessor()

    input_file = Path("input/3352.docx")
    output_file = Path("output/3352.docx")

    result = processor.process(
        input_path=input_file,
        output_path=output_file,
    )

    print("\nProcessing completed:")
    print(result)
