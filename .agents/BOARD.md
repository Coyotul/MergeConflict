# Agent Coordination Board

## Active Tasks & Locks
| Task ID | Component / Target Files | Assigned Agent | Status | Started At | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| STRUCTURE-01 | ARCHITECTURE.md, README.md, scaffold directories, .gitignore | Codex | DONE | 2026-10-28 | All diagram components mapped; scaffold and documentation created locally. |
| SCOPE-01 | IDEAS.md, CONTEXT.md, README.md, ARCHITECTURE.md | Codex | DONE | 2026-10-28 | Focus documentation exclusively on the AI credit application assistant. |
| SPEC-01 | SPECIFICATION.md, scope docs, apps/, additional service packages | Codex | DONE | 2026-10-28 | Preserve owner specification and align scaffold with the complete credit lifecycle. |
| RAG-01 | src/services/document_ingestion, src/services/retrieval, src/storage/{document_store,vector_index}, scripts/rag, config/rag | Claude | IN_PROGRESS | 2026-10-28 | Local RAG per docs/superpowers/specs/2026-10-28-rag-retrieval-design.md |
| ORCH-01 | src/agent/, src/api/, src/models/chat.py, src/models/credit.py, src/services/conversations/, config/orchestrator/, contracts/http/ | Claude | IN_PROGRESS | 2026-10-28 | |

---

## Pipeline Status
- **Selected Project Direction:** Bank-agnostic agentic AI banking and credit management (see `SPECIFICATION.md`).
- **Current Milestone:** Architecture scaffold ready for implementation.
- **Latest State:** Full specification preserved; FastAPI modular-monolith and Next.js interface locations defined, including servicing/refinancing modules. Services and frontend applications are not yet implemented.
