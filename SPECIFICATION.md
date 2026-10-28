# Project Specification: Agentic AI Banking and Credit Management Platform

## 1. Project Overview

We want to build a modern, AI-powered banking assistance platform that helps customers understand, apply for, manage, and refinance loans through a conversational interface.

The application should go beyond a traditional banking chatbot. It should be an intelligent agent capable of understanding customer intent, retrieving relevant banking policies, accessing authorized customer data, collecting and verifying documents, performing financial calculations, managing long-running application workflows, and coordinating with human banking representatives.

The platform should support the entire customer credit lifecycle, from exploring a new loan to repaying or refinancing an existing one.

The project should initially be developed as a functional prototype using synthetic customer data, simulated banking APIs, and free-tier cloud infrastructure where possible. The architecture should be designed so that real banking integrations can be introduced later without rebuilding the entire application.

The product must be bank-agnostic. Raiffeisen Bank Romania can be used as a reference for studying public banking procedures and product documentation, but the application must not impersonate Raiffeisen or claim to be officially affiliated with it.

## 2. Product Vision

Build an intelligent financial assistant that helps customers make better-informed financial decisions and coordinates banking processes on their behalf, subject to the necessary customer authorizations, banking policies, and human approvals.

The core principle is:

**The AI understands and coordinates. Deterministic services calculate and validate. Authorized banking systems execute transactions and enforce decisions. Human representatives review consequential credit decisions.**

The application should be proactive, contextual, transparent, and easy to use. It should maintain context throughout an application process and resume interrupted workflows without forcing the customer to start again.

## 3. User Roles

### 3.1 Customer

The customer can:

- View a financial dashboard.
- Chat with the AI assistant.
- Explore available credit products.
- Check preliminary credit eligibility.
- Apply for a new loan.
- Upload documents and track verification status.
- Compare loan amounts, interest rates, repayment periods, and total costs.
- Request loan refinancing or debt consolidation.
- Request partial or full early repayment.
- Explore repayment-period changes and restructuring options.
- Get help when experiencing financial difficulties.
- Understand existing loan contracts.
- Track submitted applications.
- Receive notifications and updates.
- Request human assistance.

### 3.2 Bank Representative / Credit Reviewer

The bank representative uses a separate staff interface to:

- View assigned applications.
- Review customer information and uploaded documents.
- Inspect document verification results.
- Review preliminary eligibility checks and financial calculations.
- See relevant policy sources and reasons behind system-generated flags.
- Approve, reject, or request additional information, according to their assigned permissions.
- Add internal notes and decision justifications.
- Request clarification from customers through the AI assistant.
- Review refinancing requests and repayment-related requests that require human intervention.
- View the complete application history and audit trail.

The reviewer must be able to independently assess the evidence. The interface must not encourage automatic approval of AI-generated recommendations.

### 3.3 Administrator

Administrators can:

- Manage application users and staff roles.
- Configure banking products and eligibility rules in the prototype.
- Upload and manage policy documents.
- Manage document versions and effective dates.
- Configure simulated external services.
- Review system health, errors, and audit events.
- Manage application-level configuration and feature flags.

Administrative actions must be authorized and logged.

## 4. Main Functional Modules

### 4.1 Conversational AI Assistant

Create an AI assistant that understands natural-language requests in a conversational interface.

Example requests include:

- "I want to apply for a personal loan of 30,000 RON."
- "Can I afford a monthly installment of 1,000 RON?"
- "What documents do I need?"
- "Can I refinance my existing loans?"
- "What happens if I repay 5,000 RON early?"
- "Can I reduce my monthly installment?"
- "I might not be able to pay next month's installment."
- "Why is my application waiting for review?"
- "Can you explain this clause in my loan agreement?"

The assistant should classify customer intent, retrieve relevant information, identify missing data, choose appropriate tools, invoke authorized services, maintain conversational context, and explain results.

