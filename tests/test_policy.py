from datetime import UTC, datetime, timedelta

import pytest

from cuauto.models import ActionType, Risk
from cuauto.policy import AllowedTarget, Approval, PolicyConfig, PolicyEngine, PolicyViolation


def test_allowed_url(policy):
    assert policy.check_url("http://127.0.0.1:8765/member?id=1")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1.evil:8765/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://user:pass@127.0.0.1:8765/",
    ],
)
def test_bad_urls(policy, url):
    with pytest.raises(PolicyViolation):
        policy.check_url(url)


def test_redirect_outside_allowlist(policy):
    with pytest.raises(PolicyViolation):
        policy.check_url("https://example.com/")


def test_route_and_private_ip():
    p = PolicyEngine(
        PolicyConfig(
            targets=(
                AllowedTarget(
                    scheme="https", host="example.com", port=443, route_prefixes=("/safe/",)
                ),
            ),
            allowed_actions=frozenset({ActionType.CLICK}),
        )
    )
    with pytest.raises(PolicyViolation):
        p.check_url("https://example.com/admin")
    private = PolicyEngine(
        PolicyConfig(
            targets=(AllowedTarget(scheme="http", host="169.254.169.254", port=80),),
            allowed_actions=frozenset({ActionType.CLICK}),
        )
    )
    with pytest.raises(PolicyViolation):
        private.check_url("http://169.254.169.254/")


def test_disallowed_action():
    p = PolicyEngine(
        PolicyConfig(
            targets=(AllowedTarget(scheme="https", host="example.com", port=443),),
            allowed_actions=frozenset({ActionType.CLICK}),
        )
    )
    with pytest.raises(PolicyViolation):
        p.check_action(ActionType.FILL, Risk.READ_ONLY)


def test_risky_requires_exact_fresh_approval(policy):
    binding = ("s", "c", "step", "click:x", "target", "inv")
    with pytest.raises(PolicyViolation):
        policy.check_action(ActionType.CLICK, Risk.HIGH)
    stale = Approval(
        token="t",
        session_id="s",
        capability_id="c",
        step_id="step",
        normalized_action="click:x",
        target="target",
        invocation_id="inv",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(PolicyViolation):
        policy.check_action(ActionType.CLICK, Risk.HIGH, approval=stale, binding=binding)
    fresh = stale.model_copy(update={"expires_at": datetime.now(UTC) + timedelta(seconds=10)})
    with pytest.raises(PolicyViolation):
        policy.check_action(
            ActionType.CLICK, Risk.HIGH, approval=fresh, binding=("wrong",) + binding[1:]
        )
    policy.check_action(ActionType.CLICK, Risk.HIGH, approval=fresh, binding=binding)
