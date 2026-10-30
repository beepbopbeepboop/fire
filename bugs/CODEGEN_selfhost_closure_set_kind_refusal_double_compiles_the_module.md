# CODEGEN_selfhost_closure_set_kind_refusal_double_compiles_the_module

Deterministic `cannot coerce MojoList * to MojoSet * (incompatible container
kinds)` refusals in the self-host bootstrap closure. The refusals are the
compiler's intended import-fallback path (the build still PASSES), but every
affected module compiles TWICE (the refused attempt, then the source
inclusion), which stretches the cold bootstrap to ~8 min quiet and makes
cold-worktree gate runs exceed registered job budgets. Compiler
type-resolution machinery; owner domain.

## Status (2026-10-28, master 8c19a643f — recorded from the closing-gate adjudication; no action taken)

### The refusals (reproduced byte-identically in a PASSING cold run)

`mojo/backend_gimple/emit_infra.py` (`_t34` → `_t35`) and `formal/model.py`
(`_t3` → `live`), each: `cannot coerce MojoList * to MojoSet * (incompatible
container kinds)`. Same five error lines appear in a cold quiet run that
finishes PASS 66/66 (artifacts: `T/opencode/sqliteruntime_cold_quiet.log`,
`T/opencode/sqlite_cold_repro.log`; the killed gate job's tail with the same
lines: `T/opencode/gate_full_8c19a643f.log`, worktree `build/suite.log`
line 147170 — pruned worktree, log retained).

### Why it is not a build failure, and why it still matters

The refusal is the sanctioned import-fallback: `mojo/backend_gimple/
emit_resolve.py` (~:1197 on 8c19a643f) prints the refusal, rolls back the
attempt's state, and includes the module's source instead ("a module whose
compile legitimately raises and is meant to fall back to source inclusion").
Cost: each affected module compiles twice, so the cold bootstrap (full
self-host + from-scratch libmojostdlib dylib + 13 program builds) measures
~8 min quiet.

### Measured impact (the sqliteruntime budget ladder, all real uncached runs on 8c19a643f)

| scenario | wall | result |
|---|---|---|
| warm main checkout, quiet | 71.9 s | PASS 66/66 |
| main checkout, 1st solo (dylib rebuilt), quiet | 517.1 s | PASS |
| fresh worktree, fully cold, quiet | 484 s | PASS 66/66 |
| fresh worktree, -j18 gate load | > 600 s | TIMEOUT at the registered 600 s |

`test('sqliteruntime', ...)` registers `timeout=600` (`tools/suite.py:2493`;
the suite-wide default is 3600 s). Two consecutive gate timeouts (the
dbbb8b722 gate and the 8c19a643f closing gate) are therefore PREDICTABLE in
any fresh-worktree run: ~8 min quiet-cold + the shared dylib lock (in the
closing gate another job held it 10:47-10:59, finishing 7 min after the
kill) + -j18 contention > 600 s. The scary-looking errors are not the
failure; termination and values are proven (66/66 checks, 3/3 green
formal-os reruns `T/opencode/formalos_solo1/2/3.log`).

### Class

Known recurring self-host-closure bug family: cf.
`COMPILE_FAIL_zipfile___init__.md`, `COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`,
and the 2026-09-23 formal/build.py `MojoDict * -> MojoSet *` instance behind
fire.py:594-608's importlib escape hatch.

### What a fix requires

Compiler-side: a `set`-annotated value is inferred/carrying the `MojoList *`
kind where the declaration wants `MojoSet *` — fix the kind inference so the
first compile attempt succeeds (removing the double-compile), or document the
residue as a known limit. Owner domain (type-resolution machinery); do not
ship a coercion hack that trades the refusal for a silent kind mismatch.

### Dependency / partial fix (2026-10-29)

The rollback-recompile memo fix (`_failed_modules` in `gimple_codegen` /
`emit_resolve`, commit `work/bug-runtime-gate-sqliteruntime-red`) fixed
cost that made the timeout exceed 600 s (`_failed_modules` memo in
`gimple_codegen` / `emit_resolve`). The container-kind inference bugs
(`_t34`→`_t35` in `emit_infra`, `_t3`→`live` in `formal/model`) remain open —
see "What a fix requires" above. Same commit deletes this doc, which cites the
fix's predecessor doc; the citation is replaced in-place by this header.

### Gate-calibration consequence (recorded, orchestrator/owner lever)

Either warm the gate worktree's build cache before gating (run the
long-bootstrap jobs once first) or relax the registered 600 s budget to ~1200 s
(2.5x the measured 484 s) at `tools/suite.py:2493`. Backed by measured
termination — not masking. If a warmed/relaxed gate still times out, open a
dedicated triage on the bootstrap cost itself (the fallback double-compile +
dylib-lock serialization are the two named contributors).
