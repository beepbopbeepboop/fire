# Gate job `sqliteruntime` is red: sqliteruntime job timed out at 600 s

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

### 2026-10-29 — reproduced alone; root cause located to the in-process closure compile (planning round)

**Reproduced, and it is not load.** On branch `work/bug-runtime-gate-sqliteruntime-red`
(HEAD `c803f1da6`; master `db6998de0` is three commits ahead, the dylib dedup
changes plus a control.py docstring, and has NOT been measured alone yet),
`python3 tools/memslot.py --gb 8 --label sqlite -- python3 test_sqlite3_runtime.py`
run ALONE did not finish in 10 min 15 s and was killed by hand. The suite's
timeout is 600 s, so the gate's `TIMEOUT` reproduces with no concurrent jobs.
The `2026-09-28` note in `tools/suite.py` (~100 s, 64/64) is no longer true of
this tree.

**Where the time goes.** The stall is in `test_probe_ignores_mentions`, the
second in-process compile (`test_fire_python_is_deliberately_excluded`'s
`fn main(): print(1)` compile hits the CAS and takes 0.2 s; the stall is the
compile of `from build_config import find_gcc` with `do_imports=True`).
Measured in isolation with `compile_to_gimple(..., do_imports=True)`:

- Under a 60 s sampler (`.tmp/probe3.py`, main-thread stack every 8 s) the
  stack is always inside `_compile_imported_module` → `gen_module` →
  `_compile_imported_module` nested several levels deep, with the leaves in
  `py_tokenize`/`parse_module`/`_detect_generator`/`_rewrite_node`. It is
  CPU-bound Python, not a subprocess (`pgrep -P` on the test shows no children).
- Call counting (`.tmp/probe4.py`, spy on `emit_resolve._compile_imported_module`)
  at ~60 s: **169 calls, 169 distinct modules**, no repeats yet. The closure
  is `build_config` → `module_loader` (line 76 of `build_config.py`, a
  top-level `from module_loader import STDLIB_PATH, TEST_PATH`) → `os`,
  `ctypes`, `pathlib`, `pathlib.Path`, and everything those pull in. Each is
  compiled through the Mojo compiler's own import machinery, not skipped.
- Two modules in that closure fail codegen with the container-kind guard
  (`mojo/backend_gimple/emit_resolve.py:2303`, `_sce_simple_emit`, a deliberate
  refusal added 2026-09-23 f785141ef2):
  `mojo.backend_gimple.emit_infra` (`MojoList * to MojoSet *`, `_t34`→`_t35`)
  and `formal.model` (`MojoSet * to MojoList *`, `_t3`→`live`). These are
  wrong container-kind INFERENCES, the same family as the other CODEGEN docs;
  the guard is correct to refuse them.
- A failed module takes the fallback in `emit_resolve.py` ~L1180-1215: it prints
  `# ERROR: compiling imported module ...`, then rolls back every module /
  struct / helper added during the failed attempt (`gen._compiled_modules`,
  `_emitted_structs`, etc.) so the outer module recompiles them and inlines
  their source. Those rolled-back modules are then compiled again by the next
  parent that imports them. The `# ERROR` lines in `.tmp/sqlite1.log` show
  emit_infra 3× and formal.model 2× before the run was killed, so the
  rollback is re-doing real closure work.

**What is NOT yet established (the next round must measure these first):**

1. Whether the 169-module walk is itself the cost (a clean closure of this size
   is expected to be seconds-to-minutes, not >10 min) or whether it is the
   rollback recompiles (count of calls per module after ~5 min, and per-module
   wall time). Probe `.tmp/probe4.py` is ready; extend it to let it run to
   completion (about 15 min) and print the per-module repeat counts.
2. Whether the closure grew since 2026-09-28. Check `git log` on
   `build_config.py`, `module_loader.py`, `module_gen.py`, `emit_resolve.py`
   for the commits that changed the `_compile_imported_module` fallback.
3. Whether `build_config` → `module_loader` → `ctypes` is supposed to be inside
   the closure at all. `module_loader` is the stdlib path resolver; the closure
   that matters for the probe is "does this module pull a runtime unit", and
   that can be answered without compiling `ctypes`/`pathlib`.

**Decisions the next round needs (with the readings above):**

- **D1, the test or the compiler?** If the closure walk is legitimately
  expensive, the fix is performance in the import walk (see
  `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`, which
  says the `_walk_ast` memo landed but `_collect_self_assigns` is open). If the
  walk is pathological because of rollback-recompiles, the fix is to memoise
  the failed-module outcome per compile so a module that failed once is not
  recompiled per parent. Do NOT shrink the test to avoid the closure: the probe
  is supposed to see a real `build_config` import (CLAUDE.md, "the probe on a
  real codegen run").
- **D2, the container-kind inferences in `emit_infra.py` and `formal/model.py`.**
  These are real codegen bugs and are NOT this doc's to fix. File or extend a
  `CODEGEN_` doc naming the two modules and the `_t34`/`_t3` temps, and mark
  this doc as depending on it. The guard at `emit_resolve.py:2303` stays.

**Implementation plan for the next round (once D1 is decided by measurement):**

1. Files: `mojo/backend_gimple/emit_resolve.py` (`_compile_imported_module`,
   the fallback block ~L1180-1215, and the rollback sets), and possibly
   `gimple_codegen.py` (`_compile_imported_module` shim at L5505).
2. If rollback-recompile is the cost: add a per-compile `failed_modules` set on
   the root `GimpleGen`; on a repeat call for a module in it, skip the compile
   and take the source-inclusion path directly. The output must be byte-identical
   for a closure with no failures, and for a closure WITH failures compare the
   emitted C before/after with `cmp` on the sqlite probe's compile output.
3. Test (quick, next to `test_sqlite3_runtime.py`): a call-count pin, i.e. a
   spy on `_compile_imported_module` asserting each module is compiled at most
   once per root compile on the `build_config` probe. Fails before, passes after.
   Plus run `python3 test_sqlite3_runtime.py` alone under
   `python3 tools/memslot.py --gb 8 --label x --` and require it to finish inside
   the 600 s timeout with the same 64/64 checks.
4. Gate, integrator's job: `stdlib-syntax` `U` count and `stdlib-dylib` `skip`
   count must not increase (CLAUDE.md, "Two gate verdicts"), since the rollback
   path is shared with every stdlib compile.

## Gate output (first lines)

```
# ERROR: compiling imported module 'formal.model' from /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
# ERROR: compiling imported module 'formal.model' from ./formal/model.py: cannot coerce MojoSet * to MojoList * (incompatible container kinds) at /Users/mrs/net/chatgpt/claude/work-spanfix/formal/model.py: value='_t3' dest='live'
  ... 214/218 jobs done, 4 running, 1096s elapsed
  ... 214/218 jobs done, 4 running, 1126s elapsed
  ... 214/218 jobs done, 4 running, 1157s elapsed
  exit: 0   secs: 674.5   peak: 0.4 GB
```

## What to check first

a hang or a very slow build; rerun alone and time it.

## Next step

1. DONE 2026-10-29: run alone on this branch it exceeds 600 s (killed at 10 min 15 s), so it is not load. See the 2026-10-29 entry above.
2. Measure the two open questions in that entry (closure walk vs rollback recompiles; closure growth since 2026-09-28), then take decision D1.
3. Fix the root cause and add the call-count pin test; delete this doc when the test passes alone within the timeout.
