from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from cuauto.demo_app import Handler
from cuauto.events import EventRecorder
from cuauto.intervention import InterventionManager
from cuauto.models import CapabilityArtifact
from cuauto.policy import AllowedTarget, PolicyConfig, PolicyEngine
from cuauto.replay import ReplayEngine
from cuauto.surface import PlaywrightSurface


@pytest.fixture
def live_demo() -> Iterator[tuple[str, PolicyEngine]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    policy = PolicyEngine(
        PolicyConfig(
            targets=(
                AllowedTarget(
                    scheme="http",
                    host="127.0.0.1",
                    port=port,
                    route_prefixes=("/",),
                    allow_private=True,
                ),
            ),
            allowed_actions=frozenset(
                {"navigate", "fill", "click", "extract", "wait", "dismiss_dialog"}
            ),
        )
    )
    try:
        yield f"http://127.0.0.1:{port}/", policy
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.integration
def test_real_playwright_deterministic_replay(
    tmp_path: Path,
    artifact: CapabilityArtifact,
    live_demo: tuple[str, PolicyEngine],
) -> None:
    base_url, policy = live_demo
    data = artifact.model_dump(mode="json")
    data["base_url"] = base_url
    data["steps"][0]["destination"] = base_url
    live_artifact = CapabilityArtifact.model_validate(data)
    surface = PlaywrightSurface(policy, headless=True)
    try:
        outcome = ReplayEngine(
            surface,
            policy,
            EventRecorder(tmp_path / "replay.jsonl"),
            InterventionManager(),
            tmp_path / "runtime",
        ).run(live_artifact, {"member_id": "M1001"})
    finally:
        surface.close()

    assert outcome.kind == "success"
    assert outcome.outputs == {"balance": "1245.67"}
    assert len((tmp_path / "replay.jsonl").read_text(encoding="utf-8").splitlines()) == 5
