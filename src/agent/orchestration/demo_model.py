"""Deterministic demo chat model for mock mode (ORCHESTRATOR_MODEL=fake).

It reads the last CONTEXT_JSON system message and the current turn's history
and returns one action JSON, following a few fixed rules on the first need.
It is not a classifier: it only exercises every screen of the chat API.
Values it proposes are parsed with fields.parse_field_value (types and enum
options from CONTEXT_JSON needs); replies that summarise tool results take their values from
CONTEXT_JSON (or, for passages and product names, from the tool result).
"""
import json
import re
from typing import Any

from src.agent.orchestration.fields import DISCOVERY_FIELDS, FieldValueError, parse_field_value, parse_money
from src.integrations.llm.chat import ChatMessage
from src.models.credit import FieldSpec, FieldType

CONTEXT_PREFIX = "CONTEXT_JSON:"
_TOOL_PREFIXES = ("TOOL_RESULT ", "TOOL_REJECTED ")
_EVENT_PREFIX = "EVENT: "
_TOOL_LINE = re.compile(r"^(TOOL_RESULT|TOOL_REJECTED) (\w+): ?(.*)$", re.DOTALL)
_CREDIT_WORDS = re.compile(r"\b(?:credit\w*|loan\w*|împrumut\w*|imprumut\w*)", re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d.,]*")
_YES = {"da", "yes", "ok", "corect", "correct"}
OFFER_TERM_OPTIONS = [36, 48]

# ---- texts ------------------------------------------------------------------

