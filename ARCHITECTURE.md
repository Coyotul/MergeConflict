# System architecture and folder ownership

The product scope is defined in [SPECIFICATION.md](SPECIFICATION.md): a bank-agnostic
AI platform for the full credit lifecycle. The earlier banking diagram remains
the component baseline, extended below for servicing, refinancing and assistance.
Use a Python 3.11+/FastAPI modular monolith with separate Next.js customer and staff
interfaces. Backend folders are logical modules, not individual microservices.
The local Next.js prototype and a separate synthetic FastAPI capability API are
implemented. The frontend still uses its temporary Node adapter; the Python
orchestrator, live banking integrations and remaining scaffold capabilities are
not implemented. See ADR 006 and `contracts/http/backend-v1.md` for current backend
behavior and the integration boundary.
The merged `feature/eligibility-check` implementation provides synthetic preliminary
eligibility, verification adapters, affordability and a narrow API/tool boundary
(see `docs/decisions/005-eligibility-reference-service.md`). Its evidence-based
contract is preserved; this is not a complete banking platform.

## Repository layout

```text
MergeConflict/
|-- main.py                      # Existing development entry point
|-- requirements.txt             # Existing Python dependencies
|-- SPECIFICATION.md             # Full owner-supplied product requirements
|-- apps/
|   |-- customer/src/            # Next.js customer dashboard, chat and loan pages
|   `-- staff/src/               # Next.js reviewer and authorized admin views
|-- src/
|   |-- api/
|   |   |-- gateway/              # Routing and authentication integration
|   |   `-- application/          # HTTP handlers and request validation
|   |-- agent/
|   |   |-- orchestration/        # AI routing, context and tool coordination
|   |   |-- tools/                # Adapters to application capabilities
|   |   `-- prompts/              # Version-controlled prompt templates
|   |-- services/
|   |   |-- customers/            # Authorized customer profile access and consent
|   |   |-- conversations/        # Persisted conversation context, not workflow state
|   |   |-- document_ingestion/   # Policy/product knowledge ingestion
|   |   |-- document_processing/  # Applicant document processing
|   |   |-- retrieval/            # RAG search, ranking and source citations
|   |   |-- eligibility/          # Deterministic decision coordination
|   |   |-- pricing/              # Loan offers and repayment simulation
|   |   |-- financial_calculations/ # Shared deterministic financial engine
|   |   |-- loan_servicing/       # Repayment, term-change and restructuring requests
|   |   |-- refinancing/          # Refinance and debt-consolidation comparisons
|   |   |-- human_review/         # Assigned review queue, notes and decision actions
|   |   |-- notifications/        # Customer updates and notification preferences
|   |   |-- administration/       # Authorized product, policy and role administration
|   |   |-- financial_insights/   # Early warnings and life-event scenarios
|   |   |-- application_recovery/ # Missing evidence, corrections and follow-up cases
|   |   |-- workflow/             # Application state and review tasks
|   |   |-- contracts/            # Contract and signature coordination
|   |   `-- settlement/           # Authorized loan disbursement and status tracking
|   |-- parsers/
|   |   |-- ocr/                  # OCR provider adapters
|   |   |-- extraction/           # Structured field extraction
|   |   `-- validation/           # Completeness and verification
|   |-- rules/
|   |   |-- eligibility/          # Eligibility/compliance rules
|   |   |-- credit_scoring/       # Deterministic scoring calculations
|   |   `-- pricing/              # Product and interest calculation rules
|   |-- integrations/
|   |   |-- bank/                 # Bank integration facade and interfaces
|   |   |-- anaf/                 # ANAF adapter
|   |   |-- credit_bureau/        # Biroul de Credit adapter
|   |   |-- customer_loans/       # Customer and loan API adapters
|   |   |-- signature/            # E-signature provider adapter
|   |   |-- settlement/           # Disbursement provider adapter
|   |   `-- llm/                  # Model provider adapter
|   |-- storage/
|   |   |-- application_db/       # Repositories; migrations/ holds schema changes
|   |   |-- vector_index/         # Embeddings index adapter
|   |   |-- document_store/       # Policy/product source text and metadata
|   |   `-- secure_documents/     # Applicant upload storage adapter
|   |-- models/                  # Shared Pydantic data models
|   |-- core/                    # Settings, errors and dependency composition
|   |-- observability/           # Audit, logs, metrics and tracing
|   |-- security/                # Authorization, redaction and security policy
|   `-- ui/                      # Original unused Python UI placeholders;
|       |-- chat/                 # active frontend ownership is in apps/
|       `-- human_review/
|-- contracts/
|   |-- http/                    # OpenAPI specifications
|   |-- events/                  # Workflow/integration event schemas
|   `-- schemas/                 # Shared serialized data schemas
|-- config/
|   |-- products/                # Synthetic product/pricing inputs
|   `-- rules/                   # Versioned rule configuration
|-- data/
|   |-- synthetic/
|   |   |-- policies/             # Synthetic banking policies
|   |   |-- products/             # Synthetic product documents
|   |   `-- applications/         # Synthetic applicant documents and records
|   `-- local/                   # Ignored databases, uploads and indexes
|-- tests/
|   |-- unit/                    # Mirrors src/ as implementation grows
|   |-- integration/             # Storage/provider boundary tests
|   |-- contract/                # Serialized contract compatibility tests
|   |-- e2e/                     # Application/review journeys
|   `-- fixtures/                # Small synthetic test inputs
|-- infrastructure/
|   |-- local/                   # Local environment/dependency definitions
|   `-- deployment/              # Deployment and gateway configuration
|-- scripts/                     # Setup, ingestion and maintenance commands
`-- docs/
    |-- decisions/               # Architecture decision records
    `-- runbooks/                # Operations and failure recovery
```

