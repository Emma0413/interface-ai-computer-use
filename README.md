# Computer-Use Automation System

This repository is a focused vertical slice: an LLM discovers a flow against a deliberately
legacy-looking local banking application; the successful, verified flow becomes a strict JSON
capability; replay executes it without any model decisions; failures become typed results with
redacted evidence; and an intervention state machine can cede the same browser session to a person.

> **Never use this project with real banking credentials, accounts, secrets, or PII.** The bundled
> application and evidence use fictional data only.

## Prerequisites and setup

Python 3.11+ is required (3.13 is exercised here).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m playwright install chromium
# Only on minimal Linux images reporting missing libnspr/libnss/libasound:
bash scripts/install_browser_libs.sh
```

Copy values from `.env.example` into your shell; do not create or commit a real `.env`. Discovery
reads only `CUAUTO_MODEL_API_KEY`, `CUAUTO_MODEL_BASE_URL`, and `CUAUTO_MODEL_NAME`. The client uses
an OpenAI-compatible `/chat/completions` endpoint and a strict JSON schema response.

## End-to-end commands

In terminal one:

```bash
cuauto serve-demo
```

Genuine discovery in terminal two:

```bash
export CUAUTO_MODEL_API_KEY='...'
export CUAUTO_MODEL_NAME='gpt-4o-mini'
export CUAUTO_MODEL_TIMEOUT_SECONDS=90
cuauto discover --goal 'Look up member M1001 and read the savings balance'
cuauto validate evidence/capability.json
```

Deterministic replay (the command does not construct or call a model):

```bash
cuauto replay evidence/capability.json --member-id M1001
cuauto replay evidence/capability.json --member-id M9999 --result evidence/not-found-result.json
```

Known business outcomes exit successfully and are represented as `business_outcome`. Hard failures
exit 2, and discovery escalation exits 3.

## Offline mode and handoff

The offline fixture drives the same live Playwright UI and produces a real artifact, but **does not
satisfy the assignment's genuine-model evidence requirement**:

```bash
cuauto discover --offline --output evidence/offline-capability.json
cuauto replay evidence/offline-capability.json --member-id M1001
```

For a real manual takeover, keep `cuauto serve-demo` running in terminal 1, then run this in terminal
2:

```bash
cuauto handoff-demo --result evidence/live-handoff-result.json
```

A visible Chromium window opens. The command pauses automation before transferring control; operate
that same window, return to the terminal, type `resume` (or `cancel`), and enter a short note. On
resume it atomically returns ownership, re-observes the same session, and rechecks the current URL
against policy. Evidence is written to `evidence/live-handoff.jsonl` and the result path above. The
tested manager rejects concurrent automation, cross-session, stale, duplicate, cancelled, and
expired commands. This records the operator's sanitized completion note and control transitions—not
individual mouse or keyboard events. `scripts/handoff_demo.py` remains only a fast state-machine
fixture and is not evidence of a live browser takeover.

## Verification

```bash
ruff format --check .
ruff check .
mypy src
pytest
pip-audit
rg -n -i '(password|authorization|bearer|api[_-]?key|cookie|access[_-]?token)' \
  --glob '!Assignment*.pdf' --glob '!.env.example' .
```

The unit suite uses injected adapters/models and never incurs a model charge. Browser integration is
the CLI demo above. The target supports not-found, validation, permission, expired-session,
application-error, delayed-load, and review-without-commit routes. Evidence persistence defaults to
redacted DOM text; screenshots are opt-in because pixels cannot be reliably redacted here.

## Evidence guide

See `evidence/README.md`. JSONL contains bounded audit rationale, never hidden reasoning or a full
model prompt. IDs/timestamps in generated files come from executions. `provenance.model_provider`
distinguishes `offline-fixture` from `openai-compatible`.

## Limitations and troubleshooting

This is not production-grade security. DNS rebinding protection is checked when resolution is
enabled, but a production adapter should pin resolved addresses and use an egress proxy. Chromium
screenshots are disabled by default; DOM text redaction is heuristic. There is no identity provider,
durable approval service, encrypted artifact signing, remote co-browsing, frame/desktop adapter, or
per-event human input capture. Approval objects are in-memory and single-process. The demo's
same-origin protection applies to POSTs; it is not a general operator web console.

If Chromium is missing, rerun `python -m playwright install chromium`. If genuine discovery fails,
confirm the provider supports strict JSON Schema and the three `CUAUTO_MODEL_*` variables are set.