T: dict[str, dict[str, str]] = {
    "greeting": {
        "ro": "Bună! Sunt asistentul tău pentru credite (mod demonstrativ, date simulate). "
              "Te pot ajuta cu o cerere de credit sau cu informații despre produse.",
        "en": "Hi! I'm your credit assistant (demo mode, simulated data). "
              "I can help you apply for a loan or answer product questions.",
    },
    "start_application": {
        "ro": "Sigur, te ajut cu cererea de credit. Spune-mi scopul creditului, suma dorită și perioada (în luni). "
              "Începem cu scopul: pentru ce ai nevoie de credit?",
        "en": "Sure, I'll help you apply. I need the purpose, the amount and the term (in months). "
              "Let's start with the purpose: what is the loan for?",
    },
    "more": {
        "ro": "Poți să-mi spui mai multe? Te pot ajuta cu o cerere de credit sau cu informații despre produse.",
        "en": "Could you tell me more? I can help you apply for a loan or answer product questions.",
    },
    "ask_field": {"ro": "Te rog să-mi spui: {label}.", "en": "Please tell me: {label}."},
    "options": {"ro": " Variante: {options}.", "en": " Options: {options}."},
    "invalid_value": {
        "ro": "Valoarea nu pare corectă.", "en": "That value doesn't look right.",
    },
    "thanks": {"ro": "Mulțumesc.", "en": "Thank you."},
    "ready_for_check": {
        "ro": "Am toate datele pentru o verificare preliminară (simulată, pe baza condițiilor publice). "
              "Scrie „ok” ca s-o rulez sau încarcă documentele: {documents}.",
        "en": "I have everything for a preliminary check (simulated, based on public conditions). "
              "Reply \"ok\" to run it, or upload your documents: {documents}.",
    },
    "ready_for_check_no_docs": {
        "ro": "Am toate datele pentru o verificare preliminară (simulată, pe baza condițiilor publice). "
              "Scrie „ok” ca s-o rulez.",
        "en": "I have everything for a preliminary check (simulated, based on public conditions). "
              "Reply \"ok\" to run it.",
    },
    "choose_product": {
        "ro": "Ce tip de credit te interesează?", "en": "Which kind of loan are you interested in?",
    },
    "product_chosen": {
        "ro": "Pentru scopul tău am ales produsul {name}.", "en": "For your purpose I picked {name}.",
    },
    "profile_loaded": {
        "ro": "Am preluat numele și vârsta din profilul tău.", "en": "I took your name and age from your profile.",
    },
    "upload": {"ro": "Te rog încarcă: {documents}.", "en": "Please upload: {documents}."},
    "upload_detail": {
        "ro": "Documentul {label} nu a putut fi folosit: {detail}", "en": "Your {label} could not be used: {detail}",
    },
    "confirm_values": {
        "ro": "Te rog verifică valorile din documente: {items}. Răspunde „da” dacă valorile din documente sunt corecte.",
        "en": "Please check the values from your documents: {items}. Reply \"yes\" if the document values are correct.",
    },
    "conflict_item": {
        "ro": "{label}: documentul arată {document}, tu ai spus {customer}",
        "en": "{label}: the document shows {document}, you said {customer}",
    },
    "eligibility": {
        "ro": "Rezultatul verificării preliminare (simulat, pe baza condițiilor publice): {status}.",
        "en": "Preliminary check result (simulated, based on public conditions): {status}.",
    },
    "offers": {
        "ro": "Ofertele (simulate, pe baza condițiilor publice): {items}.",
        "en": "Your offers (simulated, based on public conditions): {items}.",
    },
    "offer_item": {
        "ro": "{term} luni: rată lunară {installment} RON, cost total {total_cost} RON",
        "en": "{term} months: monthly installment {installment} RON, total cost {total_cost} RON",
    },
    "choose_offer": {
        "ro": "Alege una dintre oferte din listă.", "en": "Please choose one of the offers in the list.",
    },
    "confirm_submission": {
        "ro": "Verifică rezumatul cererii și confirmă-l când ești gata. Nu trimit nimic fără confirmarea ta.",
        "en": "Please review the application summary and confirm it when you're ready. "
              "Nothing is sent without your confirmation.",
    },
    "not_eligible": {
        "ro": "Cu aceste date nu sunt îndeplinite condițiile preliminare. Poți modifica suma sau perioada, "
              "sau pot cere ajutorul unui consultant.",
        "en": "With these details the preliminary conditions are not met. You can change the amount or the term, "
              "or I can ask a human advisor to help.",
    },
    "manual_review": {
        "ro": "Cazul tău are nevoie de analiza unui consultant. Pot cere acum ajutorul unui consultant.",
        "en": "Your case needs a review by a human advisor. I can ask an advisor to help now.",
    },
    "escalated": {
        "ro": "Un consultant va analiza cazul tău și te va contacta.",
        "en": "A human advisor will review your case and contact you.",
    },
    "submitted": {
        "ro": "Cererea ta a fost trimisă spre analiză unui consultant. Referința ei este {id}. "
              "Nu s-a luat încă nicio decizie; vei fi informat separat.",
        "en": "Your application was sent to a human advisor for review. Its reference is {id}. "
              "No decision has been made yet; you will be informed separately.",
    },
    "doc_accepted": {"ro": "Am primit documentul ({doc_type}).", "en": "We received your document ({doc_type})."},
    "doc_rejected": {
        "ro": "Nu am putut folosi documentul ({doc_type}): {reason}",
        "en": "We couldn't use your document ({doc_type}): {reason}",
    },
    "offer_selected": {"ro": "Ai ales varianta pe {term} luni.", "en": "You chose the {term}-month option."},
    "offer_rejected": {
        "ro": "Această ofertă nu mai este disponibilă.", "en": "That offer is no longer available.",
    },
    "summary_changed": {
        "ro": "Rezumatul confirmat nu mai este actual, așa că nu am trimis nimic.",
        "en": "The summary you confirmed is no longer current, so nothing was submitted.",
    },
    "declined": {
        "ro": "Bine, nu am trimis nimic. Poți modifica orice detaliu.",
        "en": "OK, nothing was submitted. You can change any detail.",
    },
    "not_submitted": {
        "ro": "Cererea nu a fost trimisă din cauza unei probleme tehnice. Te rog să încerci din nou.",
        "en": "Your application was not submitted because of a technical problem. Please try again.",
    },
    "tool_failed": {
        "ro": "Nu am putut finaliza un pas acum.", "en": "I couldn't complete a step right now.",
    },
    "passage": {"ro": "Conform {publisher}: {header}. {text}", "en": "According to {publisher}: {header}. {text}"},
    "no_evidence": {
        "ro": "Nu am găsit suficiente informații în sursele disponibile. Pot cere ajutorul unui consultant.",
        "en": "I couldn't find enough evidence in the available sources. I can ask a human advisor to help.",
    },
}

_ELIGIBILITY_STATUS = {
    "satisfied": {"ro": "condițiile preliminare sunt îndeplinite", "en": "the preliminary conditions are met"},
    "not_satisfied": {"ro": "condițiile preliminare nu sunt îndeplinite", "en": "the preliminary conditions are not met"},
    "manual_review": {"ro": "este necesară analiza unui consultant", "en": "a human advisor needs to review it"},
    "more_information_required": {"ro": "mai am nevoie de câteva informații", "en": "I need a few more details"},
}

