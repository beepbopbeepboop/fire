# CODEGEN: `_local_sibling_module_exports` prints debug lines on a normal compile

**Found:** 2026-11-12, while running `python3 test_gimple.py` as the quick test
for the tuple-slot mixed-container refusal review. Pre-existing on master; not
touched by this lane.

## Symptom

`mojo/backend_gimple/emit_methods.py` prints two debug lines around every
sibling-module export lookup, with `flush=True` and no env guard, from inside
the ordinary (non-selfhost) compile path:

    3731:  print(f"BEFORE_EXPS: {module_name}.{method_name}", flush=True)
    3735:  print(f"AFTER_EXPS: {module_name}.{method_name}", flush=True)
    3737:  print(f"EXPS_ERR: {e}", flush=True)

Measured: `python3 test_gimple.py`'s output contains 8 such lines
(`BEFORE_EXPS: q.sub.tri` / `AFTER_EXPS: q.sub.tri` from the bare-submodule
fixture) among the pass/fail lines. Any `fire.py build` that reaches this path
prints them on stdout too.

They came in with `19576d579` ("Fix stdlib compilation issues from bug
reports", 2026-11-03) and were never guarded or removed.

## Expected

A successful compile prints nothing unless the user asked for diagnostics;
debug instrumentation is behind an env var or gone. As it stands the lines are
indistinguishable from compiler output for a script that captures stdout.

## Next step

Delete the three prints (the `try/except` that sets `_mgc_exps, _mgc_qual =
None, None` on error stays). If they are still wanted for debugging, wrap them
in one `os.environ.get('MOJO_DEBUG_SIBLING_EXPORTS')` check rather than an
unconditional `print`. Verify with `python3 test_link_mode.py` (which owns
`test_bare_submodule_import_call_inside_source_tree`, the fixture that
exercises this path) and `python3 test_gimple.py`.
