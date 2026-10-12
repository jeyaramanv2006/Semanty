from pathlib import Path
from typing import Dict, Optional

from cli.parsers.base import BaseParser
from cli.parsers.docx_parser import DocxParser
from cli.parsers.pdf_parser import PDFParser
from cli.parsers.pptx_parser import PPTXParser
from cli.parsers.text_parser import TextParser


class ParserFactory:
    """Registry and factory for document format parsers."""

    def __init__(self) -> None:
        self._parsers: Dict[str, BaseParser] = {}
        
        pdf = PDFParser()
        docx = DocxParser()
        pptx = PPTXParser()
        text = TextParser()

        self._parsers[".pdf"] = pdf
        self._parsers[".docx"] = docx
        self._parsers[".pptx"] = pptx

        # Text and code formats
        for ext in [
            ".txt", ".md", ".markdown", ".py", ".json", ".csv",
            ".log", ".java", ".c", ".cpp", ".h", ".js", ".ts",
            ".html", ".css", ".yaml", ".yml", ".toml", ".xml",
        ]:
            self._parsers[ext] = text

    def get_parser(self, file_path: Path) -> Optional[BaseParser]:
        """Return the appropriate parser for a file path, or None if unsupported."""
        return self._parsers.get(file_path.suffix.lower())
