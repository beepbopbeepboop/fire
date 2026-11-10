# CODEGEN_class_capture_of_a_bound_name_the_walk_misses_is_a_snapshot

## Summary
A class declared inside a function whose method reads an enclosing LOCAL whose
first binding comes after the `class` statement is still captured by VALUE (a
snapshot at the class statement, read before the local was ever written) when
the local's binding shape is one `mojo.middle.boundnames`' walk does not see.
Measured with a `match` case:

```python
def f(v: int):
    class C:
        def get(self):
            return x
    match v:
        case 1:
            x = 5
    return C().get()

def main():
    print(f(1))
main()
```

CPython prints `5`; this tree and `git archive master` both print `0`
(silently, exit 0).

## Why it is still open after the class-rebind fix
The by-reference class-capture pass (`module_gen._gmi_capture_nested_class_
enclosing_reads`) boxes a captured enclosing local only when the name is in
`_ef_own`:

```python
_ef_own = set(_ef_params)
_ef_own |= bound_name_set(_ef.body)
```

`_ef_own` is deliberately the exact set of names THIS function binds itself —
`_gmi_local_binding_names` over-approximates with bindings inside nested
`def`s/classes, and boxing one of those would shadow a global (that was a real
regression, fixed in `codegen: box only the enclosing frame's own class
captures`).

`bound_name_set` (via `boundnames._lbn_walk`) has no `MatchStmt` arm, so a
local bound only in a `case` body is not "own": the capture keeps the by-VALUE
cell, whose `_cap_x = x` runs at the `class` statement before `x` exists.

The same under-approximation affects at least:
- `except E as e:` — `_lbn_walk` walks handler bodies but never adds `h.name`;
- walrus targets (`x := ...`) in expressions — `_lbn_compr_targets` only
  looks at comprehension generator targets.

Each is a residual of the late-binding root cause for a name the enclosing
function really does bind.

## Next step
Make the by-reference candidate set complete without re-introducing the
shadowing bug:

1. Add the missing arms to `mojo/middle/boundnames.py::_lbn_walk`
   (`MatchStmt` → walk each `case.body` plus `_lbn_compr_targets` on the guard;
   `TryStmt` → add the `except ... as <name>` handler name; walrus in
   `_lbn_compr_targets` if the AST exposes it). This module is the one shared
   bound-name walk for GIMPLE and formal, so the fix belongs there rather than
   in a second private walk.
2. The C TYPE of a boxed name comes from
   `closures._gmi_all_stmts_nonfunc`, which also has no `MatchStmt` arm — add
   it, or a `str`/pointer local bound in a `case` body would be boxed
   `int64_t *` (wrong width; the class-rebind tests use ints, so a plain
   `match` case is not enough coverage).
3. Regression: add the program above beside
   `gimple_nested_class_ignores_nested_def_local_shadowing_global` in
   `test_gimple_runner.py`; it must print `5`. Add the `str` spelling and an
   `except ... as` spelling too, so the typing arm is covered.

## Measured
`python3 tools/memslot.py --gb 8 --label probe-match -- python3 <probe>`,
where the probe is the program above through
`test_gimple_runner.compile_mojo_to_gimple_exe`: CPython `5`, this branch `0`,
`git archive master` `0`. Full `test_gimple_runner.py` on this branch:
`571 passed, 19 failed`, the same 19 pre-existing failures as master.
