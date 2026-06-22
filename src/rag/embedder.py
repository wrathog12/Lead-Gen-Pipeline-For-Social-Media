"""
Embedder — Converts scheme descriptions to dense vectors and manages the FAISS index.

Uses sentence-transformers (all-MiniLM-L6-v2) to generate 384-dimensional
embeddings for the BCI scheme dataset. Embeddings are stored in a FAISS
index on disk so they only need to be computed ONCE.

Index lifecycle:
  1. build_index()  — Reads the scheme JSON, embeds all vector_descriptions,
                       saves FAISS index + ID mapping to data/vector_store/
  2. load_index()   — Loads the pre-built index from disk (fast, no re-embedding)
  3. search()       — Embeds a query and searches the FAISS index for top-K matches

The index is built once and reused across all pipeline runs.
"""

import os
import json
import numpy as np
import faiss
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger("embedder")

# ── Defaults ─────────────────────────────────────────────────────
DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_SCHEME_PATH = os.path.join("data", "raw", "icici_scheme_dataset.json")
DEFAULT_INDEX_DIR = os.path.join("data", "vector_store")
INDEX_FILENAME = "schemes.index"
METADATA_FILENAME = "schemes_metadata.json"


class SchemeEmbedder:
    """Generates, stores, and searches embeddings for the BCI scheme dataset."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        index_dir: str = DEFAULT_INDEX_DIR,
    ):
        self.model_name = model_name
        self.index_dir = index_dir
        self._model = None                       # Lazy-loaded sentence-transformer
        self._index: Optional[faiss.Index] = None # FAISS index (loaded or built)
        self._schemes: List[Dict[str, Any]] = []  # Scheme metadata parallel to index rows
        self._dimension: int = 384                # all-MiniLM-L6-v2 output dimension

    # ── Lazy model loading ───────────────────────────────────────

    def _get_model(self):
        """Load the sentence-transformer model on first use."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("loading_model", model=self.model_name)
            self._model = SentenceTransformer(self.model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info("model_loaded", dimension=self._dimension)
        return self._model

    # ── Embedding ────────────────────────────────────────────────

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        Convert a list of text strings to dense vector embeddings.

        Returns:
            np.ndarray of shape (len(texts), dimension), dtype float32
        """
        model = self._get_model()
        embeddings = model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,  # L2 normalize for cosine similarity via inner product
        )
        return embeddings.astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed a single query string for search.

        Returns:
            np.ndarray of shape (1, dimension), dtype float32
        """
        return self.embed_texts([query])

    # ── Index building (one-time) ────────────────────────────────

    def build_index(
        self,
        scheme_path: str = DEFAULT_SCHEME_PATH,
        force_rebuild: bool = False,
    ) -> None:
        """
        Build and save a FAISS index from the scheme dataset.

        Reads icici_scheme_dataset.json, embeds all vector_description fields,
        creates a FAISS IndexFlatIP (inner product = cosine similarity since
        vectors are L2-normalized), and saves both the index and scheme metadata
        to disk.

        Args:
            scheme_path: Path to the scheme JSON file.
            force_rebuild: If True, rebuilds even if index already exists on disk.
        """
        index_path = os.path.join(self.index_dir, INDEX_FILENAME)
        metadata_path = os.path.join(self.index_dir, METADATA_FILENAME)

        # Skip if already built (unless forced)
        if not force_rebuild and os.path.exists(index_path) and os.path.exists(metadata_path):
            logger.info("index_already_exists", path=index_path)
            self.load_index()
            return

        # Load scheme data
        logger.info("building_index", scheme_path=scheme_path)

        with open(scheme_path, "r", encoding="utf-8") as f:
            schemes = json.load(f)

        if not schemes:
            raise ValueError(f"No schemes found in {scheme_path}")

        # Extract descriptions for embedding
        descriptions = [s["vector_description"] for s in schemes]
        logger.info("embedding_schemes", count=len(descriptions))

        # Generate embeddings
        embeddings = self.embed_texts(descriptions)

        # Build FAISS index (IndexFlatIP = brute-force inner product)
        # Since vectors are L2-normalized, inner product == cosine similarity
        index = faiss.IndexFlatIP(self._dimension)
        index.add(embeddings)

        # Save to disk
        os.makedirs(self.index_dir, exist_ok=True)
        faiss.write_index(index, index_path)

        # Save scheme metadata alongside index
        # (so we can map FAISS row indices back to scheme objects)
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(schemes, f, indent=2, ensure_ascii=False)

        # Keep in memory
        self._index = index
        self._schemes = schemes

        logger.info(
            "index_built",
            total_schemes=len(schemes),
            index_path=index_path,
            dimension=self._dimension,
        )

    # ── Index loading (fast, from disk) ──────────────────────────

    def load_index(self) -> None:
        """
        Load a pre-built FAISS index and scheme metadata from disk.

        This is the fast path — no embedding computation, just file reads.
        Call this at application startup after the index has been built once.
        """
        index_path = os.path.join(self.index_dir, INDEX_FILENAME)
        metadata_path = os.path.join(self.index_dir, METADATA_FILENAME)

        if not os.path.exists(index_path):
            raise FileNotFoundError(
                f"FAISS index not found at {index_path}. "
                f"Run build_index() first to create it."
            )
        if not os.path.exists(metadata_path):
            raise FileNotFoundError(
                f"Scheme metadata not found at {metadata_path}. "
                f"Run build_index() first to create it."
            )

        self._index = faiss.read_index(index_path)

        with open(metadata_path, "r", encoding="utf-8") as f:
            self._schemes = json.load(f)

        logger.info(
            "index_loaded",
            total_schemes=self._index.ntotal,
            index_path=index_path,
        )

    # ── Search ───────────────────────────────────────────────────

    def search(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Embed a query and search the FAISS index for the top-K matching schemes.

        Args:
            query: The user's post text (or relevant portion).
            top_k: Number of top results to return.

        Returns:
            List of (scheme_dict, similarity_score) tuples, sorted by
            descending similarity. Score is cosine similarity (0.0 to 1.0).
        """
        if self._index is None:
            raise RuntimeError(
                "Index not loaded. Call build_index() or load_index() first."
            )

        # Embed the query
        query_vector = self.embed_query(query)

        # Search FAISS
        # D = distances (inner product scores), I = indices
        k = min(top_k, self._index.ntotal)
        distances, indices = self._index.search(query_vector, k)

        # Map indices back to scheme dicts
        results = []
        for score, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._schemes):
                continue
            results.append((self._schemes[idx], float(score)))

        return results

    # ── Utility ──────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """Check if the index is loaded and ready for search."""
        return self._index is not None and len(self._schemes) > 0

    @property
    def scheme_count(self) -> int:
        """Number of schemes in the loaded index."""
        return len(self._schemes) if self._schemes else 0
