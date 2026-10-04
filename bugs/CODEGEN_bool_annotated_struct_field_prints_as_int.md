# CODEGEN: a `bool`-annotated struct field and parameter — the print spellings, the method return and the parameter are all fixed; `isinstance`/`type` are not

**State: PARTIAL, 2026-10-02.** Everything this document opened for has landed.
One narrow shape remains, and it is the one shape the original author of this
document predicted would need a separate session: option A,
`_TYPE_MAP['bool'] = '_Bool'`.

## What landed, and in what order

The three printing shapes — a `bool`-annotated FIELD, a method that RETURNS
one, and a `bool`-annotated PARAMETER — are all correct now, and they all go
through the ONE shared predicate, `mojo/middle/exprtypes.py::is_python_bool_expr`,
so no consumer can disagree with another about the same value. Measured with
CPython alongside, on this tree:

| shape | before | now |
|---|---|---|
| `print(b.flag)` / `repr` / `str` / `'%r' %` / `f'{...}'` at MODULE scope | `1` | `True` |
| the same, inside a `def` | `True` | `True` |
| `{'k': b.flag}` / `[b.flag]` / a mixed `{'flag': ..., 'n': ...}` | `{'k': 1}` | `{'k': True}` |
| `b.get()` / `repr(b.get())` / `{'g': b.get()}` (unannotated return) | `1` | `True` |
| `b.get2()` (`-> bool`) | `1` | `True` |
| `print(v)` where `def show(v: bool)` | `1` | `True` |
| `{'k': v}` where `def show(v: bool)` | `{'k': 1}` | `{'k': True}` |
| `print(other)` inside `def report(self, other: bool)` | `1` | `True` |
| `v + 1` / `int(v)` / `str(v) + 'x'` / `not v` / `if v:` on a bool param | already right | still right |

Regressions, all in `test_gimple_runner.py`: `gimple_bool_annotated_struct_field`
(both spellings), `gimple_bool_field_in_a_list_and_through_a_receiver`,
`gimple_dict_of_bool_values`, and the new `gimple_bool_annotated_parameter`.

### The three mechanisms, because they are three different gaps

1. **A FIELD.** `struct_bool_fields` already recorded which fields carry a
   `bool` annotation, and only the struct's own generated `_mojo_repr_<Sn>`
   consulted it — so `print(b)` said `flag=True` while `print(b.flag)` said
   `1`. `is_python_bool_expr` gained a `MemberExpr` arm, and
   `_gmi_collect_self_assigns` (which is the pass that infers that field's
   type at all, for the canonical `self.flag = flag` spelling that puts the
   annotation on the `__init__` PARAMETER) registers the field it lands on.
2. **The receiver.** `_is_python_bool_field` and `_is_python_bool_method`
   resolve the receiver through `_receiver_ctypes`, which is a LIST of every
   type this backend has RECORDED for the name — not `gen._quick_type`, which
   reads `var_types` and has no entry for a MODULE-LEVEL global. That is why
   `b.flag` at module scope and the identical `b.flag` inside a `def` used to
   disagree, and why a list is the honest shape: a single winner would be a
   guess about the wrong struct.
3. **A PARAMETER.** `'bool'` resolves to `'int'` and `'int'` to `'int64_t'`,
   so a bool param IS distinguishable from an int param in `func_param_types`
   — but NOT from a small integer LITERAL's own lowering, which is also a
   plain C `int` (`_local_literal_ctype`'s docstring). Keying off the type
   would have turned `x = 5; print(x)` into `True`. So the annotation is
   captured where it is still readable: `record_bool_params`, called from the
   two places in `emit_funcs.py` that set `gen.current_func_name` with the
   `FunctionDef` in hand (a free function's name, and a method's
   `<Struct>_<method><overload>`), keyed by `current_func_name` verbatim, and
   read back per function by `bool_param_in_scope`.

`_signature_ctypes` looks like the chokepoint for (3) and is NOT: on the
body-lowering path it is only reached for a varargs signature. That is why the
recorder is called where `current_func_name` is set.

### The dict half — a merge dropped its call sites

A whole-DICT bool registry (`mojo_mark_dict_bool_values` / `mojo_is_bool_dict`)
was replaced by a per-SLOT tag (`_DictSlot.kind == 3`, set by
`mojo_dict_set_bool`), because one bool value in a dict made every OTHER value
print as True/False too. `mojo_mark_dict_bool_values` was removed from the
runtime, and the five `d[k] = v` / dict-literal / dict-comprehension spellings
that used to call it were meant to be consolidated into the ONE function
`emit_infra.py::emit_dict_int_value_store`. The consolidation did not survive
the merge into this tree: the helper was present and DEAD, every call site still
called the deleted runtime function, and `GimpleGen._emit_dict_int_value_store`
(the one-line delegate, and the reason `test_gimple_runner.py` reported
`'GimpleGen' object has no attribute '_emit_dict_int_value_store'` on four
bytes-dict tests) was missing. All of it is back, and `emit_dict_int_value_store`
has exactly the five callers its own docstring names.

The merge damage was measured rather than inferred: the same missing delegate
and the same four test failures were filed independently by another worker as
their own bug doc, and this change fixes that doc's subject (its doc is deleted
with this commit). `test_suite.py` now checks the whole family — every
`gen.X(...)` the backend calls must be a method `GimpleGen` has.

## What is STILL wrong

`isinstance` and `type` on a `bool`:

```python
def show(v: bool):
    print(isinstance(v, bool))
    print(type(v))
def showi(v: int):
    print(isinstance(v, bool))
    print(type(v))
show(True)
showi(1)
```

| | CPython | compiled |
|---|---|---|
| `isinstance(True, bool)` | `True` | `False` |
| `type(True)` | `<class 'bool'>` | `0` |
| `isinstance(1, bool)` | `False` | `False` |

Both are option A: the lowered C type of a `bool` is `int`, so
`mojo_isinstance(v, 'bool')` has nothing to match and the `type()` read has no
tag to report. The fix is one line — `_TYPE_MAP['bool'] = '_Bool'` — and it is
deliberately NOT applied here, for the reason this document's original author
recorded and still holds:

* `_quick_type` writes the enclosing function's PROTOTYPE and every local
  DECLARATION. Claiming `_Bool` for a value the lowering really loads as `int`
  writes a `_Bool x = <int>` store into a `__GIMPLE` body, which gcc rejects
  outright (`invalid conversion in gimple assignment`), not merely warns about.
* `_Bool` then propagates into struct field layout, comparison mnemonics and
  the formal arm64 backend, all of which read `_TYPE_MAP` — so it is a
  whole-program change.

Applied, it would also make most of the mechanism above redundant (a `_Bool`
param needs no side table), which is the strongest argument for doing it as
its own change rather than behind the three fixes that are already in.

**Done when** `isinstance(True, bool)` is `True`, `type(True)` is
`<class 'bool'>`, and `_TYPE_MAP['bool'] = '_Bool'` survives `make gate` — plus
`stdlib-syntax`'s `U` count not increasing and a `stdlib-dylib` `skip` count not
increasing, both per CLAUDE.md's rule about type-resolution changes.