The assistant must not invent customer data, product conditions, interest rates, eligibility results, or transaction outcomes.

When information is missing or uncertain, it must ask a clarifying question, retrieve the necessary information, or escalate the issue.

The assistant should not be implemented as a collection of unrelated, hardcoded conversational scripts. It should use a shared orchestration layer with reusable tools and specialized workflows.

### 4.2 New Loan Origination

The loan application workflow must support:

1. Customer requests a loan.
2. AI identifies the requested amount, duration, product, and preferences.
3. System retrieves available customer information.
4. System identifies missing information and requests it.
5. Relevant banking policies are retrieved through RAG.
6. Authorized services perform preliminary eligibility checks.
7. Customer provides supporting documents where required.
8. Documents are extracted and validated.
9. Financial affordability calculations are performed.
10. The system retrieves or calculates eligible loan scenarios.
11. The customer compares the available options.
12. AI prepares an application summary.
13. Customer reviews the information and explicitly confirms submission.
14. Application enters the human review workflow.
15. Reviewer approves, rejects, or requests additional information.
16. Customer is notified of the outcome.
17. Approved applications proceed to the appropriate signing and disbursement workflow.

The prototype may simulate contract signing and disbursement. It must not claim that a real loan has been approved, signed, or funded.

### 4.3 Refinancing and Debt Consolidation

The assistant must support refinancing requests involving existing loans.

Possible customer goals include:

- Replacing an existing loan with a new loan.
- Consolidating several loans into one.
- Reducing monthly installments.
- Reducing total interest costs.
- Changing the repayment period.
- Refinancing existing debts while requesting additional funds, where the product permits it.

The workflow must:

- Collect information about existing loans.
- Record outstanding balances and monthly installments.
- Request payoff statements or additional documentation when needed.
- Obtain verified payoff amounts from an appropriate service where available.
- Calculate the required refinancing amount.
- Compare existing obligations with proposed refinancing scenarios.
- Include applicable interest, fees, insurance, and repayment duration.
- Explain the difference between monthly affordability and total repayment cost.
- Prepare and submit the refinancing application after customer confirmation.
- Route the application to a human reviewer.
- Simulate settlement of existing loans and closure confirmation.

The system must not assume that refinancing is always beneficial. It should present transparent comparisons and explain relevant trade-offs.

### 4.4 Loan Servicing and Early Repayment

The assistant must support existing loan management requests.

Supported scenarios include:

- Partial early repayment.
- Full early repayment.
- Reducing the monthly installment after a partial repayment.
- Reducing the repayment period after a partial repayment.
- Requesting a repayment-period extension.
- Exploring restructuring or payment deferral options.
- Checking outstanding balances, repayment schedules, and next payment dates.

All calculations must use deterministic financial services.

For a full early repayment, the application must retrieve the authoritative settlement amount for the relevant date rather than estimate it from the principal balance.

Before any financial operation is executed, the system must verify eligibility, authorization, required customer confirmation, and any applicable human approval requirements.

A successful request must not be reported as completed until the responsible banking service confirms the outcome.

### 4.5 Financial Early-Warning Assistant

Introduce a feature that can identify potential financial difficulties before they become missed payments.

With appropriate customer consent and access to the relevant information, the system may compare expected income, available balances, known payment obligations, and customer-provided financial assumptions.

It can identify potential shortfalls, explain the information supporting its estimates, and simulate possible responses.

For example:

"Based on the income and scheduled payments currently available, your expected balance may fall below the amount required for your next installment."

The system can then help the customer explore budgeting changes, repayment simulations, or contact with a bank representative.

This feature must clearly distinguish estimates from verified facts and must not guarantee future financial outcomes.

### 4.6 Life-Event Financial Simulator

Allow customers to evaluate hypothetical financial scenarios before committing to new obligations.

Examples include:

- Buying a car.
- Moving to a different home.
- Experiencing a temporary reduction in income.
- Taking on a new monthly expense.
- Comparing different loan durations.
- Making an early repayment.
- Refinancing existing credit obligations.

