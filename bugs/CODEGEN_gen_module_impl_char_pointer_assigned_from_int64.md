# CODEGEN: `gen_module_impl` is compiled with `assignment to 'char *' from 'int64_t' makes pointer from integer without a cast`, breaking the self-host build

Status: OPEN. Filed 2026-11-12 from a failing self-host build. No repro and no confirmed cause: the reported line is not the faulting statement. Class: easy (find the statement, then one conversion).

## Symptom

```
mojo/backend_gimple/module_gen.py: In function 'mojo_backend_gimple_module_gen_gen_module_impl_7e9a9f':
mojo/backend_gimple/module_gen.py:13818:19: error: assignment to 'char *' from 'int64_t' {aka 'long long int'}
    makes pointer from integer without a cast [-Wint-conversion]
13818 |     # base's would read `_classattr_Base__tag` where CPython reads Child's,
```

Line 13818 of `module_gen.py` is inside a long comment block (about per-receiver-class generator units); nothing there can fail. gcc's line is the last `#line` plus the generated lines since (the per-physical-line stamp in `emit_infra._emit_raw` now gives every statement line its own directive), so the real statement is somewhere after the statement that starts near line 13806 (`self._compile_nested_async_functions(s, _async_fns)`) in `gen_module_impl`.

## Suspects (hypotheses, not findings)

`mojo/backend_gimple/module_gen.py` and the module-global machinery changed today (2026-11-12): `13d52e192` (store module-scope class attributes whose value is a typed call), `6228c22c0` (a float module global is a double everywhere), and the landing `203fd5ea3` (imported float global access). The comment text near the reported line mentions class attributes (`_classattr_Base__tag`). A local of type `char *` receiving an `int64_t` value is the kind of mismatch a typed class-attribute or module-global store would produce when the value's type is inferred as an integer but the variable is a string/pointer.

## Scope

1. Locate the statement: generate `fire.ci` for the self-host closure (or compile just `mojo/backend_gimple/module_gen.py` as a module) and read the generated lines of `gen_module_impl` after its statement at about line 13806 for an assignment whose left side is `char *` and right side an `int64_t` expression; or bisect over today's commits listed above (one `--dump-full` plus `gcc -fgimple -c` per step).
2. Reduce it to a small program and add it as a regression test.
3. Fix the conversion at its source (the type that was inferred wrongly), not by a cast at the use.

## Acceptance

- The statement is named in the fix's commit message, with the source line it came from.
- A regression test compiles the reduced program under `gcc -fgimple` with `-Os -g -ftrivial-auto-var-init=zero` and passes.
- `gen_module_impl` no longer produces `-Wint-conversion` errors in the generated C.

## Done when

The regression test passes. The full self-host `fire.o` step is the integrator's check; a worker reports it as not run.
