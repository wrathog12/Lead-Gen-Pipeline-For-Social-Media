"""
Hybrid Search — Combines FAISS dense search + BM25 sparse search.

With only 50 schemes, both search methods are brute-force exact
(no approximation), so a cross-encoder reranker is unnecessary.
The hybrid merge itself produces a precise final ranking.

Strategy:
  1. Dense (FAISS): Semantic similarity via sentence-transformer embeddings
  2. Sparse (BM25): Exact keyword overlap using scheme bm25_keywords
  3. Score fusion: Weighted combination of normalized dense + sparse scores
  4. Return the top-K merged results as the final scheme matches

Score fusion uses Reciprocal Rank Fusion (RRF) — a simple, robust method
that doesn't require tuning score normalization across different scales.
"""

import json
import os
from typing import List, Dict, Any, Tuple, Optional

from rank_bm25 import BM25Okapi

from src.rag.embedder import SchemeEmbedder
from src.utils.logger import get_logger

logger = get_logger("hybrid_search")

# ── Defaults ─────────────────────────────────────────────────────
DEFAULT_SCHEME_PATH = os.path.join("data", "raw", "icici_scheme_dataset.json")

# RRF constant (standard value from the original RRF paper)
# Higher k reduces the impact of rank differences between methods
RRF_K = 60


