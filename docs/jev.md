# Optional hybrid Blue selection

`BLUE_JEV_ENABLED=1` enables a shared selector for standalone `run_defence` / red-blue orchestration
and classic or strategic `Match` Blue turns, including preparation. Default `0` retains the existing
Blue flow. Red's action selection is unchanged. Restart the backend after changing its environment.

The existing chat LLM proposes alternatives. Python validates each alternative on a temporary TuringDB
branch, discards the previews, and supplies only valid alternatives to Featherless Simple Jev. Jev
returns a candidate ID, never executable instructions. Python retrieves that candidate's locally held
action and arguments, executes it through the existing branch builder, and measures the outcome with
the existing impact model. A separate, bounded call to the existing chat LLM explains the measured
result. If explanation fails, the measured move is retained with a plain factual summary.

Standalone candidates are single existing defensive actions. Wargame proposals name IDs from a local
shortlist of the board's existing actions, with distinct action kinds represented before repeated kinds.
Strategic `play` still checks legal plans and wraps exactly one action in `game_order`: existing budget,
delay, capacity and pending-order checks apply. Automatic forced waits make no new model calls.
Stacking still replays lineage and propagates status; no code submits changes or writes graph main.
The standalone orchestrator honours the priority-selected branch, even if aggregate loss is higher
than an alternative. It retains its original minimum-loss selection on fallback.

## Configuration

The backend reuses `FEATHERLESS_API_KEY`; the key never reaches the UI. There is no automatic switch to
TypeSafe, a public demo, a different classifier model, or another credential.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BLUE_JEV_ENABLED` | `0` | Enable with exactly `1` |
| `BLUE_JEV_MODEL` | `featherless-ai/gemma-4-26B-A4B-classifier` | Production classifier model ID |
| `BLUE_JEV_TIMEOUT` | `15` | httpx timeout per network phase, clamped to 0.1–60 seconds |
| `BLUE_JEV_MIN_CONFIDENCE` | `0` | Minimum conditional option probability, clamped to 0–1 |
| `BLUE_JEV_PRIORITIES` | Protect critical parts and priority programmes; respect the available intervention budget. | Operator priorities; bounded to 1,000 characters |

The default confidence threshold accepts any valid selection. There is no domain calibration supporting
a higher threshold. Confidence and the returned distribution are probabilities **over these options**,
not guarantees of correctness. Set a threshold only after evaluation on representative labelled decisions.

No new costs, deadlines or capacities are invented. Standalone state explicitly marks budget and timing
unspecified. Strategic costs/readiness come from the repository's existing gameplay assumptions, not
calibrated operational data. Python supplies measured critical-part restoration and programme capability
as evidence; loss percentages and loss forecasts are omitted from Jev's context. Jev judges priorities,
coverage and existing constraints, rather than calculating or minimizing supply loss.

## Verified Featherless contract (3 October 2026)

Official sources: [API reference](https://featherless.ai/simple-jev/docs),
[Featherless introduction](https://featherless.ai/blog/jev-llm-classifier-qwen3-simple-jev), and
[agent reference](https://featherless.ai/simple-jev/skills.md).

The separate client uses `POST https://api.featherless.ai/v1/classifier`, JSON content type, and a server-side
Bearer header. Request fields are `model`, structured `state`, and `questions.blue` with `type: choice`,
`instructions`, and candidate IDs as the keys of `criteria`. Response fields are
`answers.blue.{type,choice,confidence,probabilities}`. No chat-generation settings are sent. IDs,
finite probabilities, normalization and consistency of the selected probability are checked before use.
Redirects are disabled. Only safe diagnostic codes are recorded; provider bodies are not logged.

The current production catalog lists Gemma and both Qwen classifier models. Official documentation says production classifiers are in beta
on Featherless Developer plans. Listing a model does not establish that an account can run it.

## Bounds, fallback and observability

Each selection has one proposal chat request, at most five action validations, and one Jev request with
no retry. Successful selection adds one explanation chat request. The two new chat requests use the
existing client in bounded mode: one HTTP attempt each, 30-second httpx network-phase timeout, no
model-switch/retry loop. Normal existing Blue/Red calls retain their original retry behaviour. HTTP
phase timeouts are not a strict total wall-clock deadline; graph previews also add measurable latency.
Two valid alternatives suffice; the proposal prompt asks for three to five. Insufficient/invalid proposals,
preview failures, unavailable credentials, HTTP errors, timeout, invalid IDs/probabilities, or a configured
confidence rejection return to the existing Blue flow. No malformed classifier action/arguments are used.