Customers should be able to adjust assumptions and compare the impact on monthly cash flow, debt obligations, and projected total repayment costs.

The calculator must use explicit assumptions and deterministic calculations, not language-model-generated arithmetic.

### 4.7 Loan Contract Assistant

The system should process uploaded loan agreements and help customers understand their contractual obligations.

Possible functionality includes:

- Extracting important terms.
- Identifying interest rates, fees, repayment schedules, and relevant dates.
- Explaining clauses in plain language.
- Comparing a contract clause with the applicable policy or product documentation.
- Highlighting uncertainty and potential inconsistencies.
- Answering questions using references to the relevant document sections.

The assistant must distinguish an explanation from legal advice and must not replace authoritative banking calculations or contractual interpretations.

### 4.8 Application Recovery Assistant

When an application is rejected, incomplete, or blocked, the assistant should help the customer understand the next available steps.

It may:

- Identify missing or inconsistent information.
- Explain communicated reasons for a decision.
- Request corrected documents.
- Help submit a request to correct potentially inaccurate personal or credit information.
- Prepare a clarification request.
- Route the case for human review.
- Track the result of the follow-up process.

The assistant must not invent rejection reasons, promise future approval, or automatically submit a new application without appropriate customer confirmation.

### 4.9 Human Support and Escalation

The customer must be able to request human assistance at any point.

The assistant should transfer the relevant conversation context, application status, supporting evidence references, and unresolved questions to the authorized representative.

The customer should be informed when a case has been handed over and whether additional action is required from them.

## 5. Frontend Architecture

Build two connected interfaces with different design requirements.

### 5.1 Customer Application

Use a mobile-first, responsive interface with a clean, modern fintech design.

Suggested technologies:

- Next.js.
- React.
- TypeScript.
- Tailwind CSS.
- A reusable component library such as shadcn/ui.

The customer application should contain:

#### Home / Financial Dashboard

- Greeting and personalized overview.
- Relevant account and loan information available to the current user.
- Upcoming payment information.
- Active application status.
- AI assistant entry point.
- Quick actions for credit applications, refinancing, repayment simulations, and support.
- Optional alerts or financial insights based on available data.

#### AI Assistant Interface

- Natural-language chat.
- Suggested questions and contextual actions.
- Rich response cards for calculations and comparisons.
- Document upload and status display.
- Source references for policy-based answers.
- Clear confirmations before important actions.
- Application status updates and access to human support.

The assistant should not be limited to a full-screen text conversation. It should present structured information when useful, including tables, comparison cards, progress indicators, document status, and repayment simulations.

#### Loan and Application Pages

- Available credit products.
- Loan simulation.
- Application form and document checklist.
- Application progress timeline.
- Existing loan overview.
- Refinancing comparison.
- Early repayment simulation.
- Contract information.
- Notification history.

### 5.2 Staff / Reviewer Dashboard

Build a separate desktop-oriented interface.

It should include:

- Application queue.
- Filters and search.
- Application detail view.
- Customer and financial information.
- Document preview and verification status.
- Eligibility and affordability results.
- Policy references.
- AI-generated summaries clearly labeled as such.
- Reviewer notes.
- Request-information workflow.
- Approve and reject actions, subject to permissions.
- Audit history.
- Application status tracking.

Approval and rejection actions must require appropriate authorization and be recorded in the backend.

The interface should display evidence and relevant context rather than relying only on an AI-generated summary.

### 5.3 UX Principles

The user experience must prioritize:

- Clear hierarchy and readability.
- Mobile responsiveness.
- Accessible color contrast and keyboard navigation.
- Plain-language explanations.
- Transparent fees and financial calculations.
- Clear status indicators.
- Predictable navigation.
- Visible privacy and security controls.
- Easy access to human assistance.

