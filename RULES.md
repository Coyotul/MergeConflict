# Agent & Coding Rules

- **Git-Based Agent Coordination:** Follow [`GIT_AGENT_PROTOCOL.md`](file:///c:/Users/George/repos/MergeConflict/GIT_AGENT_PROTOCOL.md). Always pull before starting, claim tasks in `.agents/BOARD.md`, and use standardized commit messages.
- **Product Scope:** Follow `SPECIFICATION.md` for the full credit-lifecycle product requirements and `ARCHITECTURE.md` for module ownership. Use synthetic data and simulated banking integrations for the MVP.
- **Language & Runtime:** Python 3.11+ and FastAPI for the modular-monolith backend (using `.venv`); Next.js, React and TypeScript for customer and staff interfaces.
- **Credit Authority:** Preliminary eligibility is distinct from final approval. Every new credit application in the prototype requires authorized human review and explicit customer submission confirmation. Approval, signing and disbursement are separate stages; financial execution is simulated.
- **Data Validation:** Use Pydantic models for structured inputs and outputs.
- **Deterministic Logic:** Banking rules and compliance calculations must be handled deterministically (code/logic), not left to LLM guesswork.
- **Error Handling:** Do not crash on bad inputs; flag exceptions or return meaningful error states.
- **Modularity:** Keep parsers, rules, and agent orchestration decoupled in separate files to avoid merge conflicts.
- **Git Hygiene:** Never commit `.venv`, `.env`, API keys, or temporary files.
