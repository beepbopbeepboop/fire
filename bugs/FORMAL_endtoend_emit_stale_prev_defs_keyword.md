# FORMAL: `emit()` calls `_resolve(prev_defs=…)` which `_resolve` does not accept

`formal/x86_64_endtoend_test.py:3611` (the straight-line `emit()` step loop) calls

    _resolve(form, raw, addr, prev, k, (), None, insn.length,
             prev_defs=_SIMP_FORMS.get(prev_form, ()) if prev_form else ())

but `_resolve`'s signature (line 1008) is

    def _resolve(form, raw, addr, prev, k, cases=(), hs_in=None,
                 length=1, rip=None, code_name="rc", fs_path=()):

— there is no `prev_defs` parameter. The path-tree emitter's two call sites pass
`fs_path=fs_path` instead, so the parameter was renamed and this one call site was
left on the old keyword.

## What was run

    python3 -c "import formal.x86_64_endtoend_test as ET; \
        ET._resolve('push_r64', b'\x55', 4096, 'i0', 0, (), None, 1, prev_defs=())"

## What was seen

    TypeError: _resolve() got an unexpected keyword argument 'prev_defs'

## What was expected

The straight-line value-theorem emitter to run. It is currently DORMANT: every
corpus example is refused by `emit()`'s branching check before the step loop
(measured 2026-11-18 on `six_params` and `const2`: `value: -  (branches: …)`,
because the stack-floor guard emits a `jcc_rel32` in every prologue), so no example
reaches the call and the TypeError never fires. The moment a branch-free example
with a constant result exists — the case `emit()` exists for — the whole run dies
with the TypeError rather than proving the value theorem, and `main()` does not
catch it (only `ValueError`), so it would take the summary line down with it.

## Next step

1. Decide what the `rip` side condition needs: the docstring describes `fs_path`
   as the forms of every step walked before this one, and `_path_simp` reads
   `_SIMP_FORMS` off them. So the call site should pass the FORMS path, not the
   previous form's defs: `fs_path=<forms walked so far>`.
2. Add a branch-free, constant-result example (or a unit test that calls `emit`
   over a synthetic straight-line path) so the value path actually runs in the
   suite, then verify the `rip` conditions still close on it.