Use realistic fintech design references for inspiration, but do not copy a bank's branding or imply an official partnership.

## 6. Backend Architecture

Use Python and FastAPI for the initial backend.

Start with a **modular monolith** rather than many microservices. Each module should have a clear responsibility and well-defined interfaces so it can be separated later if needed.

The main logical modules should be:

1. API and authentication integration.
2. AI orchestration.
3. RAG and knowledge retrieval.
4. Customer profile integration.
5. Document processing.
6. Eligibility and business rules.
7. Financial calculation and simulation.
8. Application workflow management.
9. Loan servicing and refinancing.
10. Human review.
11. Notification management.
12. Audit logging and monitoring.

Frontend clients must communicate with the backend through authenticated API endpoints.

The LLM must not have unrestricted database access or direct permission to perform financial operations.

Instead, the orchestrator should invoke narrowly scoped backend tools that validate inputs, check permissions, enforce business rules, and return structured results.

## 7. AI Orchestration Layer

The AI orchestrator is responsible for coordinating the tools and workflows.

Its responsibilities include:

- Intent classification.
- Conversation context management.
- Customer request interpretation.
- Tool selection.
- Retrieval of policy information.
- Identification of missing data.
- Calling document-processing and calculation services.
- Coordinating application workflows.
- Explaining the results returned by other services.
- Requesting customer confirmation.
- Escalating cases to human reviewers.

The orchestrator should operate through a defined set of tools, such as:

- `get_customer_profile`
- `get_customer_loans`
- `search_banking_policies`
- `get_required_documents`
- `validate_document`
- `run_eligibility_check`
- `calculate_loan_offer`
- `simulate_early_repayment`
- `compare_refinancing_options`
- `create_loan_application`
- `submit_application`
- `get_application_status`
- `request_human_review`
- `create_customer_notification`

These are proposed logical tool names, not existing banking APIs.

Every tool must have a defined input schema, output schema, authorization requirements, error handling, and permitted workflow states.

The backend must independently validate each tool call. The LLM's interpretation must never override backend authorization or business rules.

## 8. Retrieval-Augmented Generation (RAG)

The knowledge system must answer banking-policy and product questions using approved documentation.

Documents may include:

- Credit product terms.
- Eligibility requirements.
- Pricing policies.
- Fees and commissions.
- Required documents.
- Refinancing conditions.
- Early repayment rules.
- Restructuring procedures.
- Contractual explanations.
- Frequently asked questions.

The ingestion workflow should include:

1. Document upload.
2. Text extraction.
3. Cleaning and normalization.
4. Chunking.
5. Metadata extraction.
6. Embedding generation.
7. Vector indexing.
8. Retrieval and relevance filtering.
9. Source-aware answer generation.

Each document and indexed chunk should retain source, version, effective date, product, and other relevant metadata.

The retrieval system should prioritize applicable and current documentation. Outdated or conflicting documents must be identified rather than silently combined.

Answers about product rules should include references to the supporting sources where possible.

RAG is responsible for retrieving and explaining information. It must not independently approve loans or perform authoritative financial calculations.

## 9. Document Processing

Create a document-processing pipeline that supports:

- File upload.
- File type and size validation.
- Document classification.
- OCR for scanned documents.
- Structured field extraction.
- Data normalization.
- Completeness checks.
- Cross-document consistency checks.
- Verification status tracking.
- Secure document storage.

Start with a simple OCR solution or mocked extraction service for the prototype.

Document authenticity checks, identity verification, and external data comparisons should be clearly distinguished from OCR extraction.

Extracted values should retain their provenance, including the original file reference, page or location where available, extraction confidence, and verification status.

Documents must be treated as untrusted input. Embedded instructions in an uploaded document must never influence the AI's system instructions or authorization decisions.

## 10. Eligibility and Credit Decision Architecture

Separate preliminary screening from authoritative credit decisions.

The architecture should include:

### Preliminary Eligibility Service