`Move.selection` is saved and streamed by the existing match job/events/recording path. It includes selector,
presented local candidates and measured preview evidence, selected ID/candidate, confidence/distribution,
proposal duration, classifier duration/count, fallback and safe reason, and the measured executed impact.
Fallback also records the action actually executed. Moves count logical chat calls and actual chat HTTP
attempts (including normal retries); match summaries aggregate them and classifier duration/count plus
elapsed time. Classifier time is excluded from `db_ms`. Standalone result/trace/job selection events carry
the same audit and total duration/chat counts; red-blue results retain the audit. Existing MoveFeed shows
who selected the move, the number of alternatives and whether the existing flow was used. Explanation
text belongs to the chat LLM; Jev has no explanation output.

## Validation and comparison

Validation results: 152 focused Python tests passed, 7 skipped; two real-TuringDB tests passed
with deterministic provider doubles. UI: 28 tests passed, typecheck and build passed. `git diff --check`
was clean.

Offline coverage includes valid and invalid selections, HTTP timeout/access/schema failures, confidence
rejection, disabled behaviour, single-action execution, candidate cleanup, and bounded chat retry behaviour.
Focused regression command:

```bash
.venv/bin/python -m pytest tests/agents/test_blue_selection.py tests/agents/test_guard.py \
  tests/agents/test_llm.py tests/agents/test_deep_impact.py tests/agents/test_match.py \
  tests/agents/test_game_rules.py tests/api -q
npm --prefix ui run typecheck
npm --prefix ui test
npm --prefix ui run build
```

`tests/agents/test_jev_live.py` validates branch stacking, replay, preview cleanup, unchanged main and
strategic single-action/budget rules against real TuringDB with deterministic provider doubles. It skips
when theatre is unavailable. These tests do not establish live Jev model quality.

Live model discovery succeeded (HTTP 200). The keyless official Featherless example returned a valid
choice. Authenticated production classifier calls with the configured key returned HTTP 400, including
minimal official-schema requests against both Qwen models. The response supplied only a generic invalid
request diagnostic. Account/service cause is unresolved; successful production Jev selection could not
be verified for Qwen. The implementation exercised its existing-Blue fallback correctly.

Follow-up: authenticated `featherless-ai/gemma-4-26B-A4B-classifier` succeeded using the same key
and the repository client, selecting the critical-part backup candidate in 1,758.2 ms. It is now the
default; production-only authentication is retained. No demo mode is enabled or installed. The earlier
HTTP 400 failure is model-specific in the tested requests, not a general connection failure. A full
real-provider hybrid match with Gemma has not yet been run. Recheck with:

```bash
.venv/bin/python -m agents.jev --smoke
```

Current production contract: [Featherless classifier reference](https://featherless.ai/docs/api-reference-classifier).
The account-filtered classifier catalog returned the supported models; minimal invalid questions
returned 422 and an unknown model returned 404, confirming the authenticated validation route works.

A serial real-Qwen standalone comparison used the same synthetic supplier-outage branch on an isolated
in-memory theatre, beginning at 4.4% measured loss. Both runs had a six-step existing-Blue budget.

| Path | Final loss | Selected action count | Successful chat calls | Jev requests | Total duration |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing Blue | 0.0% | 1 | 6 | 0 | 155.36 s |
| Jev opt-in, HTTP-400 fallback | 0.0% | 1 | 7 | 1 | 100.61 s |

The classifier attempt took 756.4 ms. Five graph-validated proposals were presented, including critical-only
backup and four individual critical-part backups. Main retained 426,969 nodes; only this validation's
branches were cleaned up. These are single-run timings with different provider warm-up conditions, not a
performance or quality improvement claim. Gemma-assisted Blue versus existing-Blue quality remains
unmeasured. Comparison artifacts are under ignored `logs/jev-validation`, not committed match files.

The Jev-only commit snapshot was tested separately from the pre-existing strategic working-tree
changes: 134 Python tests passed, 9 skipped, and UI typechecking passed.
