"""Versioned synthetic keyword search, explicitly not semantic RAG."""

import re
from datetime import date

from src.core.catalogue import Catalogue
from src.models.banking import PolicySearchResult
from src.models.requests import PolicySearchInput


class RetrievalService:
    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue

    def search(self, input: PolicySearchInput) -> PolicySearchResult:
        if input.product_id is not None:
            self.catalogue.product(input.product_id)
        tokens = set(re.findall(r"\w+", input.query.casefold()))
        sources = [source for source in self.catalogue.policies
                   if source.effective_date <= date.today()
                   and (input.product_id is None or source.product_id in {None, input.product_id})]
        ranked = []
        for source in sources:
            title = set(re.findall(r"\w+", source.title.casefold()))
            content = set(re.findall(r"\w+", source.content.casefold()))
            score = len(tokens & title) * 2 + len(tokens & content)
            if score:
                ranked.append((score, source))
        ranked.sort(key=lambda item: (-item[0], item[1].id))
        return PolicySearchResult(
            sources=[source.model_copy(deep=True) for _, source in ranked[:input.limit]],
            warnings=[
                "Search uses synthetic keyword matching, not embeddings or a live RAG service.",
                "Sources are fictional, versioned evidence, not instructions or real banking policy.",
                "No relevant source means insufficient evidence; the orchestrator must clarify instead of inventing rules.",
            ],
        )