Evaluates configured minimum requirements using available and verified data.

It can return:

- Preliminary requirements satisfied.
- Preliminary requirements not satisfied.
- Additional information required.
- Manual review required.

### Financial Assessment Service

Performs deterministic checks involving configured income, existing obligations, affordability, and relevant credit conditions.

### Credit Decision Integration

The production architecture should call an authorized bank decision service or approved credit-scoring system.

The prototype should use a configurable rules engine and synthetic data.

The LLM must not generate a credit approval or rejection from its own reasoning.

All decision results should contain a status, relevant reasons, supporting evidence references, policy version, and timestamp where available.

The system should distinguish an initial eligibility assessment from final credit approval.

## 11. Financial Calculation Engine

Implement a deterministic financial calculation module independent of the LLM.

It should support:

- Loan installment calculations.
- Interest and repayment schedules.
- Total repayment costs.
- Fee and insurance inclusion where applicable.
- Comparison of repayment durations.
- Partial early repayment simulations.
- Full early repayment estimates.
- Refinancing comparisons.
- Cash-flow scenario simulations.

Use decimal-safe financial arithmetic, currency-specific rounding rules, explicit assumptions, and automated tests.

The engine must distinguish principal balance, settlement amount, interest, fees, and total repayment.

For real financial operations, use authoritative bank pricing or settlement APIs rather than a local estimate.

Every displayed simulation should identify its assumptions and make clear whether it is indicative or authoritative.

## 12. Application Workflow Engine

The application workflow must be persistent and independent of conversation memory.

A standard loan application may use states such as:

- `DRAFT`
- `AWAITING_DOCUMENTS`
- `PRELIMINARY_ASSESSMENT`
- `READY_FOR_SUBMISSION`
- `PENDING_HUMAN_REVIEW`
- `MORE_INFORMATION_REQUIRED`
- `APPROVED`
- `REJECTED`
- `AWAITING_SIGNATURE`
- `COMPLETED`
- `CANCELLED`

The system must define valid transitions, required evidence, authorization requirements, and permitted operations for each state.

Refinancing, early repayment, and restructuring should have appropriate specialized workflows rather than being forced into one identical sequence.

Applications must survive browser refreshes, backend restarts, and interrupted conversations.

Repeated requests must not accidentally create duplicate applications or execute the same financial action more than once.

Use idempotency keys for operations that may be retried.

## 13. Human-in-the-Loop Decision Process

Human review is a central system capability, not an optional chat feature.

For the prototype, every new credit application must be reviewed by an authorized human before the final credit decision is recorded.

The customer can prepare and submit an application through the AI, but the system must require explicit submission confirmation.

The reviewer may:

- Approve the application.
- Reject the application.
- Request additional information.
- Escalate the case when appropriate.

The agent should explain the recorded outcome and continue the workflow.

Approval, signing, and disbursement must be separate stages.

A human approval must not automatically imply that a contract has been signed or that funds have been transferred.

For real banking integrations, the exact review requirements must be configurable according to the applicable product, banking policy, authorization rules, and regulatory requirements.

Operations such as early repayment may follow a different authorization path from loan approval, depending on the applicable banking procedures.

## 14. Database Architecture

Use PostgreSQL, preferably through Supabase for the initial prototype.

Suggested logical entities include:

- `users`
- `user_profiles`
- `roles`
- `customer_financial_profiles`
- `bank_products`
- `product_policy_versions`
- `loan_accounts`
- `loan_applications`
- `application_status_history`
- `application_documents`
- `document_verification_results`
- `eligibility_assessments`
- `loan_offers`
- `loan_simulations`
- `refinancing_requests`
- `repayment_requests`
- `human_reviews`
- `review_notes`
- `conversation_sessions`
- `conversation_messages`
- `notifications`
- `audit_events`
- `knowledge_documents`
- `knowledge_document_versions`
- `knowledge_chunks`

