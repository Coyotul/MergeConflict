"""Retrieval protocols and stub implementation for policy search."""
from datetime import datetime, UTC, date
from pathlib import Path
from typing import Protocol
import yaml

from src.models.knowledge import (
    SearchQuery,
    SearchResult,
    SearchStatus,
    Passage,
    Citation,
    Scores,
    Product,
    DocKind,
    ChunkKind,
    Topic,
    Authority,
)


class PolicySearch(Protocol):
    """Protocol for searching banking policies."""

    def search(self, query: SearchQuery) -> SearchResult:
        """Search for relevant passages.

        Args:
            query: Search query

        Returns:
            Search result with passages or insufficient evidence
        """
        ...


class StubPolicySearch:
    """Stub implementation using keyword overlap matching."""

    def __init__(self, config_dir: Path):
        """Initialize stub with policy passages from YAML.

        Args:
            config_dir: Directory containing policy_passages.yaml
        """
        self.config_dir = config_dir
        self._passages = self._load_passages()

    def _load_passages(self) -> list[Passage]:
        """Load passages from YAML file."""
        yaml_path = self.config_dir / "policy_passages.yaml"
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        passages = []
        for item in data["passages"]:
            # Parse dates
            effective_date = date.fromisoformat(item["effective_date"])
            fetched_at = datetime.fromisoformat(item["fetched_at"].replace("Z", "+00:00"))

            # Build Citation
            citation = Citation(
                publisher=item["publisher"],
                title=item["header"],
                url=item["url"],
                section_path=item["section_path"],
                effective_date=effective_date,
                fetched_at=fetched_at
            )

            # Build Scores
            scores = Scores(
                dense=item.get("dense_score"),
                keyword=item.get("keyword_score"),
                fused=item["fused_score"]
            )

            # Build Passage
            passage = Passage(
                chunk_id=item["chunk_id"],
                document_id=item["document_id"],
                doc_kind=DocKind(item["doc_kind"]),
                kind=ChunkKind(item["kind"]),
                topic=Topic(item["topic"]),
                products=[Product(p) for p in item["products"]],
                authority=Authority(item["authority"]),
                header=item["header"],
                text=item["text"],
                citation=citation,
                scores=scores
            )

            passages.append(passage)

        return passages

    def search(self, query: SearchQuery) -> SearchResult:
        """Search passages using simple keyword overlap.

        Returns insufficient_evidence when no passage shares a non-stopword
        token with the query.

        Args:
            query: Search query

        Returns:
            Search result with matching passages or insufficient evidence
        """
        # Stopwords to exclude from matching
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "up", "about", "into", "through", "during",
            "before", "after", "above", "below", "between", "under", "again",
            "further", "then", "once", "here", "there", "when", "where", "why",
            "how", "all", "both", "each", "few", "more", "most", "other", "some",
            "such", "no", "nor", "not", "only", "own", "same", "so", "than",
            "too", "very", "can", "will", "just", "should", "now", "i", "you",
            "he", "she", "it", "we", "they", "them", "their", "what", "which",
            "who", "this", "that", "these", "those", "am", "is", "are", "was",
            "were", "be", "been", "being", "have", "has", "had", "do", "does",
            "did", "doing", "would", "could", "ought", "might", "must", "may"
        }

        # Extract query tokens (non-stopwords)
        query_text = query.text.lower()
        query_tokens = set()
        for word in query_text.split():
            # Strip punctuation
            word = ''.join(c for c in word if c.isalnum())
            if word and word not in stopwords:
                query_tokens.add(word)

        if not query_tokens:
            # Query is all stopwords
            return SearchResult(
                status=SearchStatus.insufficient_evidence,
                passages=[]
            )

        # Score each passage by token overlap
        scored_passages = []
        for passage in self._passages:
            # Filter by product if specified
            if query.products is not None:
                if not any(p in passage.products for p in query.products):
                    continue

            # Check token overlap
            passage_text = (passage.header + " " + passage.text).lower()
            passage_tokens = set()
            for word in passage_text.split():
                word = ''.join(c for c in word if c.isalnum())
                if word and word not in stopwords:
                    passage_tokens.add(word)

            overlap = query_tokens & passage_tokens
            if overlap:
                score = len(overlap) / len(query_tokens)
                scored_passages.append((score, passage))

        if not scored_passages:
            # No passages matched
            return SearchResult(
                status=SearchStatus.insufficient_evidence,
                passages=[]
            )

        # Sort by score descending and take top_k
        scored_passages.sort(key=lambda x: x[0], reverse=True)
        top_passages = [p for _, p in scored_passages[:query.top_k]]

        return SearchResult(
            status=SearchStatus.ok,
            passages=top_passages
        )
