# Git-Based Multi-Agent Communication Protocol (GIT_AGENT_PROTOCOL.md)

This protocol enables autonomous or paired AI agents to collaborate, hand off tasks, and synchronize progress asynchronously using Git as the shared communication bus and source of truth.

---

## 1. Core Principles
1. **Pull Before Work:** Always run `git pull --rebase` before reading state or starting any task to get the latest messages and code from other agents.
2. **Conflict Prevention:** Agents must claim their task on the board (`.agents/BOARD.md`) before editing code. Never have two agents modify the exact same file simultaneously.
3. **Traceable Handoffs:** Every commit must clearly state **who** did the work, **what** changed, and **which agent or role** should act next.

---

## 2. Directory Structure for Communication
```text
.agents/
├── BOARD.md           # Shared blackboard: active agents, task locks, and pipeline status
├── messages/          # Asynchronous inbox for agent-to-agent messages
│   └── .gitkeep
└── log.md             # Append-only chronological activity log
```

---

## 3. Communication Patterns

### Pattern A: Task Claiming & Locks (Preventing Merge Conflicts)
Before working on a module, the agent updates `.agents/BOARD.md`:
```markdown
| Task ID | Module / File Path | Assigned Agent | Status | Started At |
|:---|:---|:---|:---|:---|
| TASK-01 | src/models/schemas.py | ModelAgent | IN_PROGRESS | 2026-10-28 10:45 |
```
Once committed and pushed, no other agent should touch `src/models/schemas.py` until the status is `DONE`.

### Pattern B: Agent-to-Agent Handoff Messages
When an agent finishes a task that another agent depends on, it adds a brief note to `.agents/messages/`:
- **File Name:** `YYYYMMDD-HHMM-<sender>-to-<recipient>.md`
- **Example Content:**
  ```markdown
  # Handoff: Parser to Rule Engine
  - **From:** ParserAgent
  - **To:** RulesAgent
  - **Commit:** a1b2c3d
  - **Summary:** Extracted applicant profile models are ready in `src/models/schemas.py`.
  - **Action Required:** Implement DTI (Debt-to-Income) validation in `src/rules/dti.py`.
  ```

### Pattern C: Append-Only Activity Log (`.agents/log.md`)
Agents append one line describing their actions to maintain a clear audit trail:
`[2026-10-28 10:50] [ParserAgent] Created synthetic payslip parser. Ready for rules engine.`

---

## 4. Git Commit Message Standard
Commit messages must follow this structure so any agent can parse Git history (`git log`):

```text
agent(<agent-role>): <concise action description>

- Details: <bullet points of what was created or changed>
- Status: <IN_PROGRESS | COMPLETED | BLOCKED>
- Next: @<next-agent-role> -> <action required>
```

**Example:**
```text
agent(rules): implement preliminary DTI calculation

- Added DtiRule class in src/rules/dti.py
- Added test cases in tests/test_dti.py
- Status: COMPLETED
- Next: @orchestrator-agent -> integrate DTI into main decision pipeline
```

---

## 5. Agent Workflow Step-by-Step
```text
[Agent Wakeup]
      │
      ▼
1. git pull --rebase
      │
      ▼
2. Read .agents/BOARD.md & check .agents/messages/ for assigned tasks
      │
      ▼
3. Claim task in .agents/BOARD.md -> git commit & push
      │
      ▼
4. Implement code & run tests locally
      │
      ▼
5. Update .agents/BOARD.md (Status: DONE)
   Write message in .agents/messages/ (if handoff needed)
   Append entry to .agents/log.md
      │
      ▼
6. git add . && git commit -m "agent(...): ..." && git push
```