_TOOL_FOR_NEED = {
    "choose_product": "get_credit_products",
    "run_eligibility": "run_eligibility_check",
    "run_offers": "calculate_loan_offer",
}


def _text(key: str, lang: str, **values: Any) -> str:
    return T[key][lang].format(**values)


def _stem_match(a: str, b: str) -> bool:
    return a == b or (len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6])


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^\w]+", text.lower()) if w]


class _Turn:
    """What the model sees this step: CONTEXT_JSON, the trigger and this turn's tool results."""

    def __init__(self, messages: list[ChatMessage]):
        self.context: dict[str, Any] = {}
        for m in reversed(messages):
            if m.role == "system" and m.content.startswith(CONTEXT_PREFIX):
                self.context = json.loads(m.content[len(CONTEXT_PREFIX):])
                break
        convo = [m for m in messages if m.role != "system"]
        trigger_at = -1
        for i in range(len(convo) - 1, -1, -1):
            if convo[i].role == "user" and not convo[i].content.startswith(_TOOL_PREFIXES):
                trigger_at = i
                break
        trigger = convo[trigger_at].content if trigger_at >= 0 else ""
        self.event = trigger[len(_EVENT_PREFIX):] if trigger.startswith(_EVENT_PREFIX) else None
        self.customer_text = None if self.event is not None or trigger_at < 0 else trigger
        after = convo[trigger_at + 1:]
        # Code may log a failed code-tool result before the first model step.
        self.first_step = not any(m.role == "assistant" for m in after)
        self.tools: dict[str, dict | None] = {}  # name -> output (None when rejected)
        for m in after:
            match = _TOOL_LINE.match(m.content) if m.role == "user" else None
            if match:
                kind, name, payload = match.groups()
                self.tools[name] = json.loads(payload) if kind == "TOOL_RESULT" else None

        self.lang: str = self.context.get("language") or "ro"
        self.needs: list[dict] = self.context.get("needs") or []
        self.has_application = self.context.get("stage") is not None
        self.notices: list[str] = self.context.get("notices") or []

    @property
    def updates_rejected(self) -> bool:
        return any(n.startswith("FIELD_UPDATES_REJECTED") for n in self.notices)


