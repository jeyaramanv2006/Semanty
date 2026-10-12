import re
from typing import List

from cli.config import DEFAULT_CONFIG, SearchConfig
from cli.models import ChunkMetadata
from cli.parsers.base import ParsedSection


class TextChunker:
    """Chunks parsed document sections into overlapping passages preserving metadata."""

    def __init__(self, config: SearchConfig = DEFAULT_CONFIG):
        self.config = config

    def chunk_sections(self, doc_id: str, sections: List[ParsedSection]) -> List[ChunkMetadata]:
        chunks: List[ChunkMetadata] = []
        global_chunk_idx = 0

        for section in sections:
            section_chunks = self._chunk_text(section.text)
            for sub_idx, chunk_text in enumerate(section_chunks):
                if not chunk_text.strip():
                    continue

                token_matches = re.findall(self.config.tokenizer_regex, chunk_text.lower())
                token_count = len(token_matches)
                if token_count == 0:
                    continue

                chunk_id = f"{doc_id}_c{global_chunk_idx}"
                loc_val = section.location_value
                if len(section_chunks) > 1:
                    loc_val = f"{section.location_value} [part {sub_idx + 1}/{len(section_chunks)}]"

                chunks.append(
                    ChunkMetadata(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        chunk_index=global_chunk_idx,
                        text=chunk_text,
                        location_type=section.location_type,
                        location_value=loc_val,
                        char_length=len(chunk_text),
                        token_count=token_count,
                    )
                )
                global_chunk_idx += 1

        return chunks

    def _chunk_text(self, text: str) -> List[str]:
        text = text.strip()
        if not text:
            return []

        if len(text) <= self.config.chunk_size:
            return [text]

        # Break text into paragraphs or sentences
        paragraphs = re.split(r"(\n{2,}|\n)", text)
        atoms: List[str] = []
        for p in paragraphs:
            if not p:
                continue
            if len(p) <= self.config.chunk_size:
                atoms.append(p)
            else:
                sentences = re.split(r"((?<=[.?!])\s+)", p)
                for s in sentences:
                    if not s:
                        continue
                    if len(s) <= self.config.chunk_size:
                        atoms.append(s)
                    else:
                        words = s.split(" ")
                        curr_word_block: List[str] = []
                        curr_len = 0
                        for w in words:
                            if curr_len + len(w) + 1 > self.config.chunk_size and curr_word_block:
                                atoms.append(" ".join(curr_word_block))
                                curr_word_block = [w]
                                curr_len = len(w)
                            else:
                                curr_word_block.append(w)
                                curr_len += len(w) + 1
                        if curr_word_block:
                            atoms.append(" ".join(curr_word_block))

        # Recombine atoms with target chunk_size and chunk_overlap
        chunks: List[str] = []
        current_chunk: List[str] = []
        current_len = 0

        for atom in atoms:
            atom_len = len(atom)
            if current_len + atom_len > self.config.chunk_size and current_chunk:
                combined = "".join(current_chunk).strip()
                if combined:
                    chunks.append(combined)

                overlap_chunk: List[str] = []
                overlap_len = 0
                for prev in reversed(current_chunk):
                    if overlap_len + len(prev) <= self.config.chunk_overlap:
                        overlap_chunk.insert(0, prev)
                        overlap_len += len(prev)
                    else:
                        break
                current_chunk = overlap_chunk
                current_len = overlap_len

            current_chunk.append(atom)
            current_len += atom_len

        if current_chunk:
            combined = "".join(current_chunk).strip()
            if combined and (not chunks or chunks[-1] != combined):
                chunks.append(combined)

        return chunks
