# CODEGEN: `cannot coerce <Set/Dict> * to MojoList *` blocks the selfhost, `--dump-full` and the bootstrap gate jobs

**Found:** 2026-11-13, while fixing the membership false positive that had been
refusing two of the compiler's own modules (see the commit that landed
`_definitive_binding_type`'s scalar-annotation check). That refusal stopped
compilation early and MASKED these; with it gone, `--dump-full
mojo/middle/exprtypes.py` proceeds and reports three:

```
# ERROR: compiling imported module 'comptime' from comptime.py:
  cannot coerce MojoSet * to MojoList * (incompatible container kinds)
  at comptime.py in function `_build_dylib_build`: value='_t3' dest='_t6'
# ERROR: compiling imported module 'gimple_codegen' from gimple_codegen.py:
  cannot coerce MojoDict * to MojoList * (incompatible container kinds)
  at gimple_codegen.py in function `_run_pipeline__walk_diag_fns`: value='_t37' dest='_t29'
# ERROR: compiling imported module 'monomorphize' from monomorphize.py:
  cannot coerce MojoSet * to MojoList * (incompatible container kinds)
  at monomorphize.py in function `instantiate_build`: value='_t22' dest='_t25'
```

The first of these was already visible before the membership fix (the same
`gimple_codegen._run_pipeline__walk_diag_fns` line appears in the pre-fix
log), so this is not a regression from that change — it is a pre-existing
defect that the earlier refusal hid.

## Why it matters

These three are what still block, in order:

- `python3 fire.py --dump-full fire.py` (the repro in
  `bugs/hard/GATE_red_recover-land_2026-11-02.md` for the bootstrap jobs),
- `make mojoc` / the selfhost,
- `bootstrap-stage1-transitive` and its stage2/stage3 siblings, which are
  turned OFF in `tools/gates.json` until that repro is clean.

## Reproduce

```
cd /Users/mrs/net/gcc/gcc/fire/fire
python3 fire.py --dump-full mojo/middle/exprtypes.py 2>&1 | grep 'cannot coerce'
```

(Compiling any module that imports the three above reaches the same errors.)

## Next step

Read each `dest=` binding: the emitter has decided the destination is a
`MojoList *` while the value it is handed is a `MojoSet *` / `MojoDict *`.
Either the destination's recorded kind is wrong (the same
`_infer_param_types`-vs-USES mismatch that
`bugs/CODEGEN_param_container_kind_across_call_sites_refused.md` describes for
a parameter) or the value's is. Start with
`monomorphize.instantiate_build` (`_t22` -> `_t25`), the smallest of the
three.

## Done when

`python3 fire.py --dump-full mojo/middle/exprtypes.py` reports no
`cannot coerce ... (incompatible container kinds)` line, and the selfhost /
bootstrap chain in `bugs/hard/GATE_red_recover-land_2026-11-02.md` can be
re-enabled.
