"""Authorization lives outside the LLM and is enforced on every use case."""

from src.core.errors import DomainError
from src.models.banking import Actor, LoanApplication, Role


def require_role(actor: Actor, role: Role) -> None:
    if actor.role != role:
        raise DomainError("FORBIDDEN", "Your demo role cannot perform this action.", 403)


def visible_application(application: LoanApplication, actor: Actor) -> LoanApplication:
    visible = application.model_copy(deep=True)
    if actor.role == Role.CUSTOMER:
        visible.notes = [note for note in visible.notes if not note.internal]
    return visible