from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class ParsedSection:
    """A structured piece of content extracted from a document."""
    text: str
    location_type: str  # "page", "slide", "heading", "lines"
    location_value: str  # e.g., "Page 1", "Slide 4", "Heading: Abstract", "Lines 1-50"


class BaseParser(ABC):
    """Abstract base class for document format parsers."""

    @abstractmethod
    def parse(self, file_path: Path) -> List[ParsedSection]:
        """Parse a document file into structured sections with location metadata."""
        pass
