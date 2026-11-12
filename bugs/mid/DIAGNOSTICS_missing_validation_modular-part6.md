# DIAGNOSTICS missing-validation part 6: refuse mutually recursive generic instantiation (and cap elaboration depth)

Class: **mid** (this doc lives in `bugs/mid/`). It generalises an existing
per-template self-call check and adds a depth cap around an instantiation loop
that currently ends in a silent stub.

Parent: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` (the
elaboration-recursion remainder). Plan:
`docs/diagnostics-missing-validation-plan.md` §5, measured against
`elaboration_error_recursion1.mojo`.

## Goal

An uninstantiable recursive generic must be refused with a diagnostic, in both
the in-TU and the `.o` elaboration paths. Direct self-recursion already is;
mutual recursion is not — it silently compiles a stub that answers 0.

## Current state (measured 2026-11-12)

- Direct self-recursion is refused: `fire.py build` on
  `def self_recursion[i: Int]() -> Int: var x = self_recursion[i + 1](); return x`
  exits 1 with
  `cannot compile module: self recursive call to 'self_recursion' will cause an infinite loop`.
  The checks are `mojo/backend_gimple/elab_intu.py` (~3100, the in-TU pass),
  `mojo/backend_gimple/emit_resolve.py` (~2999/3015) and
  `mojo/backend_gimple/emit_calls.py` (~3135), plus the shared
  `self_recursive_uninstantiable` (`emit_calls.py`, ~1858).
- Mutual recursion is silently accepted:
  `def a[i: Int]() -> Int: return b[i + 1]()` /
  `def b[i: Int]() -> Int: return a[i + 1]()` called as `a[1]()` builds with
  `rc=0`, no diagnostic, and the binary runs. The in-TU check compares the
  callee base with `rec['base']` only, and `a`'s body calling `b` is a
  different base; `b[i + 1]` then has a non-concrete argument, so
  `_concrete_args` returns `None` and the call becomes a weak stub. The
  modular file's own expectation is that this is an error, with the
  `elaborator expansion is N levels deep - infinite recursion?` /
  `error recurses N times` notes.
- `monomorphize.ELAB_DEPTH` (~943) already counts nested instantiation builds
  (incremented and decremented around the CAS build, ~1186/1200) but is used
  only for the optional `MOJO_ELAB_LOG` trace.

## Scope

1. **Generalise the in-TU refusal.** In `elab_intu.py`'s `visit`, a bracketed
   generic call inside a concrete (monomorphized) template that is not all
   concrete must be refused, not left to become an extern stub — that is the
   actual defect, and `base == rec['base']` is only its commonest shape. Keep
   the existing wording when `base == rec['base']` (the regression pins it);
   for another callee name it and say the instantiation cannot be materialized.
   Apply the same rule to the `.o` route's calls
   (`emit_resolve._elaborate_generic_call` and the `emit_calls` stub arm).
2. **Depth cap.** Turn `ELAB_DEPTH` into a hard guard as well as a trace: a
   nested elaboration deeper than a documented limit (modular's default is 128,
   `--elaboration-max-depth`) raises
   `elaborator expansion is N levels deep - infinite recursion?` and must
   unwind (`ELAB_DEPTH` decremented on the error path too). This is the guard
   for cascades the concreteness test cannot see, and it is what makes an
   unanticipated shape fail in bounded work rather than loop.
3. Do not swallow the error in the instantiation `try/except`: the existing
   re-raise path for compile-time diagnostics from an instantiated body
   (`emit_resolve.py`, ~3476) is the precedent; a refusal must surface as a
   nonzero build, not fall through to the stub.
4. If the diagnostic plumbing has a note channel, attach
   `error recurses N times` with the observed depth; the two load-bearing
   strings are the ones in Acceptance.

## Acceptance

- The direct self-recursion program still exits nonzero with
  `self recursive call to 'self_recursion' will cause an infinite loop`.
- The mutual `a`/`b` program exits nonzero, within a bounded time (the test
  uses a subprocess timeout), with `infinite recursion` or
  `self recursive call` in the output — no `rc=0`, no hang.
- A finite chain (`a` calls `b`, `b` returns a constant) builds and runs.
- A finite chain a few levels deep, below the cap, builds.
- The existing bracket/`comptime` diagnostics tests keep passing.

## Done when

Add `test_elaboration_recursion_diagnostic.py` beside the other
`test_*_diagnostic.py` files (do NOT register it in `tools/suite.py`) and run
exactly:

    python3 tools/memslot.py --gb 8 --label elaboration-recursion -- python3 test_elaboration_recursion_diagnostic.py

The test invokes `fire.py build` through a helper with
`subprocess.run(..., timeout=120)` for every case, so a regression that hangs
or silently accepts is a failure rather than a gate hang.

## Not in this part

The exact note inventory of `elaboration_error_recursion1.mojo` beyond the two
strings above, and recursion in the formal backends. No test registration.

## Status

- **Open.**