## Diagram-to-code mapping

| Diagram component | Owning folder(s) | Responsibility |
| --- | --- | --- |
| Banking App / Chat UI | `apps/customer/` | Customer dashboard, chat, credit lifecycle pages, status and cited answers. |
| API Gateway + Authentication | `src/api/gateway/`, `src/security/` | Route requests, integrate identity verification and enforce access policy. Deployment configuration lives in `infrastructure/deployment/`. |
| Backend / Application API | `src/api/application/` | Validate requests with Pydantic and invoke use cases. |
| AI Orchestrator | `src/agent/` | Select tools and assemble responses; delegate authoritative actions to services. |
| Banking Policies & Product Docs | `data/synthetic/policies/`, `data/synthetic/products/` | Synthetic knowledge inputs for the demo. |
| Document Ingestion | `src/services/document_ingestion/` | Parse, chunk, embed and index knowledge with source versions. |
| Vector Index + Document Store | `src/storage/vector_index/`, `src/storage/document_store/` | Store searchable embeddings, source text and citation metadata. |
| Document Processing Service | `src/services/document_processing/` | Coordinate applicant document processing and persist validated results. |
| OCR + Extraction | `src/parsers/ocr/`, `src/parsers/extraction/` | Convert uploads into structured candidate fields. |
| Validation & Verification | `src/parsers/validation/` | Verify shape, completeness and consistency; return exceptions. |
| Secure Document Storage | `src/storage/secure_documents/` | Access-controlled storage of applicant files. |
| RAG Retrieval Service | `src/services/retrieval/` | Retrieve policy/product evidence with citations. |
| Eligibility & Decision Service | `src/services/eligibility/`, `src/services/human_review/` | Preliminary screening is deterministic; authorized human review records the prototype's final credit decision. |
| Rules Engine / Credit Scoring | `src/rules/eligibility/`, `src/rules/credit_scoring/` | Pure deterministic rule and score evaluation. |
| Bank Integration Layer | `src/integrations/bank/` | Expose provider-neutral operations and compose external adapters. |
| ANAF | `src/integrations/anaf/` | Tax/income data adapter or synthetic stub. |
| Biroul de Credit | `src/integrations/credit_bureau/` | Credit bureau adapter or synthetic stub. |
| Customer & Loan APIs | `src/integrations/customer_loans/` | Customer/loan adapter or synthetic stub. |
| Loan Pricing & Simulation | `src/services/pricing/`, `src/services/financial_calculations/`, `src/rules/pricing/` | Product-aware offers use a shared deterministic financial engine. |
| Product Rules & Pricing Data | `config/products/`, `config/rules/` | Structured rule inputs, distinct from ingested product prose. |
| Application Workflow Manager | `src/services/workflow/` | Own lifecycle, review gates and durable transitions. |
| Application Database | `src/storage/application_db/` | Persist applications, outcomes and workflow history. |
| Human Review Portal | `apps/staff/`, `src/services/human_review/` | Inspect evidence and submit authorized review actions through the API. |
| Contract & Signature Service | `src/services/contracts/`, `src/integrations/signature/` | Prepare contracts from approved terms and verify signature callbacks. |
| Authorized Disbursement / Settlement | `src/services/settlement/`, `src/integrations/settlement/` | Execute authorized loan disbursements and track provider outcomes. |
| Audit, Monitoring & Security | `src/observability/`, `src/security/` | Audit, telemetry, authorization and sensitive-data handling. |

