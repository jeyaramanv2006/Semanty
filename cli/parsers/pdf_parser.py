from pathlib import Path
from typing import List
import pymupdf

from cli.parsers.base import BaseParser, ParsedSection


class PDFParser(BaseParser):
    """PDF parser using PyMuPDF (fitz) with page-level metadata tracking."""

    def parse(self, file_path: Path) -> List[ParsedSection]:
        sections: List[ParsedSection] = []
        doc = pymupdf.open(str(file_path))
        try:
            for page_index in range(len(doc)):
                page = doc[page_index]
                text = page.get_text("text").strip()
                if text:
                    sections.append(
                        ParsedSection(
                            text=text,
                            location_type="page",
                            location_value=f"Page {page_index + 1}",
                        )
                    )
        finally:
            doc.close()
        return sections
