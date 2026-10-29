# Worker pool cutover: from environment variables to one pool file

Decided 2026-10-29 (architect: the orchestration owner's agent; the user approved the direction).

## Why

Today the worker pool lives in environment variables (`CONTROL_MODEL`, `CONTROL_FALLBACKS`, `CONTROL_CAPS`) and in
constants in `tools/control.py` (`MODEL_CAPS`, `FALLBACKS`). Every change means restarting the swarm with a new
environment, and the pool the swarm believes in can differ from the one running. On 2026-10-29 that gap left a free
slot idle for hours: the swarm knew only OpenRouter, the only other free model was banned, and a hand-started
Qwen worker was invisible to refill.

## Decision

One committed file, `tools/pool.json`, is the single source of the pool:

```json
{
  "slots": [
    {"model": "openrouter/openrouter/free",            "slots": 1, "kind": "opencode"},
    {"model": "omlx/Qwen3.8-27B-oQ4e-mtp",             "slots": 1, "kind": "opencode"},
    {"model": "opencode/deepseek-v4.1-flash-free",     "slots": 1, "kind": "opencode"}
  ],
  "feed":   ["bugs/*.md", "bugs/hard/*.md"],
  "skip":   ["FORMAL_", "COMPILE_FAIL_", "MERGE_", "OPEN_WORK", "PERF_memory_over", "DOCS_"],
  "retry_hours": 12
}
```

- `refill` assigns each queued task to the FIRST pool entry with a free slot whose model is not banned; the entry's
  `slots` is the cap. There is no separate `CONTROL_CAPS`.
- The swarm's `--target` becomes the sum of the pool's `slots`, read from the file. No flag to keep in sync.
- `CONTROL_MODEL` / `CONTROL_FALLBACKS` / `CONTROL_CAPS` are removed. The file is the only way to change the pool.
- `kind` names how a worker is run. Only `opencode` exists today. A Claude Code agent is NOT a pool entry: it is
  started by the Claude session with `control.py claim` (it holds claims but is not refilled), because the Claude
  session owns its own budget and the Haiku/Sonnet choice. A later cutover can add `kind: "claude"` if a Claude
  session should be refilled by the swarm; that needs its own plan.
- Bans (`dead_models.json`) are still per model and still time-limited. A model's recovery is handled by
  `ping`: `tools/ping_pool.py` tries each banned model every `retry_hours` and lifts the ban on a real reply.

## Steps

1. Write `tools/pool.json` with the three entries above (already the live pool).
2. `control.py`: read the pool file; drop the env-based `MODEL`/`FALLBACKS`/`MODEL_CAPS` as sources of truth. Keep
   `CONTROL_POOL_FILE` as an override for tests.
3. `refill`: pool-driven assignment as above; tasks queued without a model take the pool order.
4. `swarm.py`: `--target` defaults to the pool's slot total; the feed scans the `feed` globs and skips the `skip`
   prefixes; remove the hard-coded lists.
5. `tools/ping_pool.py`: replaces the one-off shell loop. Runs every `retry_hours`, pings each banned pool model.
6. Test: a unit test in `tools/test_control_pool.py` with a temp registry: (a) two models, one busy, the task goes to
   the second; (b) a banned model is skipped; (c) all banned -> nothing starts; (d) target equals the slot sum.
7. Cut over: stop the swarm, start it with no environment variables, check `refill` fills every slot, then delete the
   old environment setup from the notes.

## Rollback

Restore the three environment variables and the old constants; the file and the new code are additive until step 2.

## Open questions

- Whether a Claude Code agent should be refilled by the swarm (today it is started by hand and claimed).
- Whether `kind: "claude"` should use the Claude Code `Agent` tool (in-session) or a separate process. Not decided here.
