# Handoff: Real document tools in the orchestrator

- **From:** Cline / orchestrator-documents
- **Branch:** `feature/orchestrator-document-tools` (local only; no main merge or push)
- **Base:** `c7cea73`
- **Task:** ORCH-DOC-02

## Integration

Chat uploads share `SecureDocumentStore` with `DocumentProcessingService`, and
`process_document` now reads the real stored bytes. It remains server-only.
The model has `read_document_extraction` (one current document type) and
`verify_application_documents` (current dossier), both read-only and owner/session
scoped. Code also verifies automatically before offers/submission. No document
paths, full OCR transcripts, CNPs/IBANs or acceptance overrides go to the model.

Do not reinstate the canned `customers.yaml` document values, filename-based
acceptance hooks, PDF-metadata-as-text fallback, inconsistent-balance repair,
guessed net pay/salary/zero debt, or a checksum waiver for chat uploads.
Standalone stub registries remain for explicitly isolated unit tests only;
all API composition paths bind the real document service.

## Checks

- 119 document checks pass, including actual PNG/JPEG/scanned/mixed PDF OCR and rotation.
- Full Python suite with benchmark: 742 passed, 420 subtests passed, 13 skipped,
  no failures (PostgreSQL unreachable and no live model key).
- Frontend checks: 63 JavaScript tests and 8 browser journeys pass; both builds pass.
- Real loopback HTTP journey and the existing manual document runners pass.
- `scripts/check_document_tools.py` gives a plain-language, nonzero-on-failure report.

See `docs/runbooks/orchestrator-documents.md` for exact commands and supported
evidence. Generated chat examples now use real synthetic PDFs, and tests pin the
archived fixture assessment date. Production still needs trusted authentication,
encrypted storage, malware/issuer checks, database-backed recovery/retention and
authorized human review resolution. Existing stub-accepted sessions are not
automatically trusted; start fresh or replace evidence.