# CODEGEN_generator_function: Lib/test/test_dynamic.py

## Status (updated 2026-08-07, re-verified with a real rebuild)

Re-verified against current master with an actual `mojo.py build`
rerun (the previous 2026-08-07 note below only speculated this was
task #145's pattern without rebuilding — it was WRONG). The line-161
error is **STILL PRESENT, unchanged**:
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py:161:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py:161:1: error: type mismatch in binary expression
```
`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md` (task
#145) is fixed, but that is NOT what's failing here — this is a
different, still-open `_quick_type` gap, now root-caused:

```python
def test_after_specialization(self):
    def trace(frame, event, arg):
        return trace          # <-- self-reference: trace returns itself
    ...
```
`_quick_type`'s `IdentExpr` case (gimple_codegen.py ~line 6637) resolves
a bare-name reference to a sibling/enclosing nested-function VALUE
(`return add` inside `make_adder`, where `add` is a *different*, already-
registered nested closure) via `_closure_info_for_ident`, which checks
`self._all_closures[self.current_func_name]` — the closures registered
under the ENCLOSING function currently being compiled. But `return trace`
appears INSIDE `trace`'s own body: at that point `self.current_func_name
== 'trace'`, so the lookup is `_all_closures['trace']` (trace's OWN
nested closures, empty) — never checking whether `name` equals
`self.current_func_name` itself (a literal self-reference). This is a
distinct case from the already-fixed self-recursive `yield from` bug
(task #138, which was about generator bodies) and from the covered
"return a *different* sibling closure" case — nobody has ever taught
`_closure_info_for_ident`/`_quick_type` that a function can return a
reference to ITSELF by name. Falls through to the `int64_t` default,
while the real body lowering (`_lower_IdentExpr`'s closure-value
materialization, a separate code path from `_quick_type`) correctly
returns the real `MojoBoundMethod */void *` closure value — the same
forward-declared-vs-actual-body mismatch shape as the comprehension bug,
but a different root cause and a different, so-far-single occurrence.

Confirmed via direct read of `gimple_codegen.py`'s `_quick_type`/
`_closure_info_for_ident` (~lines 6637-6652, 6572-6586); not fixed here
(single confirmed occurrence, doesn't yet meet this project's "recurs
≥2 times" bar for promotion to its own `bugs/hard/*.md`; also, per this
file's own prior notes, out of scope either way — none of `test_dynamic.
py`'s own 4 real generators are implicated).

## Status (updated 2026-08-07, superseded above — was not rebuilt, wrong)

`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md` (task
#145, referenced below re: line 161's error shape) is now fixed. This
file's own mention was only ever a speculative "matches the shape"
note (the exact triggering expression wasn't independently read from
source), not re-investigated further here.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `invalid conversion from 'void*'` .cpp error no longer
reproduces. `test_dynamic.py`'s 4 own generator sites (all `yield
len(x)`, lines 53/54/112/113 — nested closures inside test methods) do
not appear in the current error list and have no "not eligible"
refusal.

**Classification: likely NOT a generator-codegen-cluster failure**, but
not fully traced this pass. Only 2 current errors, both at the same
line/col:
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py:161:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py:161:1: error: type mismatch in binary expression
```
Line 161 is `def test_after_specialization(self):` (a method containing a
nested `def trace(frame, event, arg):` closure, not itself a generator)
— the error SHAPE matches the `_quick_type`-family gap
(`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md`'s
sibling pattern: forward-declared-vs-actual-body return type mismatch),
but the exact triggering expression wasn't read from source in this
pass. Not investigated further — out of scope for this generator-
codegen cluster either way (the 2 errors don't implicate any of this
file's own generators).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_dynamic.py
