# `selfhost` is RED on the branch base: 67 distinct gcc errors across the
# compiled closure, and the self-host path is what the two other `expect=`
# markers call a pre-existing SIGSEGV

## Status

OPEN, and PRE-EXISTING ON THIS BRANCH'S BASE — measured 2026-10-02 while
verifying a branch that had changed four files inside the compiled closure.
Found by running the job twice, from the branch tip and from
`git archive HEAD`, and diffing the error sets. Not caused by that branch: its
own four changes accounted for four errors, which were fixed; everything below
was already there.

CLAUDE.md's table says `selfhost` is a passing `make gate` step with a measured
3.7 GB peak, and `bugs/UNTESTED.md`'s status line does not contradict it. So
either the table is stale or something regressed without anyone noticing —
which is a question worth answering rather than assuming either way, because the
answer decides whether this is a regression hunt or a documentation fix.

## What I ran, and what I saw

Two full runs of `python3 tools/suite.py selfhost`, one per tree, ~8 minutes
each, both peak ~2.2-2.3 GB:

```
branch tip (work/bugs4-10)      selfhost FAIL 473 s  peak 2.2 GB
branch base (git archive HEAD)  selfhost FAIL 515 s  peak 2.3 GB
```

Then the error sets, reduced to the distinct `error:` strings (file:line and
the temp paths normalised away):

```
branch tip     67 distinct errors
branch base    67 distinct errors
comm -23 (only in mine):  (empty)
comm -13 (only in base):  (empty)
```

**Identical.** So the job is red for exactly the same reasons on both trees,
which is the useful part: this is a standing red, not a regression from the
work that found it.

### The failing summary line

```
self-host closure: 60 modules, every generator/async lowered in place: True
self-host closure: 1420 functions, 1 of them declared in fire_runtime.h under a
  pinned C name; every such declaration matches its definition: True
✗ self-host compile/link regressed (GCC error, ICE, undefined symbol, or the
  produced binary cannot compile)
```

The first two lines PASS. So the closure walk, the generator lowering and the
hand-written signature table are all fine; it is `gcc` on the generated C that
rejects it. The test's own verdict word, "regressed", is what makes this
worth pinning rather than ignoring: it means "the produced binary does not
build", and it says it every run.

### What the 67 errors are, by family

| count | shape | where |
|---|---|---|
| 27 | `struct _<module>_toplev has no member named 'X'` | `emit_funcs.py` (`_TYPE_MAP`, `_FIXED_ARRAY_ANN_RE`, `_SELFHOST_EXTRA_FIELD_CACHE`), `emit_infra.py` + `funcs_shared.py` (`_module_loader`), `module_gen.py` (`_C_RESERVED_FUNCS`, `_FIXED_ARRAY_ANN_RE`), `build_stdlib_dylib.py` (`STDLIB_PATH`), `resolve_shared.py`, `module_shared.py` |
| 25 | `'_mojo_elem_repr_<Node>' undeclared (did you mean '_mojo_sizeof_<Node>'?)` | `mojo/middle/coro.py` (15 `IdentExpr`, 6 `CallExpr`), `fire_compiler.py`, `regex_compile.py`, `mojo/middle/offload.py` |
| 16 | `passing argument 1 of 'mojo_repr_list_ints' makes pointer from integer` | `mojo/backend_gimple/emit_methods.py` |
| 5 | `_mojo_elem_repr_X undeclared` (no `_mojo_sizeof_` suggestion) | assorted |
| 2 | `non-trivial conversion in 'component_ref'` / `'var_decl'` | `myinterpreter.py` |
| rest | one each: a conflicting signature, an implicit declaration, a pointer/integer assignment, an arity mismatch on `myinterpreter_MojoFunction___call__`, an undefined type | |

**Three families, and they are three defects rather than 67.** That is the
useful shape of this finding: the first two are one bug each wearing many
costumes, and a per-error fix would be 27 edits of the same thing.

1. **A module-level global that is not in its toplev struct.** Every one of
   the 27 is a name the source assigns at module scope (`_TYPE_MAP`,
   `_module_loader`, `STDLIB_PATH`, …) and the self-hosted emitter did not emit
   a field for. `_selfhost_extracted_fn_index` / `funcs_shared`'s
   `_selfhost_module_scalar_globals` are the passes that decide what a
   module-level global becomes; they are admitting function-level names, not
   module-level ones, for these particular globals.
2. **`_mojo_elem_repr_<Node>` not emitted.** The hint says
   `_mojo_sizeof_<Node>` exists, so the SIZE helper is emitted and the REPR
   helper is not: the same admission decision, in the other direction, for
   `IdentExpr`/`CallExpr` in `mojo/middle/coro.py` and `fire_compiler.py`.
3. **`mojo_repr_list_ints` / `_mojo_repr_list` handed a scalar.** The
   int64_t-boxed-node problem this tree documents repeatedly, in
   `emit_methods.py` — 16 sites of it.

## The exact next step

1. Answer the standing question first, because it is cheap and it decides the
   rest: **when did this go red?** Bisect `selfhost` over the commits between
   the last commit where it was green and this branch's base. `tools/suite.py`
   caches a PASS and re-runs a FAILURE, so a bisect is one ~8-minute job per
   step — expensive, which is why it is not this pass's job, but nothing else
   here can be scoped until it is answered. A commit range from
   `git log --oneline -- tools/suite.py | head -40` narrowed by whether the
   error families appeared together is the cheap first cut: family 3
   (`emit_methods.py`) is a single file and a single fix, so if it is present
   throughout the range the regression is older and wider.
2. If it is older than the last recorded green, the fix is CLAUDE.md's table:
   `selfhost` needs an `expect=` marker naming these three families, exactly as
   `native-dumpfull` and `bootstrap-stage2-dumps` carry one. **Not before the
   bisect**, because the alternative reading is a regression and a marker on a
   regression hides it.
3. Family 1 and family 2 are the same decision in
   `funcs_shared._selfhost_module_scalar_globals` /
   `_selfhost_extracted_fn_index`: one predicate, "does this module-level
   binding need a struct field", and 52 of the 67 errors are one edit. Start
   there — it is the largest single win and the cheapest to verify (one
   `selfhost` run).
4. Family 3 is its own pass in `emit_methods.py` and needs no new machinery.

## Note for whoever picks this up

`selfhost` being red does not make `make gate` green-in-the-large: it is a
`check` job, so `check` is red on this tree and has been for as long as the
regression has existed. Everything else on this branch was verified against
narrow suites (`test_gimple.py`, `test_gimple_runner.py`,
`test_gimple_generator_runner.py`, `test_suite.py`) precisely because the
everyday bucket is not a usable signal while this is open.