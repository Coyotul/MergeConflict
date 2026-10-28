"""Field parsing and validation for the orchestrator."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from pydantic import BaseModel

from src.agent.orchestration.state import (
    ApplicationState,
    DocumentRecord,
    DocumentStatus,
    FieldConflict,
    FieldSource,
    FieldValue,
)
from src.models.credit import FieldSpec, FieldType
from src.models.knowledge import Product


# Discovery fields used before product selection
DISCOVERY_FIELDS: list[FieldSpec] = [
    FieldSpec(
        name="purpose",
        label="Purpose",
        type=FieldType.text,
        required=True
    ),
    FieldSpec(
        name="amount",
        label="Amount",
        type=FieldType.money,
        required=True,
        min=Decimal("1000"),
        max=Decimal("1000000")
    ),
    FieldSpec(
        name="term_months",
        label="Term (months)",
        type=FieldType.integer,
        required=True,
        min=Decimal("6"),
        max=Decimal("360")
    )
]


class FieldValueError(ValueError):
    """Raised when a field value cannot be parsed or is invalid."""
    pass


def field_type_to_kind(field_type: FieldType) -> str:
    """Map FieldType to FieldValue kind.

    enum values are canonical option strings, so they are stored as text.
    """
    if field_type == FieldType.enum:
        return "text"
    return field_type.value


def parse_money(raw: str | int | float | Decimal) -> Decimal:
    """Parse a monetary amount from various formats.

    Handles Romanian formats with spaces, dots, and commas as separators,
    as well as standard formats. Supports 'k' suffix for thousands.

    Args:
        raw: The value to parse (string, number)

    Returns:
        Parsed Decimal amount

    Raises:
        FieldValueError: If the value cannot be parsed
    """
    # If already a number, convert directly
    if isinstance(raw, (int, Decimal)):
        return Decimal(str(raw))
    if isinstance(raw, float):
        return Decimal(str(raw))

    if not isinstance(raw, str):
        raise FieldValueError(f"Cannot parse money from {type(raw).__name__}")

    # Lowercase and strip
    s = raw.lower().strip()

    # Remove currency markers first
    s = s.replace("lei", "").replace("ron", "").replace("eur", "")

    # Remove all spaces
    s = s.replace(" ", "").strip()

    # Check for 'k' suffix (thousands) after removing spaces
    multiplier = Decimal("1")
    if s.endswith("k"):
        multiplier = Decimal("1000")
        s = s[:-1].strip()

    if not s:
        raise FieldValueError("Empty value after removing currency markers")

    # Reject special float values and scientific notation
    s_lower = s.lower()
    if "nan" in s_lower or "inf" in s_lower or "e" in s_lower:
        raise FieldValueError(f"Invalid money value: '{raw}'")

    # Determine decimal separator
    # If both . and , appear, the last one is the decimal separator
    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # Last one is decimal separator
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma > last_dot:
            # Comma is decimal separator, dot is thousands
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            # Dot is decimal separator, comma is thousands
            s = s.replace(",", "")
    elif has_comma:
        # Only comma - need to determine if it's thousands or decimal
        parts = s.split(",")
        if len(parts) == 2:
            decimal_part = parts[1]
            if len(decimal_part) == 1:
                # Single digit after comma -> decimal (e.g., "30,5" -> 30.5)
                s = s.replace(",", ".")
            elif len(decimal_part) == 2:
                # Two digits -> decimal (e.g., "30,50" -> 30.5)
                s = s.replace(",", ".")
            elif len(decimal_part) == 3:
                # Three digits - thousands separator (e.g., "1,500" -> 1500)
                s = s.replace(",", "")
            else:
                # Other cases - assume thousands
                s = s.replace(",", "")
        else:
            # Multiple commas - assume thousands
            s = s.replace(",", "")
    elif has_dot:
        # Only dot - similar logic
        parts = s.split(".")
        if len(parts) == 2:
            decimal_part = parts[1]
            if len(decimal_part) == 1:
                # Single digit after dot -> decimal
                pass
            elif len(decimal_part) == 2:
                # Two digits -> decimal
                pass
            elif len(decimal_part) == 3:
                # Three digits - thousands separator (e.g., "1.500" -> 1500)
                s = s.replace(".", "")
            else:
                # More than 3 digits - keep as is (might fail parsing, but let it try)
                pass
        else:
            # Multiple dots - assume thousands
            s = s.replace(".", "")

    # Try to parse
    try:
        value = Decimal(s) * multiplier
        # Check if value is finite
        if not value.is_finite():
            raise FieldValueError(f"Invalid money value (non-finite): '{raw}'")
        return value
    except (InvalidOperation, ValueError) as e:
        raise FieldValueError(f"Cannot parse '{raw}' as money: {e}")


def parse_field_value(spec: FieldSpec, raw: object) -> Decimal | int | str | bool:
    """Parse and validate a field value according to its spec.

    Args:
        spec: Field specification
        raw: Raw value to parse

    Returns:
        Parsed and validated value

    Raises:
        FieldValueError: If the value is invalid
    """
    if spec.type == FieldType.money:
        value = parse_money(raw)
        if spec.min is not None and value < spec.min:
            raise FieldValueError(f"Value {value} is below minimum {spec.min}")
        if spec.max is not None and value > spec.max:
            raise FieldValueError(f"Value {value} exceeds maximum {spec.max}")
        return value

    elif spec.type == FieldType.integer:
        try:
            if isinstance(raw, str):
                raw = raw.strip()
            value = int(raw)
        except (ValueError, TypeError) as e:
            raise FieldValueError(f"Cannot parse '{raw}' as integer: {e}")

        if spec.min is not None and Decimal(value) < spec.min:
            raise FieldValueError(f"Value {value} is below minimum {spec.min}")
        if spec.max is not None and Decimal(value) > spec.max:
            raise FieldValueError(f"Value {value} exceeds maximum {spec.max}")
        return value

    elif spec.type == FieldType.enum:
        if not isinstance(raw, str):
            raise FieldValueError(f"Enum value must be a string, got {type(raw).__name__}")

        raw_lower = raw.strip().lower()
        if spec.options is None:
            raise FieldValueError("Enum field has no options defined")

        # Case-insensitive match, return canonical option
        for option in spec.options:
            if option.lower() == raw_lower:
                return option

        raise FieldValueError(f"Value '{raw}' is not one of {spec.options}")

    elif spec.type == FieldType.text:
        if not isinstance(raw, str):
            raise FieldValueError(f"Text value must be a string, got {type(raw).__name__}")
        value = raw.strip()
        if not value:
            raise FieldValueError("Text value cannot be empty")
        return value

    elif spec.type == FieldType.boolean:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            raw_lower = raw.strip().lower()
            if raw_lower in ("true", "yes", "da", "1"):
                return True
            if raw_lower in ("false", "no", "nu", "0"):
                return False
        raise FieldValueError(f"Cannot parse '{raw}' as boolean")

    else:
        raise FieldValueError(f"Unknown field type: {spec.type}")


class FieldUpdate(BaseModel):
    """A proposed field update from the model."""
    field: str
    value: str | int | float | bool | None = None
    confirm: bool = False


class UpdateResult(BaseModel):
    """Result of applying a field update."""
    field: str
    accepted: bool
    reason: str | None = None


def apply_field_updates(
    app: ApplicationState,
    updates: list[FieldUpdate],
    specs: dict[str, FieldSpec],
    *,
    offer_ids: set[str],
    now: datetime
) -> list[UpdateResult]:
    """Apply field updates to the application state.

    Validates each update and applies it if valid. Special handling for
    product_code and selected_offer_id which are stored directly on the
    application rather than in fields.

    Args:
        app: Application state to modify
        updates: List of proposed updates
        specs: Field specifications including product_code spec
        offer_ids: Valid offer IDs for validation
        now: Current timestamp

    Returns:
        List of results indicating which updates were accepted/rejected
    """
    results: list[UpdateResult] = []

    # Check if application is locked
    if app.application_id is not None:
        for update in updates:
            results.append(UpdateResult(
                field=update.field,
                accepted=False,
                reason="application_locked"
            ))
        return results

    for update in updates:
        # Handle confirmation
        if update.confirm:
            if update.field not in app.fields:
                results.append(UpdateResult(
                    field=update.field,
                    accepted=False,
                    reason="nothing_to_confirm"
                ))
                continue

            # Mark confirmed
            app.fields[update.field].confirmed = True
            app.fields[update.field].updated_at = now

            # Remove conflict if present
            app.conflicts = [
                c for c in app.conflicts if c.field != update.field
            ]

            results.append(UpdateResult(
                field=update.field,
                accepted=True,
                reason=None
            ))
            continue

        # Must have a value if not confirming
        if update.value is None:
            results.append(UpdateResult(
                field=update.field,
                accepted=False,
                reason="invalid_value: no value provided"
            ))
            continue

        # Special handling for product_code
        if update.field == "product_code":
            if "product_code" not in specs:
                results.append(UpdateResult(
                    field=update.field,
                    accepted=False,
                    reason="unknown_field"
                ))
                continue

            # Validate it's a known product
            spec = specs["product_code"]
            if spec.options is None or str(update.value) not in spec.options:
                results.append(UpdateResult(
                    field=update.field,
                    accepted=False,
                    reason="unknown_product"
                ))
                continue

            # Parse as Product enum
            try:
                new_product = Product(str(update.value))
            except ValueError:
                results.append(UpdateResult(
                    field=update.field,
                    accepted=False,
                    reason="unknown_product"
                ))
                continue

            # If changing product, clear downstream state
            if app.product_code is not None and new_product != app.product_code:
                app.requirements = None
                app.eligibility = None
                app.offers = None
                app.selected_offer_id = None
                app.summary = None
                app.draft_application_id = None

            app.product_code = new_product
            results.append(UpdateResult(
                field=update.field,
                accepted=True,
                reason=None
            ))
            continue

        # Special handling for selected_offer_id
        if update.field == "selected_offer_id":
            if str(update.value) not in offer_ids:
                results.append(UpdateResult(
                    field=update.field,
                    accepted=False,
                    reason="unknown_offer"
                ))
                continue

            app.selected_offer_id = str(update.value)
            results.append(UpdateResult(
                field=update.field,
                accepted=True,
                reason=None
            ))
            continue

        # Regular field
        if update.field not in specs:
            results.append(UpdateResult(
                field=update.field,
                accepted=False,
                reason="unknown_field"
            ))
            continue

        spec = specs[update.field]

        # Check if field requires verification and already has document value
        if update.field in app.fields:
            existing = app.fields[update.field]
            if spec.must_verify and existing.source == FieldSource.document:
                results.append(UpdateResult(
                    field=update.field,
                    accepted=False,
                    reason="must_verify_from_document"
                ))
                continue

        # Parse and validate
        try:
            parsed_value = parse_field_value(spec, update.value)
        except FieldValueError as e:
            results.append(UpdateResult(
                field=update.field,
                accepted=False,
                reason=f"invalid_value: {str(e)}"
            ))
            continue

        # Accept the update
        app.fields[update.field] = FieldValue(
            kind=field_type_to_kind(spec.type),
            value=parsed_value,
            source=FieldSource.customer,
            confirmed=True,
            updated_at=now
        )

        results.append(UpdateResult(
            field=update.field,
            accepted=True,
            reason=None
        ))

    return results


def merge_document_extraction(
    app: ApplicationState,
    doc: DocumentRecord,
    specs: dict[str, FieldSpec],
    *,
    now: datetime
) -> None:
    """Merge extracted fields from a document into application state.

    Only processes accepted documents. For each extracted field that has a
    spec with verified_by matching the doc_type:
    - If customer value differs, create a conflict
    - Set field to document value (unconfirmed)
    - Remove stale conflicts from previous docs of this type
    - Clear conflict if re-upload matches customer value

    Args:
        app: Application state to modify
        doc: Document record with extracted fields
        specs: Field specifications
        now: Current timestamp
    """
    if doc.status != DocumentStatus.accepted:
        return

    # Process each extracted field
    for field_name, extracted in doc.extracted_fields.items():
        # Find spec with this field verified by this doc type
        if field_name not in specs:
            continue

        spec = specs[field_name]
        if spec.verified_by != doc.doc_type:
            continue

        # Parse the extracted value
        try:
            parsed_value = parse_field_value(spec, extracted.value)
        except FieldValueError:
            # Skip invalid extractions
            continue

        # Check for conflict with existing customer value
        # First check if there's an open conflict for this field
        existing_conflict = next((c for c in app.conflicts if c.field == field_name), None)

        if existing_conflict:
            # Field already has a conflict - compare against customer value from conflict
            try:
                customer_value_parsed = parse_field_value(spec, existing_conflict.customer_value)
                if _values_equal(customer_value_parsed, parsed_value, spec.type):
                    # New extraction matches customer value - clear conflict
                    app.conflicts = [c for c in app.conflicts if c.field != field_name]
                else:
                    # New extraction differs - update conflict with new document
                    existing_conflict.document_value = extracted.value
                    existing_conflict.document_id = doc.document_id
            except FieldValueError:
                # Customer value in conflict can't be parsed anymore - keep conflict as is
                pass
        elif field_name in app.fields:
            existing = app.fields[field_name]
            if existing.source == FieldSource.customer:
                # Compare values
                if not _values_equal(existing.value, parsed_value, spec.type):
                    # Conflict detected
                    # Add new conflict
                    app.conflicts.append(FieldConflict(
                        field=field_name,
                        customer_value=str(existing.value),
                        document_value=extracted.value,
                        document_id=doc.document_id
                    ))
                else:
                    # Extraction matches customer value - no conflict
                    pass

        # Set field to document value
        app.fields[field_name] = FieldValue(
            kind=field_type_to_kind(spec.type),
            value=parsed_value,
            source=FieldSource.document,
            document_id=doc.document_id,
            confidence=extracted.confidence,
            confirmed=False,  # Always requires confirmation
            updated_at=now
        )

    # Remove stale conflicts from previous documents of this type only
    # (Keep conflicts from other doc types unchanged)
    valid_doc_ids = {d.document_id for d in app.documents if d.doc_type == doc.doc_type}
    valid_doc_ids.add(doc.document_id)  # Include the current document

    # Get fields that are verified by this doc_type
    fields_for_this_doc_type = {
        name for name, spec in specs.items()
        if spec.verified_by == doc.doc_type
    }

    app.conflicts = [
        c for c in app.conflicts
        # Keep if not for this doc type, or if for this doc type and document is valid
        if c.field not in fields_for_this_doc_type or c.document_id in valid_doc_ids
    ]


def _values_equal(val1: Decimal | int | str | bool, val2: Decimal | int | str | bool, field_type: FieldType) -> bool:
    """Compare two field values for equality based on field type."""
    if field_type == FieldType.money:
        # Compare at 0.01 precision
        if isinstance(val1, Decimal) and isinstance(val2, Decimal):
            return abs(val1 - val2) < Decimal("0.01")
        return False

    elif field_type == FieldType.text:
        # Case-insensitive, whitespace collapsed
        if isinstance(val1, str) and isinstance(val2, str):
            norm1 = " ".join(val1.lower().split())
            norm2 = " ".join(val2.lower().split())
            return norm1 == norm2
        return False

    else:
        # Exact equality for integer, enum, boolean
        return val1 == val2
