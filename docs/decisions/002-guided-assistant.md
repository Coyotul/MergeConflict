# Guided assistant interaction

The owner's latest UX clarification makes the assistant the primary entry point:

1. **I want a loan** -> personal loan, mortgage or car loan -> amount and duration -> deterministic synthetic quote -> document checklist -> explicit submission confirmation.
2. **Change my current loan** -> partial early repayment, refinancing, or lower-payment options. Full settlement/financial execution is not available in the prototype.
3. **My current loan details** -> synthetic balance, installment, next due date, repayment schedule and contract help.
4. A free-text composer is always available, including during guided flows. Buttons append normal conversational requests to the same persisted conversation and use the same demo intent/tool boundary. They are not separate disconnected scripts.

A visible Back to options action reopens the three primary choices without deleting the conversation or application. Mortgage and car products use explicitly synthetic configurations, with no bank-specific branding or unsupported promises. The current adapter is rule-based, not an LLM; ambiguous messages request clarification.
