"""--backend developer|vertex: client arguments, project lookup, ready fields."""
import json
import subprocess
from types import SimpleNamespace as NS

import pytest

from kana import __main__ as cli
from kana import backend


def test_backend_defaults_to_developer():
    assert cli.parse_args([]).backend == "developer"
    assert cli.parse_args([]).gcp_project is None
    a = cli.parse_args(["--backend", "vertex", "--gcp-project", "p1"])
    assert (a.backend, a.gcp_project) == ("vertex", "p1")
    with pytest.raises(SystemExit):
        cli.parse_args(["--backend", "openai"])


def test_client_kwargs_developer_and_vertex_global():
    assert backend.client_kwargs("developer") == {"http_options": {"api_version": "v1beta"}}
    assert backend.client_kwargs("vertex", "p1") == {"vertexai": True, "project": "p1", "location": "global"}
    with pytest.raises(ValueError):
        backend.client_kwargs("vertex", None)
    with pytest.raises(ValueError):
        backend.client_kwargs("other")


def test_vertex_client_uses_project_not_api_key(monkeypatch):
    """An explicit project makes the SDK use application-default credentials
    even when GEMINI_API_KEY is set (no network call is made here)."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-not-a-key")
    monkeypatch.setattr("google.auth.default", lambda *a, **k: (NS(), "p1"))
    c = backend.make_client("vertex", "p1")
    api = c._api_client
    assert api.vertexai and api.project == "p1" and api.location == "global" and not api.api_key


def test_gcp_project_order():
    def no_gcloud(*a, **k):
        raise AssertionError("gcloud must not run")
    assert backend.gcp_project("flag", env={"GOOGLE_CLOUD_PROJECT": "env"}, run=no_gcloud) == "flag"
    assert backend.gcp_project(None, env={"GOOGLE_CLOUD_PROJECT": "env"}, run=no_gcloud) == "env"
    ok = lambda *a, **k: NS(stdout="from-gcloud\n", returncode=0)  # noqa: E731
    assert backend.gcp_project(None, env={}, run=ok) == "from-gcloud"
    unset = lambda *a, **k: NS(stdout="(unset)\n", returncode=0)  # noqa: E731
    assert backend.gcp_project(None, env={}, run=unset) is None

    def missing(*a, **k):
        raise FileNotFoundError("gcloud")
    assert backend.gcp_project(None, env={}, run=missing) is None

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("gcloud", 15)
    assert backend.gcp_project(None, env={}, run=slow) is None


def test_model_label_marks_vertex_only():
    assert backend.model_label("m", "developer") == "m"
    assert backend.model_label("m", "vertex") == "m@vertex"
    assert backend.model_label(None, "vertex") is None


def test_ready_fields_report_the_backend_in_the_model_fields():
    dirs = {"IN": (("dev", 5, "BlackHole 16ch"), (1, "AirPods")),
            "OUT": (("dev", 0, "Mic"), (4, "BlackHole 2ch"))}
    dev = cli.ready_fields(cli.parse_args(["--model", "m-translate"]), dirs)
    assert (dev["model"], dev["in_model"], dev["out_model"]) == ("m-translate", "m-translate", "m-translate")
    vx = cli.ready_fields(cli.parse_args(["--model", "m-translate", "--backend", "vertex"]), dirs)
    assert (vx["model"], vx["in_model"], vx["out_model"]) == ("m-translate", "m-translate@vertex",
                                                               "m-translate@vertex")
    assert set(vx) == set(dev)  # no new protocol field


def test_vertex_needs_no_api_key_but_a_project(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", cli.Path("/nonexistent"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(backend, "gcp_project", lambda flag: None)
    assert cli.main(["--json", "--only", "in", "--backend", "vertex"]) == 2
    line = json.loads(capsys.readouterr().out.strip())
    assert line["ev"] == "error" and line["fatal"] and "project" in line["text"]
    assert "GEMINI_API_KEY" not in line["text"]
