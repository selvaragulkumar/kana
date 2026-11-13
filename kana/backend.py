"""Where the Live sessions run: the Gemini Developer API (an API key) or
Vertex AI (Google Cloud application-default credentials, a project, location
`global`). The Live config is the same on both (kana/session.py build_config);
measured side by side in docs/LATENCY.md."""
from __future__ import annotations

import os
import subprocess

BACKENDS = ("developer", "vertex")
# Live Translate is served on Vertex only at `global` (no regional endpoint).
VERTEX_LOCATION = "global"


def gcp_project(flag: str | None, env=None, run=subprocess.run) -> str | None:
    """--gcp-project, else GOOGLE_CLOUD_PROJECT, else `gcloud config get-value project`."""
    if flag:
        return flag
    env = os.environ if env is None else env
    if env.get("GOOGLE_CLOUD_PROJECT"):
        return env["GOOGLE_CLOUD_PROJECT"]
    try:
        r = run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (r.stdout or "").strip().splitlines()
    value = value[-1].strip() if value else ""
    return value if value and value != "(unset)" else None


def client_kwargs(backend: str, project: str | None = None) -> dict:
    """Keyword arguments for google.genai.Client. With an explicit project the
    SDK uses application-default credentials and ignores GEMINI_API_KEY."""
    if backend == "vertex":
        if not project:
            raise ValueError("--backend vertex needs a Google Cloud project")
        return {"vertexai": True, "project": project, "location": VERTEX_LOCATION}
    if backend == "developer":
        return {"http_options": {"api_version": "v1beta"}}
    raise ValueError(f"unknown backend {backend!r}")


def make_client(backend: str, project: str | None = None):
    from google import genai
    return genai.Client(**client_kwargs(backend, project))


def model_label(model: str | None, backend: str) -> str | None:
    """The model as reported in `ready`: on Vertex it carries an `@vertex` suffix,
    so the backend is visible without a protocol change."""
    if model is None or backend == "developer":
        return model
    return f"{model}@{backend}"
