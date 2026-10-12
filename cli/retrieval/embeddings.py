from typing import List, Union
import numpy as np
from sentence_transformers import SentenceTransformer

from cli.config import DEFAULT_CONFIG, SearchConfig


class EmbeddingGenerator:
    """Generates L2-normalized 384-dimensional embeddings using Sentence-Transformers."""

    def __init__(self, config: SearchConfig = DEFAULT_CONFIG):
        self.config = config
        self._model: Union[SentenceTransformer, None] = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy-load SentenceTransformer model."""
        if self._model is None:
            self._model = SentenceTransformer(self.config.embedding_model_name)
        return self._model

    def encode(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 64,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """
        Encode text or list of texts into L2-normalized float32 vectors.
        Returns array of shape (N, 384).
        """
        if isinstance(texts, str):
            texts = [texts]

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress_bar,
            normalize_embeddings=self.config.normalize_embeddings,
            convert_to_numpy=True,
        )

        return embeddings.astype(np.float32)
