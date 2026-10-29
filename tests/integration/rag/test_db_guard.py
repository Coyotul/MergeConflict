"""The integration fixture drops the public schema, so it must only ever touch a *_test database."""
import pytest

from tests.integration.rag.conftest import require_test_database


@pytest.mark.parametrize("name", ["rag", "rag_tests", "production", "test_rag"])
def test_refuses_a_database_not_ending_in_test(name):
    with pytest.raises(RuntimeError, match="refusing to drop"):
        require_test_database(name)


def test_accepts_a_test_database():
    require_test_database("rag_test")
