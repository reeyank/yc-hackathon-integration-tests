import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import gbrain_source  # noqa: E402


def test_source_id_for_path_is_stable_and_app_scoped(tmp_path):
    app = tmp_path / "My App"
    app.mkdir()

    source = gbrain_source.source_id_for_path(app)

    assert source.startswith("app-my-app-")
    assert source.endswith("-scoped")
    assert source == gbrain_source.source_id_for_path(app)


def test_prepare_app_source_sets_env_and_syncs(monkeypatch, tmp_path):
    calls = []
    app = tmp_path / "app-repo"
    app.mkdir()
    (app / "app").mkdir()
    (app / "app" / "index.tsx").write_text("export default function Index() {}", encoding="utf-8")
    (app / "ios" / "Pods").mkdir(parents=True)
    (app / "ios" / "Pods" / "junk.hpp").write_text("junk", encoding="utf-8")
    scoped = tmp_path / "scoped"

    def fake_run(*args, check):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(gbrain_source, "_run_gbrain", fake_run)
    monkeypatch.delenv("GBRAIN_SOURCE", raising=False)
    monkeypatch.setenv("GBRAIN_SCOPED_SOURCE_ROOT", str(scoped))

    source = gbrain_source.prepare_app_source(app, source_id="fresh-app", fresh=True)

    assert source == "fresh-app"
    assert os.environ["GBRAIN_SOURCE"] == "fresh-app"
    assert calls[0] == ("sources", "remove", "fresh-app", "--confirm-destructive")
    assert calls[1] == ("sources", "add", "fresh-app", "--path", str((scoped / "fresh-app").resolve()))
    assert calls[2] == ("sync", "--source", "fresh-app", "--strategy", "code")
    assert (scoped / "fresh-app" / "app" / "index.tsx").exists()
    assert not (scoped / "fresh-app" / "ios" / "Pods" / "junk.hpp").exists()