class DemoChatModel:
    """Scripted ChatModel for mock mode: same inputs, same output."""

    def __init__(self):
        # Discovery limits are known up front; other fields are validated by the
        # orchestrator, and a rejected value makes this model ask again.
        self._discovery = {spec.name: spec for spec in DISCOVERY_FIELDS}

    def complete(self, messages: list[ChatMessage]) -> str:
        turn = _Turn(messages)
        intent, updates, action = self._decide(turn)
        return json.dumps(
            {"intent": intent, "field_updates": updates, "action": action}, ensure_ascii=False
        )

    # ---- decision ---------------------------------------------------------

    def _decide(self, t: _Turn) -> tuple[str, list[dict], dict]:
        lang = t.lang
        if t.event == "SESSION_STARTED":
            return "other", [], _respond(_text("greeting", lang))
        if t.event and t.event.split()[0] in ("APPLICATION_SUBMITTED", "ALREADY_SUBMITTED"):
            return "application_status", [], _respond(_text("submitted", lang, id=t.event.split()[1]))

        intent = "credit_application" if t.has_application else "product_info"
        if "search_banking_policies" in t.tools:
            return intent, [], self._answer_question(t)
        if t.customer_text and t.first_step and t.customer_text.rstrip().endswith("?"):
            return intent, [], _call("search_banking_policies", {"text": t.customer_text})

        if not t.has_application:
            if t.customer_text and _CREDIT_WORDS.search(t.customer_text):
                return "credit_application", [], _respond(_text("start_application", lang))
            return "unclear", [], _respond(_text("more", lang))
        return self._application_step(t)

    def _answer_question(self, t: _Turn) -> dict:
        output = t.tools["search_banking_policies"] or {}
        passages = output.get("passages") or []
        parts: list[str] = []
        citations: list[str] = []
        if output.get("status") == "ok" and passages:
            first = passages[0]
            parts.append(_text("passage", t.lang, publisher=first["publisher"], header=first["header"],
                               text=first["text"]))
            citations.append(first["citation_id"])
        else:
            parts.append(_text("no_evidence", t.lang))
        if t.has_application and t.needs:
            parts.append(self._ask(t, t.needs[0]))
        return _respond(" ".join(parts), citations)

    def _application_step(self, t: _Turn) -> tuple[str, list[dict], dict]:
        intent = "credit_application"
        if not t.needs:
            return intent, [], _respond(self._reply(t, None))
        first = t.needs[0]
        kind = first["kind"]

        if kind == "missing_field" and t.customer_text and t.first_step and not t.updates_rejected:
            value = self._extract(first, t.customer_text)
            if value is not None:
                updates = [{"field": first["target"], "value": value}]
                following = t.needs[1] if len(t.needs) > 1 else None
                if following is not None and following["kind"] == "choose_product":
                    return intent, updates, _call("get_credit_products", {})
                text = _text("thanks", t.lang)
                if following is not None:
                    text += " " + self._ask(t, following)
                return intent, updates, _respond(text)

        if kind in ("confirm_extracted", "resolve_conflict") and t.customer_text and t.first_step:
            if " ".join(_words(t.customer_text)) in _YES:
                updates = [
                    {"field": n["target"], "confirm": True}
                    for n in t.needs if n["kind"] in ("confirm_extracted", "resolve_conflict")
                ]
                return intent, updates, _call("run_eligibility_check", {})

        if kind == "choose_product" and "get_credit_products" in t.tools:
            product = self._pick_product(t)
            if product is not None and "get_customer_profile" not in t.tools:
                return intent, [{"field": "product_code", "value": product["code"]}], _call("get_customer_profile", {})

        tool = _TOOL_FOR_NEED.get(kind)
        if tool is not None and tool not in t.tools:
            arguments = {"term_options_months": OFFER_TERM_OPTIONS} if tool == "calculate_loan_offer" else {}
            return intent, [], _call(tool, arguments)

        return intent, [], _respond(self._reply(t, first))

    # ---- replies ----------------------------------------------------------

    def _reply(self, t: _Turn, need: dict | None) -> str:
        parts = [p for p in (self._event_ack(t), *self._tool_summaries(t)) if p]
        if need is not None:
            if t.updates_rejected and need["kind"] == "missing_field":
                parts.append(_text("invalid_value", t.lang))
            parts.append(self._ask(t, need))
        return " ".join(parts) or _text("more", t.lang)

    def _event_ack(self, t: _Turn) -> str | None:
        if t.event is None:
            return None
        lang = t.lang
        name, _, rest = t.event.partition(" ")
        if name == "DOCUMENT_PROCESSED":
            doc_type, _, outcome = rest.partition(": ")
            if outcome.startswith("accepted"):
                return _text("doc_accepted", lang, doc_type=doc_type)
            reason = next(
                (d.get("rejection_reason") for d in self._ctx_list(t, "documents") if d.get("doc_type") == doc_type),
                None,
            ) or ""
            return _text("doc_rejected", lang, doc_type=doc_type, reason=reason).rstrip(": ")
        if name == "OFFER_SELECTED":
            offer = next((o for o in self._ctx_list(t, "offers") if o.get("offer_id") == rest.strip()), None)
            return _text("offer_selected", lang, term=offer["term_months"]) if offer else None
        keys = {
            "OFFER_SELECTION_REJECTED": "offer_rejected",
            "SUMMARY_CHANGED": "summary_changed",
            "SUBMISSION_DECLINED": "declined",
            "SUBMISSION_FAILED": "not_submitted",
        }
        return _text(keys[name], lang) if name in keys else None

    def _tool_summaries(self, t: _Turn) -> list[str]:
        lang = t.lang
        parts: list[str] = []
        if any(output is None for output in t.tools.values()):
            parts.append(_text("tool_failed", lang))
        if t.tools.get("get_credit_products"):
            product = self._pick_product(t)
            if product is not None:
                parts.append(_text("product_chosen", lang, name=product["name"]))
        if t.tools.get("get_customer_profile"):
            fields = t.context.get("fields") or {}
            if any(f.get("source") == "profile" for f in fields.values()):
                parts.append(_text("profile_loaded", lang))
        eligibility = t.context.get("eligibility")
        if t.tools.get("run_eligibility_check") and eligibility:
            status = _ELIGIBILITY_STATUS.get(eligibility["status"], {}).get(lang, eligibility["status"])
            text = _text("eligibility", lang, status=status)
            if eligibility["status"] != "satisfied":
                reasons = "; ".join(r["message"] for r in eligibility.get("reasons") or [])
                if reasons:
                    text += f" {reasons}."
            parts.append(text)
        offers = self._ctx_list(t, "offers")
        if t.tools.get("calculate_loan_offer") and offers:
            items = "; ".join(
                _text("offer_item", lang, term=o["term_months"], installment=o["monthly_installment"],
                      total_cost=o["total_cost"])
                for o in offers
            )
            parts.append(_text("offers", lang, items=items))
        return parts

    def _ask(self, t: _Turn, need: dict) -> str:
        lang = t.lang
        kind = need["kind"]
        if kind == "missing_field":
            text = _text("ask_field", lang, label=need.get("label") or need.get("target"))
            if need.get("options"):
                text += _text("options", lang, options=", ".join(need["options"]))
            return text
        if kind == "choose_product":
            return _text("choose_product", lang)
        if kind == "run_eligibility":
            documents = self._document_labels(t)
            if documents:
                return _text("ready_for_check", lang, documents=", ".join(documents))
            return _text("ready_for_check_no_docs", lang)
        if kind == "document":
            text = _text("upload", lang, documents=", ".join(self._document_labels(t)))
            if need.get("detail") and not (t.event or "").startswith(f"DOCUMENT_PROCESSED {need['target']}:"):
                text = _text("upload_detail", lang, label=need.get("label"), detail=need["detail"]) + " " + text
            return text
        if kind in ("confirm_extracted", "resolve_conflict"):
            return _text("confirm_values", lang, items="; ".join(self._confirm_items(t)))
        if kind in ("choose_offer", "confirm_submission", "not_eligible", "manual_review", "escalated"):
            return _text(kind, lang)
        return _text("more", lang)

    def _confirm_items(self, t: _Turn) -> list[str]:
        fields = t.context.get("fields") or {}
        conflicts = {c["field"]: c for c in self._ctx_list(t, "conflicts")}
        items = []
        for need in t.needs:
            if need["kind"] not in ("confirm_extracted", "resolve_conflict"):
                continue
            name = need["target"]
            label = need.get("label") or name
            if name in conflicts:
                c = conflicts[name]
                items.append(_text("conflict_item", t.lang, label=label, document=c["document_value"],
                                   customer=c["customer_value"]))
            elif name in fields:
                items.append(f"{label}: {fields[name]['value']}")
        return items

    def _document_labels(self, t: _Turn) -> list[str]:
        return [n.get("label") or n["target"] for n in t.needs if n["kind"] == "document"]

    @staticmethod
    def _ctx_list(t: _Turn, key: str) -> list[dict]:
        return t.context.get(key) or []

    # ---- values -----------------------------------------------------------

    def _pick_product(self, t: _Turn) -> dict | None:
        products = (t.tools.get("get_credit_products") or {}).get("products") or []
        if not products:
            return None
        purpose = (t.context.get("fields") or {}).get("purpose", {}).get("value") or ""
        words = _words(str(purpose))
        for product in products:
            if any(_stem_match(w, p.lower()) for w in words for p in product.get("purposes") or []):
                return product
        return products[0]

    def _extract(self, need: dict, text: str) -> str | int | None:
        """A value for the need from the customer's message that passes validation, or None."""
        name = need["target"]
        spec = self._discovery.get(name)
        if spec is None:
            try:
                spec = FieldSpec(name=name, label=need.get("label") or name, type=FieldType(need["field_type"]),
                                 options=need.get("options"))
            except (KeyError, ValueError, TypeError):
                return None
        candidate: str | int | None = None
        if spec.type == FieldType.money:
            numbers = []
            for raw in _NUMBER.findall(text):
                try:
                    numbers.append((raw.rstrip(".,"), parse_money(raw.rstrip(".,"))))
                except FieldValueError:
                    continue
            big = [raw for raw, value in numbers if value >= 100]
            candidate = big[0] if big else (numbers[0][0] if numbers else None)
        elif spec.type == FieldType.integer:
            match = re.search(r"\d+", text)
            candidate = int(match.group()) if match else None
        elif spec.type == FieldType.enum:
            normalised = "_".join(_words(text))
            # longest option first, so "self employed" is not read as "employed"
            options = sorted(spec.options or [], key=len, reverse=True)
            candidate = next((o for o in options if o.lower() in normalised), None)
        else:
            candidate = text.strip()
        if candidate is None:
            return None
        try:
            parse_field_value(spec, candidate)
        except FieldValueError:
            return None
        return candidate


def _respond(message: str, citation_ids: list[str] | None = None) -> dict:
    return {"type": "respond", "message": message[:4000], "citation_ids": citation_ids or []}


def _call(tool: str, arguments: dict) -> dict:
    return {"type": "call_tool", "tool": tool, "arguments": arguments}