## Additional specification modules

| Capability | Owning module | Boundary |
| --- | --- | --- |
| Customer profile and consent | `src/services/customers/` | Access only authorized profile/loan data through adapters. |
| Conversation persistence | `src/services/conversations/` | Retain messages and context separately from authoritative workflow records. |
| Financial engine | `src/services/financial_calculations/` | Decimal-safe schedules, affordability, fees, repayments, refinancing and cash-flow calculations with explicit assumptions. No LLM arithmetic. |
| Loan servicing | `src/services/loan_servicing/` | Early repayment, term changes and restructuring; use authoritative payoff amounts for execution. |
| Refinancing | `src/services/refinancing/` | Compare current and proposed obligations, including fees and total cost; coordinate specialized workflows. |
| Human review | `src/services/human_review/` | Assigned queues, independent evidence inspection, notes, requests for information and permission-checked decisions. |
| Notifications | `src/services/notifications/` | Persist customer updates and manage notification preferences. |
| Administration | `src/services/administration/` | Permission-controlled product/rule, policy-version, role and simulated-provider configuration. |
| Proactive assistance | `src/services/financial_insights/` | Consent-based shortfall estimates and life-event scenarios using the financial engine. |
| Application recovery | `src/services/application_recovery/` | Correct missing evidence, explain recorded reasons and coordinate authorized follow-ups. |
| Contract explanation | `src/services/contracts/`, `src/services/retrieval/` | Extract terms and explain clauses with citations; keep explanation separate from signature execution. |

These folders define ownership, not blanket completion claims. Current Python
services implement synthetic profile access, separate conversation context,
keyword policy search, document metadata validation, preliminary affordability,
Decimal pricing/repayment/refinancing simulations, persistent origination,
assigned human review, notifications and audit. OCR, semantic RAG, verified banking
data, administration, insights, restructuring/recovery and signing/settlement
remain unimplemented. Refinancing and repayment currently simulate only; future
execution requires specialized workflows rather than forcing origination states.
The merged reference EligibilityService is exposed through the backend's ID-only
run_eligibility_check, verified session/current assignment and a workflow repository
adapter. The saved calculator preview is not a verified eligibility decision.
Missing profile/document evidence and purpose-scoped authorizations remain absent;
metadata is not promoted to VERIFIED. Original reference contracts/tests remain.

## Component boundaries

- UI calls the application API, never storage or provider adapters directly.
- API handlers validate requests, apply authorization and call services. Domain
  behavior stays out of HTTP handlers.
- The agent calls explicit tools backed by services. An LLM must not decide
  eligibility, calculate pricing, approve contracts or authorize disbursement.
- Services coordinate use cases. Rules and parsers do not depend on the agent or UI.
- Workflow owns lifecycle transitions and review gates. Other services return typed
  outcomes instead of editing workflow state independently.
- Every new credit application requires explicit customer submission confirmation
  and authorized human review before its final decision is recorded in the MVP.
  Approval, signature and disbursement remain separate stages. Early repayment
  follows its own authorization path.
- Storage/provider interfaces belong with their consuming component. Concrete
  adapters live under `src/storage/` and `src/integrations/`; compose them in
  `src/core/`. Use synthetic implementations for the hackathon.
- `src/models/` holds shared Pydantic data models, not business logic. Private models
  stay with their service. Top-level `contracts/` holds wire specifications;
  `src/services/contracts/` holds contract/signature business logic.