class HybridSearch:
    """
    Combines FAISS vector search with BM25 keyword matching
    using Reciprocal Rank Fusion for final scoring.
    """

    def __init__(
        self,
        scheme_path: str = DEFAULT_SCHEME_PATH,
        index_dir: str = None,
    ):
        self.scheme_path = scheme_path
        self._schemes: List[Dict[str, Any]] = []
        self._bm25: Optional[BM25Okapi] = None
        self._embedder: Optional[SchemeEmbedder] = None
        self._ready = False

        # Load schemes and build both indices
        self._index_dir = index_dir or os.path.join("data", "vector_store")

    def initialize(self, force_rebuild: bool = False) -> None:
        """
        Load scheme data and prepare both search indices.

        This should be called ONCE at application startup.
        It will:
          1. Load the scheme JSON
          2. Build or load the FAISS dense index (via SchemeEmbedder)
          3. Build the BM25 sparse index from bm25_keywords

        Args:
            force_rebuild: If True, forces re-embedding even if FAISS index exists.
        """
        # ── Load scheme data ─────────────────────────────────────
        logger.info("loading_schemes", path=self.scheme_path)

        with open(self.scheme_path, "r", encoding="utf-8") as f:
            self._schemes = json.load(f)

        logger.info("schemes_loaded", count=len(self._schemes))

        # ── Initialize FAISS (dense) ─────────────────────────────
        self._embedder = SchemeEmbedder(index_dir=self._index_dir)
        self._embedder.build_index(
            scheme_path=self.scheme_path,
            force_rebuild=force_rebuild,
        )

        # ── Build BM25 (sparse) ─────────────────────────────────
        # Tokenize each scheme's keywords into a document for BM25.
        # We combine bm25_keywords + scheme_name words for richer matching.
        corpus = []
        for scheme in self._schemes:
            # Combine keywords and scheme name into a single token list
            tokens = list(scheme.get("bm25_keywords", []))

            # Add scheme name words (lowercased, split on spaces)
            name_tokens = scheme.get("scheme_name", "").lower().split()
            tokens.extend(name_tokens)

            # Add metadata category and sub_category
            meta = scheme.get("metadata", {})
            if meta.get("category"):
                tokens.extend(meta["category"].lower().split())
            if meta.get("sub_category"):
                tokens.extend(meta["sub_category"].lower().split())

            corpus.append(tokens)

        self._bm25 = BM25Okapi(corpus)
        self._ready = True

        logger.info(
            "hybrid_search_ready",
            total_schemes=len(self._schemes),
            bm25_corpus_size=len(corpus),
        )

    # ── Dense search (FAISS) ─────────────────────────────────────

    def _dense_search(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[int, float]]:
        """
        Search using FAISS vector similarity.

        Returns list of (scheme_index, cosine_score) tuples.
        """
        if self._embedder is None or not self._embedder.is_ready:
            return []

        results = self._embedder.search(query, top_k=top_k)

        # Map scheme dicts back to indices
        indexed_results = []
        for scheme, score in results:
            try:
                idx = next(
                    i for i, s in enumerate(self._schemes)
                    if s["scheme_id"] == scheme["scheme_id"]
                )
                indexed_results.append((idx, score))
            except StopIteration:
                continue

        return indexed_results

    # ── Sparse search (BM25) ────────────────────────────────────

    def _sparse_search(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[int, float]]:
        """
        Search using BM25 keyword matching.

        Tokenizes the query and scores against the keyword corpus.
        Returns list of (scheme_index, bm25_score) tuples.
        """
        if self._bm25 is None:
            return []

        # Tokenize query: lowercase, split on whitespace
        query_tokens = query.lower().split()

        # Get BM25 scores for all schemes
        scores = self._bm25.get_scores(query_tokens)

        # Get top-K indices by score (descending)
        indexed_scores = [(i, float(scores[i])) for i in range(len(scores))]
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        # Filter out zero-score results and take top-K
        return [(idx, score) for idx, score in indexed_scores[:top_k] if score > 0.0]

    # ── Reciprocal Rank Fusion ───────────────────────────────────

    def _rrf_merge(
        self,
        dense_results: List[Tuple[int, float]],
        sparse_results: List[Tuple[int, float]],
    ) -> List[Tuple[int, float]]:
        """
        Merge dense and sparse results using Reciprocal Rank Fusion (RRF).

        RRF score = Σ 1 / (k + rank_i) for each ranking method i
        where k is a constant (default 60) and rank is 1-indexed.

        This avoids the need to normalize scores across different
        scoring scales (cosine similarity vs BM25 scores).
        """
        rrf_scores: Dict[int, float] = {}

        # Score from dense rankings
        for rank, (idx, _score) in enumerate(dense_results, start=1):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (RRF_K + rank)

        # Score from sparse rankings
        for rank, (idx, _score) in enumerate(sparse_results, start=1):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (RRF_K + rank)

        # Sort by combined RRF score descending
        merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return merged

    # ── Public search interface ──────────────────────────────────

    def search(
        self, query: str, top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search and return top-K matched schemes.

        Combines FAISS dense search + BM25 sparse search via RRF,
        then returns the top-K schemes with their relevance scores.

        Args:
            query: The user's post text (already validated by Tier-1 & Tier-2).
            top_k: Number of top results to return (default 3).

        Returns:
            List of dicts, each containing the full scheme data plus
            a 'relevance_score' field, sorted by relevance descending.
            Example:
            [
                {
                    "scheme_id": "ICICI_PRU_BLUECHIP",
                    "scheme_name": "ICICI Prudential Bluechip Fund",
                    "metadata": {...},
                    "bm25_keywords": [...],
                    "vector_description": "...",
                    "relevance_score": 0.032,
                    "dense_rank": 1,
                    "sparse_rank": 3
                }
            ]
        """
        if not self._ready:
            raise RuntimeError(
                "HybridSearch not initialized. Call initialize() first."
            )

        # Retrieve candidates from both methods
        # Fetch more than top_k from each to improve coverage before merge
        fetch_k = min(top_k * 3, len(self._schemes))
        dense_results = self._dense_search(query, top_k=fetch_k)
        sparse_results = self._sparse_search(query, top_k=fetch_k)

        logger.info(
            "search_candidates",
            dense_count=len(dense_results),
            sparse_count=len(sparse_results),
            query=query[:80],
        )

        # Merge via RRF
        merged = self._rrf_merge(dense_results, sparse_results)

        # Build dense/sparse rank lookups for diagnostics
        dense_rank_map = {idx: rank for rank, (idx, _) in enumerate(dense_results, 1)}
        sparse_rank_map = {idx: rank for rank, (idx, _) in enumerate(sparse_results, 1)}

        # Map back to scheme dicts and attach scores
        results = []
        for idx, rrf_score in merged[:top_k]:
            scheme = self._schemes[idx].copy()
            scheme["relevance_score"] = round(rrf_score, 6)
            scheme["dense_rank"] = dense_rank_map.get(idx, -1)
            scheme["sparse_rank"] = sparse_rank_map.get(idx, -1)
            results.append(scheme)

        if results:
            logger.info(
                "top_match",
                scheme=results[0]["scheme_name"],
                score=results[0]["relevance_score"],
                dense_rank=results[0]["dense_rank"],
                sparse_rank=results[0]["sparse_rank"],
            )

        return results

    # ── Utility ──────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """Check if both indices are loaded and ready for search."""
        return self._ready

    @property
    def scheme_count(self) -> int:
        """Number of schemes in the loaded dataset."""
        return len(self._schemes)
