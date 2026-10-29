"""Read-only trusted application snapshots; eligibility cannot transition workflows."""

from src.models.eligibility import ApplicationSnapshot


class SyntheticApplicationRepository:
    def __init__(self, applications: tuple[ApplicationSnapshot, ...]) -> None:
        ids = [item.application_id for item in applications]
        if len(ids) != len(set(ids)):
            raise ValueError("Synthetic application identifiers must be unique.")
        self._applications = {
            item.application_id: ApplicationSnapshot.model_validate_json(item.model_dump_json())
            for item in applications
        }

    def get_application(self, application_id: str) -> ApplicationSnapshot | None:
        item = self._applications.get(application_id)
        return ApplicationSnapshot.model_validate_json(item.model_dump_json()) if item else None

    def upsert_application(self, application: ApplicationSnapshot) -> None:
        self._applications[application.application_id] = ApplicationSnapshot.model_validate_json(application.model_dump_json())
