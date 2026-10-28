# ADR 003: Yellow/black visual theme and separate demo sign-in

Date: 2026-10-28. Status: accepted for the local frontend increment.

## Owner request and preserved direction

Continue the uncommitted customer/staff frontend rather than rebuilding it. Apply
Raiffeisen-inspired colors and provide login for the customer and the bank agent
who reviews credit applications. Retain the English UI, conversational assistant,
two Next.js apps, shared components and the synthetic local adapter from ADRs 001/002.

The fictional Luma name and original sparkle mark remain. No bank logo is copied,
no affiliation is claimed, and all documents, policies, accounts and financial
outcomes remain explicitly synthetic.

## Visual system

- Primary yellow `#FFED00`, ink `#171717`, white surfaces, warm neutral borders.
- Shared semantic `primary`, `ink`, `brand-soft`, `brand-border` and `brand-ink`
  tokens replace blue/violet decoration. Yellow buttons use black text for contrast.
- Black navigation with yellow selected items; yellow/black/cream starting cards,
  neutral document/calculator panels and matching original SVG illustrations.
- Green, amber and red are reserved for meaningful success, missing information
  and rejection/error states. Keyboard focus and reduced-motion behavior remain.
- Split sign-in screens stack on mobile. The authenticated workspace retains its
  desktop-first structure; a full mobile workspace redesign is not in scope.

## Demo login, not production identity

Each app has the same accessible login component with workspace links, labeled
email/password fields, password visibility, loading/error states and a public demo
account card. “Use demo account” only fills the fields; submitting is explicit.

The local Node adapter checks a role-specific email/password pair and issues the
existing server-owned synthetic actor. Client credentials cannot be used to enter
the bank-agent workspace, and changing the requested role is insufficient to gain
review privileges. Existing owner, assignment and workflow checks still apply.

Sessions expire after eight hours and are revoked at logout. Valid sessions restore
on page refresh in the same tab. Malformed, mismatched, expired or revoked sessions
return to sign-in. In-flight refresh results cannot restore a logged-out session.
Browser session storage and demo JSON never store passwords; persisted workflow
records do not contain session tokens. Restarting the adapter invalidates tokens
without resetting applications, conversations or history.

The passwords are intentionally public fixtures included in the frontend. There
is no real identity provider, MFA, secure cookie session, rate limiting, credential
enrollment or password recovery. Loopback HTTP and sessionStorage are suitable
only for this local synthetic demonstration. Replace the adapter with production
authentication and authorization before using real data or deploying publicly.

## Validation scope

- Domain/API tests cover schema validation, normalized email, invalid credentials,
  role spoofing, expiry, logout revocation, restart invalidation and permissions.
- Browser tests cover both login forms, incorrect passwords, role separation,
  session restoration, corrupt/revoked sessions and mobile sign-in layout.
- The full customer submission -> information request -> resubmission -> agent
  approval remains covered, with a separate justified rejection/private-note test.
- Existing simulator, consent, navigation and keyboard-dialog tests are retained.
- Validate ESLint, workspace TypeScript, unit/API tests and both production builds.

All changes remain local for owner review; no automatic commit or push.