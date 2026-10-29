# Handoff: Orchestrator to Frontend

**From:** orchestrator-agent  
**To:** frontend  
**Commit:** d72073f  
**Date:** 2026-10-28

## Summary

The AI orchestrator is complete and ready for frontend integration. It provides a conversational HTTP API for guiding customers through credit applications in Romanian and English.

**Key deliverables:**
- Chat HTTP API with session management, message handling, document uploads, offer selection, and confirmation flow
- Session state persistence (memory, file, or PostgreSQL store)
- Featherless gpt-oss-120b integration for natural language understanding
- Mock mode (fake model) for frontend development without API keys
- Synthetic customer profiles (cust-001, cust-002, cust-003) for testing
- 293 tests passing (unit, integration, contract, e2e, live)

**Contract location:** [contracts/http/README.md](../contracts/http/README.md)

The contract document contains:
- OpenAPI spec: `contracts/http/chat.openapi.yaml`
- Example responses per stage: `contracts/http/examples/chat/`
- Endpoint documentation with request/response schemas
- Rendering guidance for `TurnResponse` (messages, awaiting, progress, blocks, citations)
- Error codes and retry semantics
- Test hooks for rejected documents and scripted conversations

## Known Limitations

### 1. Simulated stubs
The following components use synthetic implementations (marked with `simulated: true` in responses):
- **Customer profiles:** Only cust-001, cust-002, cust-003 are configured; other IDs fail profile lookup
- **Document processing:** Returns hardcoded extracted fields based on customer ID; files with `reject_` prefix or empty files are rejected
- **Eligibility:** Deterministic outcomes per customer (cust-001 → eligible, cust-002 → not_eligible, cust-003 → manual_review)
- **Offers:** Synthetic loan offers with scripted terms
- **Submission:** Returns application ID but no real backend integration

### 2. RAG retrieval requires merge
Policy search currently uses stub passages (publisher: "Synthetic stub"). Real citation retrieval requires:
- Setting `ORCHESTRATOR_RETRIEVAL=rag` in environment
- RAG service (RAG-01 task) merged and database populated

### 3. Prompt reliability issues observed in live testing
During the 5-turn conversation test with openai/gpt-oss-120b, the following behaviors were observed:
- **Field extraction gaps:** After the customer stated "30000 lei pe 60 de luni" (amount and term), the model asked for confirmation of the term instead of registering both values
- **Repeated product selection prompts:** The model asked for product type choice multiple times across turns 2-4 even after other details were provided
- **Slow discovery progression:** The application remained in discovery stage without advancing to collecting_information despite multiple field updates

These are prompt engineering issues in `src/agent/prompting.py` system prompt or context formatting, not API contract issues. The frontend should handle the protocol correctly; the assistant may require prompt iteration to improve field extraction and stage transitions.

### 4. No gateway integration
Endpoints require `X-Customer-Id` header on every request (returns `401` if missing). Production deployment will need API gateway authentication.

## Action Required

1. **Review the contract:** Read [contracts/http/README.md](../contracts/http/README.md) end-to-end
2. **Start backend in mock mode:**
   ```bash
   ORCHESTRATOR_MODEL=fake uvicorn src.api.app:create_app --factory --port 8000
   ```
3. **Build chat UI** implementing:
   - Session creation and message sending
   - `TurnResponse` rendering (messages, citations, awaiting input, progress stepper, blocks)
   - Document upload flow
   - Offer selection and confirmation flows
   - Error handling with retry semantics
4. **Test with synthetic customers:**
   - `cust-001`: Happy path (eligible, sees payslip conflict to confirm)
   - `cust-002`: Low income (reaches not_eligible)
   - `cust-003`: Self-employed (reaches manual_review)
5. **Flag prompt issues:** If the assistant gives poor responses during frontend testing, report specific turns and expected behavior; do NOT try to work around prompt issues in the frontend

## Test Commands

Run the backend test suite to verify setup:
```bash
python -m pytest tests/contract -v    # Contract validation
python -m pytest tests/e2e -v         # End-to-end scenarios
python -m pytest tests -v             # Full suite (293 tests)
```

Mock mode requires no database or API keys. Real mode requires `FEATHERLESS_API_KEY` in `.env`.

---

**Status:** Ready for frontend implementation  
**Next:** Build chat UI components and flows per contract specification
