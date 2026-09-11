"""Document parsers used by the ingestion pipeline."""

import io
import re
import subprocess
import tempfile
from pathlib import PurePath

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


class Parser:
    """Extract normalized text from the document formats supported by the API."""

    _SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".doc"}

    def parse(self, content: bytes, filename: str) -> list[tuple[int, str]]:
        """Return non-empty page text as ``(page_number, text)`` pairs."""
        suffix = PurePath(filename).suffix.lower()
        if suffix not in self._SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(self._SUPPORTED_EXTENSIONS))
            raise ValueError(f"Only {supported} documents are supported")

        if suffix == ".pdf":
            pages = self._parse_pdf(content)
        elif suffix in {".txt", ".md"}:
            pages = [(1, self._decode_text(content))]
        elif suffix == ".docx":
            pages = self._parse_docx(content)
        else:
            pages = [(1, self._parse_doc(content))]

        return [
            (page_number, self._normalize(text))
            for page_number, text in pages
            if self._normalize(text)
        ]

    @staticmethod
    def _parse_pdf(content: bytes) -> list[tuple[int, str]]:
        return [
            (page_number, page.extract_text() or "")
            for page_number, page in enumerate(PdfReader(io.BytesIO(content)).pages, 1)
        ]

    @staticmethod
    def _parse_docx(content: bytes) -> list[tuple[int, str]]:
        document = Document(io.BytesIO(content))
        pages: list[str] = []
        current_page: list[str] = []

        for block in document.element.body.iterchildren():
            if block.tag.endswith("}p"):
                paragraph = Paragraph(block, document)
                current_page.append(paragraph.text)
                if any(
                    break_element.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type")
                    == "page"
                    for break_element in block.iter()
                    if break_element.tag.endswith("}br")
                ):
                    pages.append("\n".join(current_page))
                    current_page = []
            elif block.tag.endswith("}tbl"):
                table = Table(block, document)
                current_page.extend(", ".join(cell.text for cell in row.cells) for row in table.rows)

        if current_page or not pages:
            pages.append("\n".join(current_page))
        return list(enumerate(pages, 1))

    @staticmethod
    def _parse_doc(content: bytes) -> str:
        try:
            with tempfile.NamedTemporaryFile(suffix=".doc") as document_file:
                document_file.write(content)
                document_file.flush()
                result = subprocess.run(
                    ["antiword", document_file.name],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
        except FileNotFoundError as error:
            raise ValueError("Legacy .doc parsing requires antiword in the runtime image") from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr.strip() or "antiword could not read the document"
            raise ValueError(f"Unable to parse .doc document: {detail}") from error
        return result.stdout

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _decode_text(content: bytes) -> str:
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")