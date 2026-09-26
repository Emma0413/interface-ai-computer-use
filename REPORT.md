# 1. Architecture

`DiscoveryAgent` owns a bounded observe/decide/check/act loop. `ModelProvider` is injected, so real
OpenAI-compatible calls and an explicitly labeled fixture share a boundary. `SurfaceAdapter` owns
observation, exact control resolution, action, condition waits, evidence, and exposure of a live
session. The Playwright implementation is only one adapter. `ReplayEngine` consumes only a validated
artifact, invocation values, policy, surface, recorder, and intervention manager; it has no model
reference. `PolicyEngine` runs immediately before actions. `ArtifactStore` and `EventRecorder` form
the small persistence layer. This stays single-process because queues and services add no value to
the assessed seam.

# 2. Artifact schema

`cuauto.capability@1.0.0` is strict and extra-field rejecting. It declares identity/revision, vendor
compatibility, tenant-neutral base URL, constrained locator-only variants, typed validated inputs
and outputs, stable ordered step IDs, risk, ranked abstract locators, conditions, explicit waits,
extraction, final checkpoint, outcomes, bounded recoveries, escalation reasons, approval state, and
provenance. Values are either `{param: id}` or a bounded literal; there is no evaluation, script, or
selector interpolation. Cross-validation rejects duplicate IDs, dangling parameters and extraction
type mismatches. Loaders reject size excess, unsafe names, traversal, symlinks, malformed JSON, and
unsupported versions. Artifact approval is draft/approved/retired; production would add signatures
and require reapproval after revision or compatibility changes.

# 3. Determinism & error handling

Replay validates artifact and inputs before opening the target, then executes the immutable step
order. Locators are tried by recorded precedence—role/name, label, scoped text, allowed attributes,
relative structure, then coordinates only when explicitly fragile—and each must resolve exactly one
control. Conditions replace sleeps. Navigation and redirects are revalidated; policy is checked on
every attempt. Preconditions, postconditions, output conversions, and the final checkpoint are
asserted. Only declared read-only steps can retry, at most three times; mutation retry is rejected by
schema.

Results discriminate success, business outcome, escalation, and failure. Failures identify taxonomy,
step, expected/sanitized observed state, retries, and evidence. Not-found is data, not an exception.
Fingerprints detect discovery loops; replay event metrics and checkpoint failure rates are the drift
signal. Production would aggregate them per vendor/version/variant and quarantine a revision when a
threshold is crossed.

# 4. Heterogeneity & multi-tenant

Artifacts contain intent-level controls, not Playwright objects. Another adapter can map the same
role/label/text/attribute/relative candidates onto a browser accessibility tree, Windows UI
Automation, OCR plus scoped coordinates, or a legacy frameset walker while preserving replay and
policy semantics. Coordinates remain a review-visible fragile fallback.

A vendor capability is the base. A tenant selects a named variant compatible with an application
version; variants can replace locators for existing stable step IDs, not add actions, values, URLs,
or risk. That keeps specialization constrained and reviewable. Version fingerprints, checkpoint
metrics, and ambiguous/missing-control rates detect drift. A variant/revision is tested and approved
before promotion, with safe fallback to escalation—not cross-tenant guessing.

# 5. Escalation & handoff

Repeated fingerprints, timeout, maximum steps, policy blocks, unsafe model output, or replay failures
raise a sanitized intervention. The manager atomically moves `AUTOMATION_ACTIVE → PAUSING →
HUMAN_ACTIVE → RESUMING → AUTOMATION_ACTIVE`, plus terminal cancellation/expiration states.
Automation checks ownership before each replay action. Transfer binds an unpredictable token to the
intervention and exact session; the same Playwright `Page` stays alive and a headful window is exposed.
The `cuauto handoff-demo` command exercises that live transfer directly. Resume rejects the wrong
session/token, expiry, duplicates, and stale state. After handback the command re-observes the same
surface and rechecks navigation policy before reporting success. Implemented capture is the operator's
bounded acknowledgment and state transitions, not a misleading claim of raw input capture.

# 6. Safety

URL comparison canonicalizes scheme, exact IDNA hostname, port and route; credentials, unsafe schemes,
traversal, wildcard/suffix matching, private/special IPs (unless the explicit local-demo exception),
and off-policy redirects fail closed. Allowed actions default deny. High-risk action approval binds
session, capability, step, normalized action, target, invocation and expiry; the schema also forbids
blind mutation retries. Page text is labeled untrusted, observations are bounded/redacted, and model
output is schema validated. It cannot issue shell/code/SQL/JavaScript or arbitrary selectors.

Secrets come only from environment variables. Recursive redaction covers keys, bearer values, email,
SSN and configured fields; events are bounded and opened no-follow. Artifact writes are atomic.
Profiles, auth state, traces, databases and `.env` are ignored. The demo binds localhost, escapes
fictional values, bounds requests, uses HttpOnly/SameSite session cookies and rejects cross-origin
POSTs. This is defense-in-depth for a take-home, not a production security claim; limitations are in
the README.

# 7. Cuts

Implemented: genuine-provider client and live discovery loop, real Playwright UI adapter, strict
artifact/store, model-free replay, typed outcomes/errors, evidence recorder, synthetic exceptional
states, and real same-object control ownership. Mocked intentionally: offline model decisions and the
operator UI (CLI/direct state-machine calls). Cut: durable orchestration, SSO, encrypted signing,
network egress enforcement, visual redaction, frame/desktop adapters, per-keystroke human audit,
multi-tenant registry, and automatic artifact promotion. Next would be a tiny authenticated
localhost operator console, signed approvals/artifacts, pinned egress, and a second accessibility/OS
adapter—not distributed infrastructure.
