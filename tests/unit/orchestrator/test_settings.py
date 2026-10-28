from pathlib import Path
from src.core.settings import load_orchestrator_settings


def test_defaults_from_empty_env():
    s = load_orchestrator_settings({})
    assert s.model == "openai/gpt-oss-120b"
    assert s.featherless_base_url == "https://api.featherless.ai/v1"
    assert s.max_steps == 4 and s.session_store == "file" and s.featherless_api_key is None


def test_env_overrides():
    s = load_orchestrator_settings({"ORCHESTRATOR_MODEL": "fake", "ORCHESTRATOR_JSON_MODE": "false",
                                    "ORCHESTRATOR_MAX_STEPS": "3", "FEATHERLESS_API_KEY": "k",
                                    "ORCHESTRATOR_SESSIONS_DIR": "x/y"})
    assert s.model == "fake" and s.json_mode is False and s.max_steps == 3
    assert s.featherless_api_key.get_secret_value() == "k" and s.sessions_dir == Path("x/y")


def test_api_key_not_in_repr():
    assert "secret" not in repr(load_orchestrator_settings({"FEATHERLESS_API_KEY": "secret"}))