The schema is conceptual and should be refined before migrations are created.

Use relational constraints, foreign keys, appropriate indexes, database migrations, and explicit ownership relationships.

Customer records must be isolated so that one customer cannot access another customer's financial data or documents.

Staff access must be restricted by role and assigned permissions.

Enable row-level security where applicable, particularly for customer-facing access to Supabase-managed data.

Conversation messages and audit events should not be treated as substitutes for authoritative application records.

## 15. Cloud and Deployment Strategy

The prototype should aim to operate at zero cost using currently available free tiers, but permanent zero-cost operation is not guaranteed.

Suggested initial technologies:

- **Frontend:** Next.js, React, TypeScript, Tailwind CSS.
- **Frontend hosting:** Vercel free tier, subject to its current limits.
- **Backend:** Python, FastAPI.
- **Backend hosting:** Render free tier or another suitable free hosting alternative.
- **Database:** Supabase PostgreSQL.
- **Vector search:** PostgreSQL with pgvector.
- **File storage:** Supabase Storage.
- **AI model:** A provider-agnostic adapter, initially connecting to an available LLM API with an appropriate free quota.
- **Document processing:** Python OCR and extraction libraries.
- **Version control:** Git and GitHub.
- **Configuration:** Environment variables for secrets and provider credentials.

The architecture must isolate provider-specific details so the hosting provider, LLM, database features, or external integrations can be changed later.

The application must not depend on ephemeral local storage for persistent customer data or application state.

Monitor resource consumption, quotas, cold starts, storage limits, and provider-specific terms.

Production use may require paid infrastructure, contractual data-protection guarantees, stronger operational controls, and approved bank integrations.

## 16. Security, Privacy, and Auditability

Security must be designed into the system from the beginning.

Include:

- Authentication and session management.
- Role-based authorization.
- Customer-specific data isolation.
- Secure handling of API keys and secrets.
- Transport encryption.
- Input validation.
- Upload restrictions.
- Rate limiting.
- Protection against prompt injection.
- Tool authorization.
- Audit logging.
- Error handling that avoids leaking personal information.
- Data retention and deletion policies.
- Appropriate consent for accessing financial data.
- Traceability of decisions, calculations, and important operations.

Use only synthetic customer data and fabricated documents in the initial public-cloud prototype.

Do not upload real national identification numbers, bank statements, credit bureau reports, personal financial documents, or real customer credentials to free-tier AI services.

Audit events should record the actor, action, relevant object, timestamp, result, and associated workflow or correlation identifier where appropriate.

Sensitive financial operations must require explicit customer confirmation and backend authorization.

## 17. Monitoring and Reliability

Add structured application logging and health checks.

The backend should expose a health endpoint and report the availability of required dependencies.

Monitor:

- API errors.
- Failed document processing.
- LLM failures and quota exhaustion.
- Database connectivity.
- Application state transition failures.
- Failed or duplicated actions.
- Pending human reviews.
- Processing delays.

External service failures must not silently produce successful application states.

Implement timeouts, bounded retries, and clear recovery paths.

For operations that must survive long waits or system restarts, store their status durably rather than relying on in-memory background tasks.

## 18. Recommended Development Phases

### Phase 1: Foundation

- Repository structure.
- Frontend application.
- Backend API.
- Supabase database.
- Authentication.
- Customer and reviewer roles.
- Basic dashboard.
- Health checks.
- Synthetic seed data.

### Phase 2: Conversational AI

- Chat interface.
- LLM integration.
- Intent classification.
- Tool-calling architecture.
- Conversation persistence.
- Error handling.
- Basic application context.

### Phase 3: RAG Knowledge Base

- Document ingestion.
- Chunking and embeddings.
- Vector retrieval.
- Document versioning.
- Source citations.
- Banking-policy questions.

### Phase 4: Loan Origination

- Product configuration.
- Preliminary eligibility rules.
- Financial calculator.
- Application creation.
- Document upload and extraction.
- Submission confirmation.
- Persistent workflow.