- Start each module with a single implementation file. Add internal layers only
  when behavior requires them; do not duplicate this entire tree in every service.

## Main flows

1. **Knowledge ingestion:** synthetic policies/product documents -> ingestion ->
   parsing/chunking/embedding -> document store and vector index. Retrieval returns
   evidence and source/version metadata to the orchestrator.
2. **Application assessment:** chat -> gateway/auth -> application API -> workflow
   and orchestrator -> document processing -> OCR/extraction -> validation ->
   secure document storage. Eligibility combines validated results, bank adapters
   and deterministic rules; pricing uses product inputs and calculation rules.
3. **Human review and completion:** after explicit customer submission, workflow
   persists state and routes every new credit application to human review. A
   reviewer may request information, approve or reject. Signing and disbursement
   are separate, simulated stages. Audit and monitoring cover all steps.
4. **Existing loans:** servicing/refinancing/recovery tools invoke specialized
   workflows, deterministic comparisons and authorized review where required.
   Insights use consented data and explicit assumptions to present estimates.

## Implementation conventions

- Represent money precisely (for example, decimal values plus currency). Retain
  rule/product versions and reason codes with decisions.
- Define Pydantic input/output models and HTTP/event contracts as capabilities are
  implemented. Validate provider responses and callbacks at their boundaries; use
  consistent typed errors and correlation IDs.
- Durable transitions, callbacks and settlement need idempotency and explicit
  pending/failed/unknown outcomes before live use.
- Retrieved documents are evidence, not instructions. Keep prompts in
  `src/agent/prompts/` and treat extracted/retrieved text as untrusted input.
- Commit only synthetic fixtures and keep secrets outside Git. Runtime artifacts
  belong in ignored `data/local/`. Storage packages contain code, not database
  volumes, applicant files or vector-index snapshots.
- Add unit tests for deterministic rules, integration tests for adapters, contract
  tests for wire formats and end-to-end tests for workflow/review journeys as
  capabilities are implemented. Python unit/integration/contract tests and the
  frontend's existing domain/API/browser tests now exercise synthetic behavior.
  Eligibility tests additionally cover reference rules, provider failures,
  evidence provenance/freshness and synthetic screening journeys.

## Technology direction and persistence

The specification selects FastAPI and recommends Next.js/React/TypeScript with
Tailwind CSS for the interfaces. PostgreSQL is the database direction, preferably
via Supabase, with pgvector and Supabase Storage as initial candidates. Model
providers and banking APIs remain behind adapters. Core backend packages are pinned
in requirements; no cloud resources are provisioned and hosting/free-tier
availability is not verified. The local
backend deliberately uses standard-library SQLite with SQL migration, owner and
assignment indexes, foreign keys, typed aggregates and atomic workflow/audit/
notification/idempotency transactions (ADR 006). This is local synthetic storage,
not deployed cloud persistence or production authentication. Verify current
provider documentation when selecting or deploying services.
The evidence-based eligibility adapter likewise uses local-only SQLite for its
independent demo; its reference models/rules and generated contracts are preserved.

Application records, review decisions, status history, consents, conversations,
notifications and knowledge versions need durable storage. The conceptual entity
list is in specification section 14. Refine relationships, access isolation and
constraints before adding migrations under `src/storage/application_db/migrations/`.
Ignored `data/local/` is for local development artifacts, never cloud persistence.

## Development sequence and MVP

Follow the eight phases in specification section 18: foundation, conversation,
RAG, origination, human review, servicing/refinancing, proactive assistance, then
hardening/deployment. Define models, API/tool contracts, valid state transitions
and authorization rules before implementing their respective capabilities.

The complete MVP is the section 20 journey: synthetic login, grounded product
answers, preliminary screening and deterministic simulations, explicit submission,
reviewer request for a missing document, customer response, resumed review and a
human-recorded final outcome with full audit/status history. Include at least one
refinancing or early repayment simulation. No real loan approval, bureau inquiry,
contract execution, payment or disbursement occurs.

Financial calculations need known-result unit tests. Authorization, customer data
isolation, review permissions, repeated submissions and interrupted/resumed
workflows must be tested independently of the LLM (specification section 19).
Record subsequent architecture choices in `docs/decisions/`.
