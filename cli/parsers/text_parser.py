from pathlib import Path
import re
from typing import List

from cli.parsers.base import BaseParser, ParsedSection


class TextParser(BaseParser):
    """Plaintext, Markdown, and source-code parser using standard library with line tracking."""

    def __init__(self, block_lines: int = 40):
        self.block_lines = block_lines

    def parse(self, file_path: Path) -> List[ParsedSection]:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = file_path.read_text(encoding="latin-1")
            except Exception:
                return []

        ext = file_path.suffix.lower()
        if ext in {".md", ".markdown"}:
            return self._parse_markdown(content)
        else:
            return self._parse_lines(content)

    def _parse_markdown(self, content: str) -> List[ParsedSection]:
        lines = content.splitlines()
        sections: List[ParsedSection] = []
        current_heading = "Header"
        buffer: List[str] = []
        start_line = 1

        for i, line in enumerate(lines, start=1):
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
            if heading_match:
                if buffer:
                    combined = "\n".join(buffer).strip()
                    if combined:
                        sections.append(
                            ParsedSection(
                                text=combined,
                                location_type="heading",
                                location_value=f"Lines {start_line}-{i-1} | {current_heading}",
                            )
                        )
                    buffer.clear()
                current_heading = heading_match.group(2).strip()
                start_line = i
            buffer.append(line)

        if buffer:
            combined = "\n".join(buffer).strip()
            if combined:
                sections.append(
                    ParsedSection(
                        text=combined,
                        location_type="heading",
                        location_value=f"Lines {start_line}-{len(lines)} | {current_heading}",
                    )
                )

        return sections

    def _parse_lines(self, content: str) -> List[ParsedSection]:
        lines = content.splitlines()
        if not lines:
            return []

        sections: List[ParsedSection] = []
        total_lines = len(lines)

        for start_idx in range(0, total_lines, self.block_lines):
            end_idx = min(start_idx + self.block_lines, total_lines)
            chunk_lines = lines[start_idx:end_idx]
            chunk_text = "\n".join(chunk_lines).strip()
            if chunk_text:
                sections.append(
                    ParsedSection(
                        text=chunk_text,
                        location_type="lines",
                        location_value=f"Lines {start_idx + 1}-{end_idx}",
                    )
                )

        return sections
