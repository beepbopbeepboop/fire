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
`_infer_param_types`-vs-USES mismatch as a parameter whose call sites disagree
on container kind while its body rebinds it to one container kind) or the
value's is. Start with `monomorphize.instantiate_build` (`_t22` -> `_t25`), the
smallest of the three.

## Done when

`python3 fire.py --dump-full mojo/middle/exprtypes.py` reports no
`cannot coerce ... (incompatible container kinds)` line, and the selfhost /
bootstrap chain in `bugs/hard/GATE_red_recover-land_2026-11-02.md` can be
re-enabled.

## Sites, re-measured 2026-11-14 (temporary instrumentation at the chokepoint)

The three sites named above are not the whole set. Printing
`gen._current_filename` / `gen.current_func_name` / the enclosing
`gen._current_func_node` at `_sce_simple_emit`'s refusal gives, in one
`--dump-full comptime.py` run:

| file | `current_func_name` | enclosing node | value -> dest |
|---|---|---|---|
| gimple_codegen.py | `_merge_struct_inheritance_resolve` | `_selfhost_syms` (line 653) | `MojoDict *` -> `MojoList *` |
| gimple_codegen.py | `_run_pipeline__walk_diag_fns` | `_relocate_module_instance_defs` (6285) | `MojoDict *` -> `MojoList *` |
| monomorphize.py | `instantiate_build` | `compile_fn` (915) | `MojoSet *` -> `MojoList *` |
| comptime.py | `_build_dylib_build` | — | `MojoSet *` -> `MojoList *` |

Two notes for whoever fixes it. First, `gen._current_line` is `None` in the
refusal, so the error message's `file:line` is line-less and the mangled
`current_func_name` (`_merge_struct_inheritance_resolve`, `instantiate_build`,
`_build_dylib_build`) does NOT appear in the source — those are derived names,
so grep for them finds nothing. The enclosing top-level function is the
source-visible handle. Second, all four are the SAME shape: a destination the
inference said `MojoList *` and a value that is really a `MojoDict *`/`MojoSet *`,
which is the parameter container-kind inference class that the silentnoop
`pick` refusal belonged to (fixed in e4a2cc2ed, "specialize literal-kind mixed
params including None/comprehensions").

## Root cause of the last one (2026-11-14): `GimpleGen(no_mangle=...)`

The final refusal, `monomorphize.py:1146 in function instantiate_build`
(`cannot coerce MojoSet * to MojoList *`), was not an inference bug at all:

```python
gen = GimpleGen(emit_entry_points=False, module_name='', no_mangle={mangled})
```

`{mangled}` is a SET literal, but the parameter was declared

```python
def __init__(self, ..., no_mangle=(), relaxed_imports: bool = False, ...):
```

with an unannotated `no_mangle` whose default `()` the compiler types as
`MojoList *`. Every one of the three call sites that pass a set literal
(`comptime.py:67`, `tools/repro_indexlist.py:38`, `monomorphize.py:1146`) was
therefore a set-into-list coercion, and the first one reached in a
whole-program compile aborted it. The parameter is used only as
`set(no_mangle)`, and the body's own field is annotated `set[str]`, so the
declaration now says what it always meant:

```python
no_mangle: set[str] = (),
```

Measured: `python3 fire.py --dump-full monomorphize.py` reports **0**
`cannot coerce` lines and `✓ Generated monomorphize.ci` (was 1 refusal and a
failed compile).

Note the diagnostic's `monomorphize.py:1146` was the ENCLOSING function's line,
not the failing statement's — the same derived-name/line caveat as above.

## Status 2026-11-14: the coercion refusals are FIXED; the chain is not yet green

`GimpleGen.__init__`'s `no_mangle` parameter is now annotated `set[str]` (was
unannotated with a `()` default the compiler typed `MojoList *`), which is the
root cause above. Measured:

- `python3 fire.py --dump-full monomorphize.py` -> **0** `cannot coerce` lines,
  `✓ Generated monomorphize.ci`.
- `python3 fire.py --dump-full fire.py` -> **0** `# ERROR` lines and **0**
  `cannot coerce` lines; the `unavailable in compiled mode` weak-stub count
  goes **178 -> 119**.
- `test_gimple.py` 460/0.

What still blocks `bootstrap-stage1-transitive` is a DIFFERENT check: its
`reject=CLOSURE_INCOMPLETE` refuses the run on ANY
`unavailable in compiled mode` stub, and 119 remain (the GATE doc's own repro
is `grep -c 'unavailable in compiled mode' fire.ci`, first measured at 26).
So the gate entries stay OFF — re-enabling them now would make the landing
gate red. The full `fire.py build fire.py` link also still fails, on gcc
errors unrelated to the container kinds. Those are the remaining work; this
doc's specific defect is done.
