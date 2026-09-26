# Evidence

Evidence in this directory must come from commands, never hand-authored run claims.

- `capability.json`: successful genuine `gpt-4o-mini` discovery artifact; provenance run ID
  `f3b7f8d1c2304364990519fca02787ce` and provider `openai-compatible`.
- `genuine-discovery.jsonl`: events filtered to that successful genuine discovery run.
- `genuine-replay-result.json` and `genuine-replay.jsonl`: successful deterministic replay and
  correlated model-free events.
- `genuine-not-found-result.json`: deterministic `member_not_found` business outcome.
- `offline-capability.json`: live-browser execution selected by the deterministic offline fixture.
  It proves the UI/artifact seam, **not a genuine LLM call**. `discovery.jsonl` is the complete audit
  history, including offline runs and genuine discovery experiments.
- `replay.jsonl`, `replay-result.json`: deterministic browser replay; no model is constructed.
- `not-found-result.json`: expected business outcome.
- `handoff.txt`: same-session state-machine execution and sanitized acknowledgment.
- `runtime/*-dom.txt`: richer sanitized failure signal when a run fails. Screenshots are disabled by
  default because this slice has no pixel-redaction pipeline.

Reproduce from the repository root:

```bash
cuauto serve-demo                                      # terminal 1
cuauto discover --offline --output evidence/offline-capability.json
cuauto replay evidence/offline-capability.json --member-id M1001
cuauto replay evidence/offline-capability.json --member-id M9999 \
  --result evidence/not-found-result.json
python scripts/handoff_demo.py --output evidence/handoff.txt
python scripts/make_error_fixture.py
cuauto replay evidence/error-capability.json --member-id M1001 \
  --result evidence/error-result.json       # expected exit 2; redacted DOM is under runtime/
```

To generate the mandatory genuine discovery artifact, set a real key and run:

```bash
export CUAUTO_MODEL_API_KEY='...'
export CUAUTO_MODEL_NAME='gpt-4o-mini'
cuauto discover --output evidence/capability.json
cuauto replay evidence/capability.json --member-id M1001
```

Verify `provenance.model_provider` is `openai-compatible`; `offline-fixture` is never acceptable as
genuine evidence. The included `capability.json` satisfies that check.

Regenerate the concise reviewer logs after new successful runs with:

```bash
python scripts/curate_evidence.py
```
