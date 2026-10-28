# ADR 004: Customer workspace viewport containment, auto-sizing composer and Taste Skill audit

Date: 2026-10-28. Status: accepted for the customer interface increment.

## Owner request and problem description

On the customer home page (`/`), viewing the guided AI assistant required scrolling down the browser window to see the text input box (composer), resulting in poor ergonomics on laptop displays and standard desktop resolutions (1440×900, 1366×768, 1280×720).

The user requested:
1. Pushing the frontend progress to remote repository (`origin/frontend`).
2. Fixing viewport autosizing so the entire customer interface fits within the viewport without requiring page-level scrolling.
3. Keeping the AI composer pinned and continuously visible at the bottom of the workspace.
4. Enabling smooth textarea auto-growing as multiline messages are entered.
5. Auditing and refining the UI using the installed **Taste Skill** (`design-taste-frontend`), resolving visual tells such as oversized headers, low text contrast and background gradients.

## Structural and layout decisions

1. **Viewport containment**:
   - `html, body` and the root layout container (`CustomerShell` / `StaffShell`) enforce `h-screen max-h-screen h-dvh max-h-dvh overflow-hidden min-h-0`.
   - The root window never has page-level vertical scrollbars on desktop viewports.
   - Internal conversation and dashboard views scroll within dedicated overflow containers (`.conversation-scroll`).

2. **Always-visible pinned composer**:
   - The composer footer in `AssistantWorkspace` is anchored with `shrink-0` at the bottom of the main surface.
   - Verified via Playwright layout probes across 1440×900, 1366×768, 1280×720, 1024×600, 768×1024 and mobile (390×844): `composerVisible: true` in all tested resolutions.

3. **Auto-growing textarea**:
   - The composer textarea dynamically measures its `scrollHeight` and adjusts its height between 38px (single line) and 140px (multiline).
   - Enter sends the message; Shift + Enter creates a newline. Submitting resets the height smoothly.

4. **Taste Skill refinements**:
   - Replaced oversized 49px 3-line heading with a clean, app-appropriate title (24–30px) that leaves comfortable room for cards and conversation.
   - Replaced radial backdrop gradient with flat `#171717`.
   - Reduced panel drop-shadows to quiet, grounded elevations (`0 4px 24px rgba(0,0,0,0.08)`).
   - Standardized secondary typography from `text-[10px]` to `text-xs` (12px) and adjusted low-contrast labels to meet WCAG AA contrast (≥ 4.5:1).

## Verification and status

- Taste Skill report before: `composerVisible: false` (page heights 1003–1042px), headline wrap FAIL, gradient FAIL.
- Taste Skill report after: `composerVisible: true` across all viewports, `pageHeight === viewportHeight`, contrast and headline issues resolved.
- Verified with ESLint, TypeScript workspaces and banking unit tests (`npm run check`).
