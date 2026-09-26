from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .models import CapabilityArtifact
from .redaction import contains_secret

SAFE_FILE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}\.json$")


class ArtifactError(ValueError):
    pass


class ArtifactStore:
    def __init__(self, root: Path, max_bytes: int = 1_000_000):
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, filename: str) -> Path:
        if not SAFE_FILE.fullmatch(filename):
            raise ArtifactError("unsafe artifact filename")
        path = self.root / filename
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ArtifactError("unsafe artifact path")
        return path

    def load(self, filename: str) -> CapabilityArtifact:
        path = self._path(filename)
        if path.stat().st_size > self.max_bytes:
            raise ArtifactError("artifact too large")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return CapabilityArtifact.model_validate(data)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ArtifactError(f"corrupted or invalid artifact: {exc}") from exc

    def save(self, filename: str, artifact: CapabilityArtifact) -> Path:
        path = self._path(filename)
        payload = artifact.model_dump_json(indent=2)
        if contains_secret(payload):
            raise ArtifactError("artifact appears to contain a secret")
        if len(payload.encode()) > self.max_bytes:
            raise ArtifactError("artifact too large")
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".artifact-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path