### Phase 5: Human Review

- Staff dashboard.
- Application queue.
- Evidence inspection.
- Approve, reject, and request-information actions.
- Customer notifications.
- Audit history.

### Phase 6: Loan Servicing and Refinancing

- Early repayment simulations.
- Refinancing comparisons.
- Repayment-period change requests.
- Restructuring requests.
- Contract assistant.
- Application recovery workflows.

### Phase 7: Proactive Financial Assistance

- Financial scenario simulator.
- Early-warning estimates.
- Customer-configurable notifications.
- Explainable financial insights.

### Phase 8: Hardening and Deployment

- Security review.
- Automated tests.
- Authorization tests.
- Workflow recovery tests.
- Database migration validation.
- Usage-limit monitoring.
- Deployment documentation.
- Demo environment.

## 19. Testing Requirements

The application must be tested with realistic synthetic scenarios.

Include tests for:

- Eligible and ineligible applicants.
- Missing or inconsistent information.
- Invalid document formats.
- Incorrectly extracted values.
- Conflicting policy versions.
- Unsupported customer requests.
- LLM hallucination prevention.
- Unauthorized customer access.
- Reviewer permission boundaries.
- Failed and repeated API calls.
- Duplicate submission prevention.
- Rejected applications.
- Requests for additional information.
- Refinancing comparisons.
- Early repayment calculations.
- Interrupted and resumed workflows.
- Database or LLM service downtime.

Financial formulas should have deterministic unit tests with known expected results.

Critical authorization and workflow rules must be tested independently of the LLM.

## 20. Definition of a Successful MVP

The first complete prototype should demonstrate one end-to-end journey:

1. A synthetic customer logs in.
2. The customer asks the AI for a personal loan.
3. The AI retrieves product conditions from the knowledge base.
4. It collects missing information.
5. The application performs a preliminary eligibility assessment.
6. A deterministic calculator returns loan simulations.
7. The customer selects a scenario.
8. The AI prepares the application.
9. The customer explicitly confirms submission.
10. The application enters the reviewer dashboard.
11. A reviewer requests additional information.
12. The AI informs the customer and collects the missing document.
13. The application returns to the reviewer.
14. The reviewer records a final decision.
15. The customer sees the updated application status.
16. The system preserves the full audit and status history.

The prototype should also demonstrate at least one refinancing or early repayment simulation using synthetic data.

No real loan approval, credit bureau inquiry, contract execution, payment, or disbursement should occur in the MVP.

## 21. Working Principles for Implementation

Treat this specification as the project's source of truth.

Before writing substantial implementation code:

1. Review the requirements and identify architectural gaps.
2. Propose the system architecture and explain component responsibilities.
3. Define the repository structure.
4. Design the core database entities and relationships.
5. Define the API contracts and application state transitions.
6. Identify external dependencies and their free-tier limitations.
7. Create a phased implementation plan.
8. Establish an initial set of automated tests.

Implement the project in small, verifiable increments.

Prefer simple, maintainable solutions over unnecessary infrastructure. Start with a modular monolith and introduce additional services only when justified.

Use typed interfaces, schema validation, clear error handling, migrations, automated tests, and concise technical documentation.

Do not hardcode production banking rules into the AI prompts. Keep configurable business rules and product data in appropriate backend services.

Do not treat mock integrations as real banking connections. Clearly label all simulated decisions, data, and transactions.

Whenever a provider, library, or free-tier limitation is relevant, verify its current documentation instead of assuming that it has remained unchanged.

The immediate objective is to build a credible, extensible banking AI prototype that demonstrates real workflow orchestration, grounded answers, deterministic financial calculations, persistent state, and human-controlled decisions.

**The long-term vision is a reusable AI platform that helps customers navigate the entire lifecycle of credit while preserving transparency, customer control, and appropriate banking oversight.**