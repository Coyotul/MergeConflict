"""Shared knowledge models and taxonomies for RAG retrieval."""
from enum import StrEnum
from typing import Annotated, Literal
from datetime import date, datetime
from pydantic import BaseModel, Field, StringConstraints, field_validator


class DocKind(StrEnum):
    """Types of documents in the knowledge base."""
    product_page = "product_page"
    category_hub = "category_hub"
    guide = "guide"
    faq_page = "faq_page"
    article = "article"
    fee_list = "fee_list"
    general_terms = "general_terms"
    cost_sheet = "cost_sheet"
    pdf_generic = "pdf_generic"


class ChunkKind(StrEnum):
    """Types of chunks within documents."""
    section = "section"
    faq = "faq"
    worked_example = "worked_example"
    hub_card = "hub_card"
    hub_teasers = "hub_teasers"
    fee_table = "fee_table"
    clause = "clause"
    cost_facts = "cost_facts"
    cost_examples = "cost_examples"
    generic = "generic"


class Authority(StrEnum):
    """Authority levels for document content."""
    high = "high"
    medium = "medium"
    low = "low"


# Map each DocKind to its Authority level
AUTHORITY_BY_DOC_KIND: dict[DocKind, Authority] = {
    DocKind.product_page: Authority.high,
    DocKind.fee_list: Authority.high,
    DocKind.general_terms: Authority.high,
    DocKind.cost_sheet: Authority.high,
    DocKind.pdf_generic: Authority.high,
    DocKind.guide: Authority.medium,
    DocKind.faq_page: Authority.medium,
    DocKind.article: Authority.low,
    DocKind.category_hub: Authority.low,
}


class LinkKind(StrEnum):
    """Types of links to related content."""
    card = "card"
    teaser = "teaser"
    inline = "inline"


class RelatedLink(BaseModel):
    """A link to related content."""
    title: str
    url: str
    canonical_key: str
    link_kind: LinkKind


class Product(StrEnum):
    """Credit products offered."""
    personal_loan = "personal_loan"
    refinancing_unsecured = "refinancing_unsecured"
    refinancing_mortgage = "refinancing_mortgage"
    mortgage_casa_ta = "mortgage_casa_ta"
    mortgage_casa_ta_verde = "mortgage_casa_ta_verde"
    mortgage_noua_casa = "mortgage_noua_casa"
    mortgage_residential_projects = "mortgage_residential_projects"
    overdraft = "overdraft"
    credit_card = "credit_card"
    general = "general"


class Topic(StrEnum):
    """Topics covered in the knowledge base."""
    # Credit topics
    eligibility = "eligibility"
    costs_fees = "costs_fees"
    worked_example = "worked_example"
    required_documents = "required_documents"
    early_repayment = "early_repayment"
    refinancing = "refinancing"
    restructuring_difficulty = "restructuring_difficulty"
    variable_rate_ircc = "variable_rate_ircc"
    repayment_methods = "repayment_methods"
    credit_process = "credit_process"
    general_terms_credit = "general_terms_credit"
    # Non-credit topics
    accounts = "accounts"
    payments = "payments"
    cards = "cards"
    data_protection = "data_protection"
    aml = "aml"
    other = "other"


# The 11 credit topics
CREDIT_TOPICS: frozenset[Topic] = frozenset([
    Topic.eligibility,
    Topic.costs_fees,
    Topic.worked_example,
    Topic.required_documents,
    Topic.early_repayment,
    Topic.refinancing,
    Topic.restructuring_difficulty,
    Topic.variable_rate_ircc,
    Topic.repayment_methods,
    Topic.credit_process,
    Topic.general_terms_credit,
])


class PassageFlag(StrEnum):
    """Flags indicating special states of passages."""
    superseded = "superseded"
    withdrawn = "withdrawn"
    campaign_active = "campaign_active"
    campaign_ended = "campaign_ended"
    low_authority = "low_authority"
    teaser_figure = "teaser_figure"


class SearchStatus(StrEnum):
    """Status of a search result."""
    ok = "ok"
    insufficient_evidence = "insufficient_evidence"


class SearchQuery(BaseModel):
    """A search query for the knowledge base."""
    # Stripped first, then 1-1000 characters; a non-string is a ValidationError.
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    # An empty list means no filter, like None.
    products: list[Product] | None = None
    topics: list[Topic] | None = None
    doc_kinds: list[DocKind] | None = None
    top_k: int = Field(6, ge=1, le=20)
    as_of: date = Field(default_factory=date.today)
    include_superseded: bool = False
    include_withdrawn: bool = False
    expand_context: bool = False

    @field_validator("products", "topics", "doc_kinds")
    @classmethod
    def empty_filter_is_none(cls, v: list | None) -> list | None:
        """An empty filter list would match nothing; treat it as no filter."""
        return v or None

    @property
    def effective_topics(self) -> frozenset[Topic]:
        """Return topics or CREDIT_TOPICS if topics is None."""
        if self.topics is None:
            return CREDIT_TOPICS
        return frozenset(self.topics)


class Citation(BaseModel):
    """Citation metadata for a passage."""
    publisher: str
    title: str
    url: str
    canonical_key: str
    page: int | None = None
    anchor: str | None = None
    section_path: list[str]
    version_label: str | None = None
    effective_date: date
    fetched_at: datetime
    campaign_valid_until: date | None = None


class Scores(BaseModel):
    """Relevance scores for a passage."""
    dense: float | None = None
    keyword: float | None = None
    fused: float


class PassageContext(BaseModel):
    """Context around a passage."""
    previous: str | None = None
    next: str | None = None


class Passage(BaseModel):
    """A passage from the knowledge base."""
    chunk_id: int
    document_id: int
    doc_kind: DocKind
    kind: ChunkKind
    topic: Topic
    products: list[Product]
    authority: Authority
    header: str
    text: str
    citation: Citation
    scores: Scores
    flags: list[PassageFlag] = []
    warnings: list[str] = []
    defer_to: int | None = None
    context: PassageContext | None = None
    related_links: list[RelatedLink] = []


class Conflict(BaseModel):
    """A conflict between passages."""
    doc_kind: DocKind
    topic: Topic
    product: Product
    chunk_ids: list[int]
    effective_dates: list[date]


class IndexInfo(BaseModel):
    """Metadata about the knowledge base index."""
    embedding_model: str
    chunker_version: str
    last_ingest_at: datetime


class SearchResult(BaseModel):
    """Result of a search query."""
    status: SearchStatus
    passages: list[Passage] = []
    conflicts: list[Conflict] = []
    index_info: IndexInfo | None = None
    content_trust: Literal["untrusted_evidence"] = "untrusted_evidence"
