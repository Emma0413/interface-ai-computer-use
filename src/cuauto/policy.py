from __future__ import annotations

import ipaddress
import secrets
import socket
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from urllib.parse import unquote, urlsplit, urlunsplit

from pydantic import Field, field_validator

from .models import ActionType, Risk, StrictModel


class PolicyViolation(ValueError):
    pass


class AllowedTarget(StrictModel):
    scheme: Literal["http", "https"]
    host: str
    port: int = Field(ge=1, le=65535)
    route_prefixes: tuple[str, ...] = ("/",)
    allow_private: bool = False

    @field_validator("host")
    @classmethod
    def host_is_exact(cls, value: str) -> str:
        normalized = value.rstrip(".").encode("idna").decode("ascii").lower()
        if "*" in normalized or not normalized:
            raise ValueError("wildcards and empty hosts are forbidden")
        return normalized


class PolicyConfig(StrictModel):
    targets: tuple[AllowedTarget, ...] = Field(min_length=1, max_length=20)
    allowed_actions: frozenset[ActionType]
    require_approval_for: frozenset[Risk] = frozenset({Risk.HIGH})
    screenshot_persistence: bool = False
    pii_fields: frozenset[str] = frozenset({"member_name", "member_id"})
    max_observation_chars: int = Field(default=8_000, ge=100, le=20_000)


class Approval(StrictModel):
    token: str
    session_id: str
    capability_id: str
    step_id: str
    normalized_action: str
    target: str
    invocation_id: str
    expires_at: datetime
    used: bool = False


def canonical_url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        raise PolicyViolation("unsupported URL scheme")
    if parts.username or parts.password:
        raise PolicyViolation("URL credentials forbidden")
    if not parts.hostname:
        raise PolicyViolation("missing hostname")
    try:
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise PolicyViolation("invalid internationalized hostname") from exc
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    path = unquote(parts.path or "/")
    if "\x00" in path or any(segment == ".." for segment in path.split("/")):
        raise PolicyViolation("unsafe URL path")
    netloc = host if port in {80, 443} else f"{host}:{port}"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


class PolicyEngine:
    def __init__(self, config: PolicyConfig):
        self.config = config

    def check_url(self, raw: str, *, resolve_dns: bool = False) -> str:
        normalized = canonical_url(raw)
        parts = urlsplit(normalized)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        target = next(
            (
                t
                for t in self.config.targets
                if t.scheme == parts.scheme and t.host == parts.hostname and t.port == port
            ),
            None,
        )
        if target is None:
            raise PolicyViolation("destination not allowlisted")
        if not any(parts.path.startswith(prefix) for prefix in target.route_prefixes):
            raise PolicyViolation("route not allowlisted")
        addresses: set[str] = {parts.hostname or ""}
        if resolve_dns:
            try:
                addresses |= {cast(str, x[4][0]) for x in socket.getaddrinfo(parts.hostname, port)}
            except socket.gaierror as exc:
                raise PolicyViolation("host resolution failed") from exc
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            unsafe = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            if unsafe and not target.allow_private:
                raise PolicyViolation("private or special-purpose address forbidden")
        return normalized

    def check_action(
        self,
        action: ActionType,
        risk: Risk,
        *,
        approval: Approval | None = None,
        binding: tuple[str, str, str, str, str, str] | None = None,
    ) -> None:
        if action not in self.config.allowed_actions:
            raise PolicyViolation(f"action not allowed: {action.value}")
        if risk in self.config.require_approval_for:
            if approval is None or binding is None:
                raise PolicyViolation("exact approval required")
            expected = (
                approval.session_id,
                approval.capability_id,
                approval.step_id,
                approval.normalized_action,
                approval.target,
                approval.invocation_id,
            )
            if approval.used or approval.expires_at <= datetime.now(UTC) or expected != binding:
                raise PolicyViolation("approval stale, used, or mismatched")


def create_approval(**binding: str) -> Approval:
    return Approval.model_validate(
        {
            "token": secrets.token_urlsafe(32),
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
            **binding,
        }
    )
