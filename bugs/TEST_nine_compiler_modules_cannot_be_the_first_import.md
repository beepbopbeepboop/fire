# Nine of the compiler's own modules cannot be the FIRST import in a fresh interpreter

## Status: OPEN, and pre-existing. Found 2026-10-03 by
## `suite-self-test` while merging master into `work/merge-bugs3-r3`; NOT caused
## by anything that merge or its conflict resolutions touched, and reproducible on
## the pre-merge tree (see "How to reproduce" — the second command was run
## before any edit of the session).

## What I ran

    python3 tools/suite.py suite-self-test
    # FAIL  suite-self-test  (42s)  exit 1

    # FAIL  imports: every real entry point imports first:
    #   mojo.middle.calls_shared: ImportError: cannot import name
    #     'user_dunder_repr_call' from partially initialized module
    #     'mojo.middle.calls_shared' (most likely due to a circular import)
    #   mojo.middle.funcs_shared: ... '_SELFHOST_EXTRA_FIELD_CACHE' ...
    #   mojo.middle.infra_infer: ... '_FC_SEP' ...
    #   mojo.middle.loops_shared: ... '_gfl_declare_target_name' ...
    #   mojo.middle.methods_shared: ... '_is_selfhost_source_file' ...
    #   mojo.middle.module_shared: ... '_LIST_RETURNING_METHODS' ...
    #   mojo.middle.resolve_shared: ... '_calls_in_stmts' ...
    #   mojo.middle.stmts_shared: ... '_annotation_container_elem_type' ...
    #   mojo.backend_gimple.module_gen: ... '_FC_SEP' ...

## How to reproduce

The check imports each entry point in its OWN fresh interpreter, so the cycle is
visible directly:

    python3 -c "import mojo.backend_gimple.module_gen"
    # ImportError: cannot import name '_FC_SEP' from partially initialized
    # module 'mojo.middle.infra_infer' (most likely due to a circular import)

Nine entry points fail, so nine fresh interpreters are involved; `module_gen` is
the one that names the bottom of the chain. The cycle is:

    mojo/backend_gimple/module_gen.py:42      import mojo.middle.infra_infer
      -> mojo/middle/infra_infer.py:21        import gimple_codegen
        -> gimple_codegen.py:738              import mojo.backend_gimple.emit_methods
          -> mojo/backend_gimple/emit_funcs.py:42   import mojo.backend_gimple.emit_calls
            -> mojo/backend_gimple/emit_exprs.py:42  import mojo.backend_gimple.emit_infra
              -> mojo/backend_gimple/emit_infra.py:60 from mojo.middle.infra_infer import (...)
                -> _FC_SEP is not bound yet; the module is still executing
                   line 21

`gimple_codegen.py`'s own comment says the cycle is deliberate and that
reading these names from `module_shared` instead "would close the cycle
`module_gen -> module_shared -> gimple_codegen -> module_gen`" — the ordering
was arranged so that importing `gimple_codegen` FIRST works, and
`mojo/middle/types.py`'s import of it was placed for the same reason. What is
missing is the same guarantee for the other nine entry points.

## Why it matters

`python3 -c "import <module>"` is not a thing any user runs, but it is the shape
every "does this import cleanly on its own" question takes, and this check is
the regression guard for it. Right now the guard is red for nine modules, so it
guards nothing for them: a new cycle introduced into any of the nine would be
absorbed into a row that is already red.

## Exact next step

Break the cycle at its widest point rather than moving nine imports: the chain
only exists because `mojo/middle/infra_infer.py:21` imports `gimple_codegen`
"constants used by some extracted helpers" (its own comment). If those helpers
read the handful of `gimple_codegen` CONSTANTS they need through a late import
inside the function body — the pattern `mojo/backend_gimple/module_gen.py` is
already forced to use for the same reason, and the reason the
`mojo.middle.types` import is placed where it is — then `infra_infer` stops
reaching `gimple_codegen` at module scope and every entry point in the chain
imports on its own.

`python3 -c "import <module>"` for each of the nine, one at a time, is the test;
`suite-self-test`'s row is the place it is already asserted.