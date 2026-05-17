import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from env_loader import load_dotenv  # noqa: E402


def test_load_dotenv_sets_missing_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY='sk-test-value'\nIOS_TEST_OPENAI_MODEL=gpt-test\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    load_dotenv()

    assert os.environ["OPENAI_API_KEY"] == "sk-test-value"
    assert os.environ["IOS_TEST_OPENAI_MODEL"] == "gpt-test"


def test_load_dotenv_does_not_override_existing_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    monkeypatch.chdir(tmp_path)

    load_dotenv()

    assert os.environ["OPENAI_API_KEY"] == "from-env"


def test_load_dotenv_defaults_project_local_gbrain_home(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    runtime = tmp_path / ".gbrain-runtime"
    runtime.mkdir()
    wrapper = tmp_path / "scripts" / "gbrain-project"
    wrapper.parent.mkdir()
    wrapper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.delenv("GBRAIN_HOME", raising=False)
    monkeypatch.delenv("GBRAIN_BIN", raising=False)
    monkeypatch.delenv("GBRAIN_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GBRAIN_SOURCE", raising=False)
    monkeypatch.chdir(tmp_path)

    load_dotenv()

    assert os.environ["GBRAIN_HOME"] == str(runtime)
    assert os.environ["GBRAIN_BIN"] == str(wrapper)
    assert os.environ["GBRAIN_TIMEOUT_S"] == "35"
    assert "GBRAIN_SOURCE" not in os.environ
    assert os.environ["GBRAIN_EXPANSION_MODEL"] == "anthropic:claude-haiku-4-5-20251001"
    assert os.environ["GBRAIN_CHAT_MODEL"] == "anthropic:claude-sonnet-4-6"
