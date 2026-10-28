# Agent & Coding Rules

- **Git-Based Agent Coordination:** Follow [`GIT_AGENT_PROTOCOL.md`](file:///c:/Users/George/repos/MergeConflict/GIT_AGENT_PROTOCOL.md). Always pull before starting, claim tasks in `.agents/BOARD.md`, and use standardized commit messages.
- **Language & Runtime:** Python 3.11+ (using `.venv`).
- **Data Validation:** Use Pydantic models for structured inputs and outputs.
- **Deterministic Logic:** Banking rules and compliance calculations must be handled deterministically (code/logic), not left to LLM guesswork.
- **Error Handling:** Do not crash on bad inputs; flag exceptions or return meaningful error states.
- **Modularity:** Keep parsers, rules, and agent orchestration decoupled in separate files to avoid merge conflicts.
- **Git Hygiene:** Never commit `.venv`, `.env`, API keys, or temporary files.
