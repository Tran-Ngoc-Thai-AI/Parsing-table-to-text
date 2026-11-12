
from pathlib import Path
from html import escape
from html.parser import HTMLParser
from pydoc import doc
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter


# =============================================================
# HTML TABLE PARSER
# =============================================================

class TableHTMLParser(HTMLParser):
    """
    Parse HTML table and preserve colspan / rowspan.

    Each cell:
        {
            "text": "...",
            "colspan": 1,
            "rowspan": 1
        }
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.rows = []
        self.current_row = None
        self.current_cell = None
        self.in_table = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "table":
            self.in_table = True

        elif tag == "tr" and self.in_table:
            self.current_row = []

        elif tag in ("td", "th") and self.current_row is not None:
            self.current_cell = {
                "text": "",
                "colspan": int(attrs.get("colspan", 1)),
                "rowspan": int(attrs.get("rowspan", 1)),
            }

        elif tag == "br" and self.current_cell is not None:
            self.current_cell["text"] += "\n"

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self.current_cell is not None:
            self.current_cell["text"] += "\n"

    def handle_data(self, data):
        if self.current_cell is not None:
            self.current_cell["text"] += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.current_cell is not None:
            self.current_cell["text"] = self.current_cell["text"].strip()

            self.current_row.append(self.current_cell)
            self.current_cell = None

        elif tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.rows.append(self.current_row)

            self.current_row = None

        elif tag == "table":
            self.in_table = False


# =============================================================
# DOCX PROCESSOR
# =============================================================

class DocxProcessor:
    """
    Process one DOCX file.

    Flow:
        DOCX
        -> extract tables using python-docx
        -> convert each extracted table to HTML
        -> Docling: HTML -> Markdown
        -> Detect table type
            -> BLOCK: Markdown -> Semantic Text
            -> JOB_DESCRIPTION: Original HTML -> Semantic Text
            -> UNKNOWN: Raise error and print HTML/Markdown
        -> replace original tables with Semantic Text
        -> save DOCX
    """

    BLOCK = "BLOCK"
    JOB_DESCRIPTION = "JOB_DESCRIPTION"
    UNKNOWN = "UNKNOWN"

    JOB_SECTIONS = [
        "MÔ TẢ CHỨC DANH",
        "VAI TRÒ & MỤC TIÊU",
        "THẨM QUYỀN",
        "NHIỆM VỤ TRỌNG TÂM",
    ]

    def __init__(self, settings_path=Path("local.settings.json")):
        # Keep settings_path for backward compatibility.
        # No Azure OpenAI is used.
        self.converter = DocumentConverter()

    # ---------------------------------------------------------
    # COMMON HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def normalize_text(text):
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def normalize_header(text):
        return re.sub(
            r"\s+",
            " ",
            (text or "").strip().lower()
        )

    # ---------------------------------------------------------
    # 1. LOAD DOCUMENT
    # ---------------------------------------------------------

    def load_document(self, input_path):
        input_path = Path(input_path)

        if not input_path.exists():
            raise FileNotFoundError(
                f"File not found: {input_path}"
            )

        if input_path.suffix.lower() != ".docx":
            raise ValueError(
                "Input file must be a DOCX file."
            )

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
        Extract one DOCX table and convert it to HTML.

        Preserve:
            - Horizontal merge: colspan
            - Vertical merge: rowspan
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

                # ---------------------------------------------
                # Horizontal merge: gridSpan
                # ---------------------------------------------

                colspan = 1

                if (
                    tc_pr is not None
                    and tc_pr.gridSpan is not None
                ):
                    colspan = int(tc_pr.gridSpan.val)

                # ---------------------------------------------
                # Vertical merge: vMerge
                # ---------------------------------------------

                vmerge_value = None

                if (
                    tc_pr is not None
                    and tc_pr.vMerge is not None
                ):
                    # In Word XML:
                    # <w:vMerge w:val="restart"/> = start
                    # <w:vMerge/> = continue

                    vmerge_value = (
                        tc_pr.vMerge.val or "continue"
                    )

                # ---------------------------------------------
                # Extract cell text
                # ---------------------------------------------

                paragraphs = tc.xpath("./w:p")

                cell_text = "\n".join(
                    paragraph.text.strip()
                    for paragraph in paragraphs
                    if paragraph.text.strip()
                )

                cell_text = escape(cell_text).replace(
                    "\n",
                    "<br>"
                )

                # ---------------------------------------------
                # Continuation of vertical merge
                # ---------------------------------------------

                if vmerge_value == "continue":
                    origin = active_vertical_merges.get(
                        column_index
                    )

                    if origin is not None:
                        origin["rowspan"] += 1

                    column_index += colspan
                    continue

                # ---------------------------------------------
                # New cell
                # ---------------------------------------------

                cell = {
                    "text": cell_text,
                    "colspan": colspan,
                    "rowspan": 1,
                }

                if vmerge_value == "restart":
                    for col in range(
                        column_index,
                        column_index + colspan
                    ):
                        active_vertical_merges[col] = cell

                else:
                    for col in range(
                        column_index,
                        column_index + colspan
                    ):
                        active_vertical_merges.pop(col, None)

                row_cells.append(cell)
                column_index += colspan

            html_rows.append(row_cells)

        # ---------------------------------------------
        # Generate HTML
        # ---------------------------------------------

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
                    attrs.append(
                        f'colspan="{cell["colspan"]}"'
                    )

                if cell["rowspan"] > 1:
                    attrs.append(
                        f'rowspan="{cell["rowspan"]}"'
                    )

                attr_text = (
                    " " + " ".join(attrs)
                    if attrs
                    else ""
                )

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

    def prepare_tables_for_docling(
        self,
        doc,
        tables_need_docling
    ):
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
            raise ValueError(
                "Docling could not convert the extracted table."
            )

        markdown = result.document.export_to_markdown()

        if not markdown or not markdown.strip():
            raise ValueError(
                "Docling returned empty Markdown."
            )

        return markdown.strip()

    # ---------------------------------------------------------
    # 5. EXTRACT MARKDOWN TABLE
    # ---------------------------------------------------------

    def extract_markdown_table(self, markdown):
        """
        Extract Markdown table rows.

        Ignore separator rows.
        """

        table_lines = []

        for line in markdown.splitlines():
            line = line.strip()

            if "|" not in line:
                continue

            if line.startswith("|"):
                line = line[1:]

            if line.endswith("|"):
                line = line[:-1]

            cells = [
                cell.strip()
                for cell in line.split("|")
            ]

            if len(cells) >= 2:
                table_lines.append(cells)

        rows = []

        for cells in table_lines:
            is_separator = all(
                re.fullmatch(
                    r":?-{3,}:?",
                    cell.replace(" ", "")
                )
                for cell in cells
            )

            if not is_separator:
                rows.append(cells)

        return rows

    # ---------------------------------------------------------
    # 6. DETECT TABLE TYPE
    # ---------------------------------------------------------

    def detect_table_type(self, html: str, markdown: str) -> str:
        normalized = self.normalize_text(html).upper()

        # 1. JOB_DESCRIPTION - ưu tiên cao nhất
        job_sections = [
            "MÔ TẢ CHỨC DANH",
            "VAI TRÒ & MỤC TIÊU",
            "THẨM QUYỀN",
            "NHIỆM VỤ TRỌNG TÂM",
            "NHIỆM VỤ KHÁC",
            "YÊU CẦU TRÌNH ĐỘ & NĂNG LỰC",
            "YÊU CẦU TRÌNH ĐỘ",
            "YÊU CẦU NĂNG LỰC",
        ]

        job_count = sum(
            1 for section in job_sections
            if section in normalized
        )

        if job_count >= 1:
            return "JOB_DESCRIPTION"

        # 2. BLOCK
        block_headers = [
            "TÊN CHỨC DANH",
            "TÊN CHỨC DANH TIẾNG ANH",
            "TÊN CHỨC DANH TRỰC THUỘC",
            "PHÂN LUỒNG",
            "PHÂN LOẠI",
        ]

        block_count = sum(
            1 for header in block_headers
            if header in normalized
        )

        if block_count >= 2:
            return "BLOCK"

        # 3. LIST - tiêu đề đặc trưng
        if "GIÁ TRỊ CỐT LÕI" in normalized:
            return "LIST"

        # 4. LIST - cấu trúc số thứ tự + nội dung
        parser = TableHTMLParser()
        parser.feed(html)

        numbered_rows = 0

        for row in parser.rows:
            cells = [
                self.normalize_text(cell["text"])
                for cell in row
                if self.normalize_text(cell["text"])
            ]

            if len(cells) < 2 or len(cells) % 2 != 0:
                continue

            if all(
                re.match(r"^\d+\.?$", cells[i])
                for i in range(0, len(cells), 2)
            ):
                numbered_rows += 1

        if numbered_rows >= 1:
            return "LIST"

        return "UNKNOWN"

    # ---------------------------------------------------------
    # 7. BLOCK: MARKDOWN -> SEMANTIC TEXT
    # ---------------------------------------------------------

    def markdown_to_semantic_text(self, markdown):
        """
        Convert Markdown table into structured Semantic Text.

        Supports merged headers such as:
            Bộ máy Tên chức danh trực thuộc

        Expected output:
            **Block 1 — Chuyên gia ...**

            - **Bộ máy:** ...
            - **Tên chức danh trực thuộc:** ...
        """

        rows = self.extract_markdown_table(markdown)

        if len(rows) < 2:
            raise ValueError(
                "BLOCK table does not contain enough Markdown rows."
            )

        headers = [
            self.normalize_text(header)
            for header in rows[0]
        ]

        # ---------------------------------------------
        # 1. Normalize duplicated merged headers
        # ---------------------------------------------

        merged_header = "Bộ máy Tên chức danh trực thuộc"

        merged_indexes = [
            index
            for index, header in enumerate(headers)
            if header.lower() == merged_header.lower()
        ]

        if len(merged_indexes) >= 2:
            headers[merged_indexes[0]] = "Bộ máy"
            headers[merged_indexes[-1]] = (
                "Tên chức danh trực thuộc"
            )

        # ---------------------------------------------
        # 2. Find entity column
        # ---------------------------------------------

        entity_candidates = [
            index
            for index, header in enumerate(headers)
            if (
                "tên chức danh trực thuộc" in header.lower()
                or header.lower() == "tên chức danh"
            )
        ]

        if not entity_candidates:
            entity_candidates = [
                index
                for index, header in enumerate(headers)
                if header.lower() in [
                    "tên",
                    "chức danh",
                    "tên đơn vị",
                    "tên phòng ban",
                ]
            ]

        if not entity_candidates:
            raise ValueError(
                "Cannot identify entity column. "
                f"Headers: {headers}"
            )

        entity_column = entity_candidates[-1]

        # ---------------------------------------------
        # 3. Generate Semantic Text blocks
        # ---------------------------------------------

        blocks = []

        for row in rows[1:]:

            row = row[:len(headers)]
            row += [""] * (len(headers) - len(row))

            row = [
                self.normalize_text(value)
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

                header = (
                    headers[index]
                    or f"Column {index + 1}"
                )

                block_lines.append(
                    f"- **{header}:** {value}"
                )

            blocks.append("\n".join(block_lines))

        if not blocks:
            raise ValueError(
                "BLOCK table did not produce any Semantic Text blocks."
            )

        return "\n\n---\n\n".join(blocks)

    # ---------------------------------------------------------
    # 8. JOB DESCRIPTION: HTML -> SEMANTIC TEXT
    # ---------------------------------------------------------

    def html_to_list_text(self, html: str) -> str:
        parser = TableHTMLParser()
        parser.feed(html)

        output = []

        for row in parser.rows:
            cells = [
                self.normalize_text(cell["text"])
                for cell in row
                if cell["text"].strip()
            ]

            if not cells:
                continue

            # Tiêu đề section
            if len(cells) == 1:
                text = cells[0]

                if text.isupper():
                    output.append(f"\n## {text}")
                else:
                    output.append(text)

                continue

            # Danh sách dạng số thứ tự + nội dung
            if len(cells) % 2 == 0:
                pairs = []

                for i in range(0, len(cells), 2):
                    number = cells[i].strip()
                    content = cells[i + 1].strip()

                    if re.match(r"^\d+\.?$", number):
                        pairs.append(f"{number} {content}")
                    else:
                        pairs = []
                        break

                if pairs:
                    output.extend(pairs)
                    continue

            # Các dòng không nhận diện được cấu trúc:
            # Giữ nguyên thứ tự nội dung, không tự suy luận.
            output.append(" | ".join(cells))

        return "\n".join(output).strip()

    def html_to_job_description_text(self, html):
        """
        Convert Job Description HTML into Semantic Text.

        Preserve original cell boundaries and merge information.

        Does not use Docling Markdown as the structural source,
        because Markdown may duplicate merged-cell content.
        """

        parser = TableHTMLParser()
        parser.feed(html)

        if not parser.rows:
            raise ValueError(
                "Cannot parse Job Description HTML table."
            )

        output = []
        current_section = None

        section_names = {
            self.normalize_text(section).upper()
            for section in self.JOB_SECTIONS
        }

        for row in parser.rows:

            cells = [
                cell
                for cell in row
                if self.normalize_text(cell["text"])
            ]

            if not cells:
                continue

            # ---------------------------------------------
            # Single cell: title, section or content
            # ---------------------------------------------

            if len(cells) == 1:
                cell = cells[0]

                text = self.normalize_text(
                    cell["text"]
                )

                normalized = text.upper()

                is_full_width = (
                    cell["colspan"] > 1
                    or cell["rowspan"] > 1
                )

                if normalized in section_names:
                    current_section = normalized

                    output.append(
                        f"\n## {normalized}"
                    )

                elif (
                    normalized == "MÔ TẢ CHỨC DANH"
                    or (
                        is_full_width
                        and normalized in section_names
                    )
                ):
                    output.append(
                        f"\n## {normalized}"
                    )

                else:
                    output.append(text)

                continue

            # ---------------------------------------------
            # Multiple cells
            # ---------------------------------------------

            parts = [
                self.normalize_text(cell["text"])
                for cell in cells
            ]

            # ---------------------------------------------
            # Detect label-value pairs
            # ---------------------------------------------

            is_label_value_row = (
                len(cells) >= 2
                and len(cells) % 2 == 0
            )

            if is_label_value_row:
                for index in range(0, len(cells), 2):
                    label = parts[index]
                    value = parts[index + 1]

                    is_label = (
                        label.startswith("-")
                        or label.endswith(":")
                        or label.endswith("：")
                    )

                    if not is_label:
                        is_label_value_row = False
                        break

            if is_label_value_row:
                for index in range(0, len(cells), 2):
                    label = parts[index]
                    value = parts[index + 1]

                    label = label.lstrip("-").strip()
                    label = label.rstrip(":：").strip()

                    if value:
                        output.append(
                            f"- **{label}:** {value}"
                        )
                    else:
                        output.append(
                            f"- **{label}:**"
                        )

            else:
                # Preserve original content without guessing
                # relationships between merged cells.
                output.append(
                    " | ".join(parts)
                )

        semantic_text = "\n".join(output).strip()

        if not semantic_text:
            raise ValueError(
                "Job Description Semantic Text is empty."
            )

        return semantic_text

    # ---------------------------------------------------------
    # 9. CONVERT TABLE BY TYPE
    # ---------------------------------------------------------

    def convert_table_to_semantic_text(
        self,
        table_type: str,
        html: str,
        markdown: str
    ) -> str:

        if table_type == "JOB_DESCRIPTION":
            return self.html_to_job_description_text(html)

        elif table_type == "BLOCK":
            return self.markdown_to_semantic_text(markdown)

        elif table_type == "LIST":
            return self.html_to_list_text(html)

        raise ValueError(f"Unsupported table type: {table_type}")

    # ---------------------------------------------------------
    # 10. RECONSTRUCT TABLES
    # ---------------------------------------------------------

    def reconstruct_tables(self, tables_for_docling):
        reconstructed_tables = []

        for table_item in tables_for_docling:

            table_index = table_item["table_index"]
            html = table_item["html"]
            markdown = ""

            try:
                # -----------------------------------------
                # Step 1. HTML -> Markdown
                # -----------------------------------------

                markdown = self.convert_table_to_markdown(
                    html
                )

                # -----------------------------------------
                # Step 2. Detect type -> Semantic Text
                # -----------------------------------------
                table_type = self.detect_table_type(
                    html=html,
                    markdown=markdown
                )

                print(f"[TABLE {table_index}] Detected type: {table_type}")

                semantic_text = (
                    self.convert_table_to_semantic_text(
                        table_type=table_type,
                        html=html,
                        markdown=markdown
                    )
                )

                if (
                    not semantic_text
                    or not semantic_text.strip()
                ):
                    raise ValueError(
                        "Semantic Text is empty."
                    )

                reconstructed_tables.append({
                    "table_index": table_index,
                    "markdown": markdown,
                    "semantic_text": semantic_text,
                })

                print(
                    f"Table {table_index}: "
                    f"processed successfully."
                )

            except Exception as e:

                print("\n" + "=" * 80)
                print("TABLE PROCESSING ERROR")
                print(f"Table index: {table_index}")
                print(f"Error: {e}")

                print("\n--- INPUT HTML ---")
                print(html)

                print("\n--- DOCLING MARKDOWN ---")
                print(markdown or "(Markdown unavailable)")

                print("=" * 80)

                raise

        return reconstructed_tables

    # ---------------------------------------------------------
    # 11. VALIDATE RESULTS
    # ---------------------------------------------------------

    def validate_results(
        self,
        tables_need_docling,
        reconstructed_tables
    ):
        if len(tables_need_docling) != len(
            reconstructed_tables
        ):
            raise ValueError(
                "The number of reconstructed tables does not "
                "match the number of input tables."
            )

        expected_indexes = set(tables_need_docling)

        actual_indexes = {
            item["table_index"]
            for item in reconstructed_tables
        }

        if expected_indexes != actual_indexes:
            raise ValueError(
                "Table indexes do not match."
            )

        for item in reconstructed_tables:
            if not item["semantic_text"].strip():
                raise ValueError(
                    f"Empty Semantic Text at table index "
                    f"{item['table_index']}."
                )

    # ---------------------------------------------------------
    # 12. REPLACE TABLE WITH SEMANTIC TEXT
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


    def replace_tables(
        self,
        doc,
        reconstructed_tables
    ):
        # Reverse order to avoid changing the indexes
        # of tables that have not been replaced yet.

        for item in sorted(
            reconstructed_tables,
            key=lambda x: x["table_index"],
            reverse=True
        ):
            table_index = item["table_index"]
            semantic_text = item["semantic_text"]

            table = doc.tables[table_index]

            self.insert_paragraph_before_table(
                table,
                semantic_text
            )

            table._element.getparent().remove(
                table._element
            )

    # ---------------------------------------------------------
    # 13. PROCESS
    # ---------------------------------------------------------

    def process(self, input_path, output_path):
        input_path = Path(input_path)
        output_path = Path(output_path)

        # ---------------------------------------------
        # Step 1. Load DOCX
        # ---------------------------------------------

        doc = self.load_document(input_path)

        # ---------------------------------------------
        # Step 2. Detect tables
        # ---------------------------------------------

        (
            tables_need_docling,
            tables_skipped
        ) = self.detect_tables(doc)

        print(f"Tables selected: {len(tables_need_docling)}")
        print(f"Tables skipped: {len(tables_skipped)}")

        # ---------------------------------------------
        # No tables to process
        # ---------------------------------------------

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

        # ---------------------------------------------
        # Step 3. Extract selected tables -> HTML
        # ---------------------------------------------

        tables_for_docling = (
            self.prepare_tables_for_docling(
                doc,
                tables_need_docling
            )
        )

        # ---------------------------------------------
        # Step 4. Docling + Semantic Text
        # ---------------------------------------------

        reconstructed_tables = self.reconstruct_tables(
            tables_for_docling
        )

        # ---------------------------------------------
        # Step 5. Validate before modifying DOCX
        # ---------------------------------------------

        self.validate_results(
            tables_need_docling,
            reconstructed_tables
        )

        # ---------------------------------------------
        # Step 6. Replace original tables
        # ---------------------------------------------

        self.replace_tables(
            doc,
            reconstructed_tables
        )

        # ---------------------------------------------
        # Step 7. Save output
        # ---------------------------------------------

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


# =============================================================
# MANUAL TEST
# =============================================================

if __name__ == "__main__":

    processor = DocxProcessor()

    input_file = Path("input/test.docx")
    output_file = Path("output/test.docx")

    result = processor.process(
        input_path=input_file,
        output_path=output_file
    )

    print("\nProcessing completed:")
    print(result)
