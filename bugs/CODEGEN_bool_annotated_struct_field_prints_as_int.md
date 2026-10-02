# CODEGEN: a `bool`-annotated struct field — the field is fixed, its METHOD RETURN and a `bool` PARAMETER are not

**State: PARTIAL, 2026-10-01.** This is the doc that was
`CODEGEN_bool_annotated_struct_field_prints_as_int.md`, rewritten twice over —
once by the branch that landed option B and once by the batch that rewrote it
against what the tree actually does — to say what landed and what did not.

The original doc's own diagnosis was right and its own recommendation
(candidate B, "record the bool fields and consult the map") is what shipped —
but it was right about more than it knew: the table it asked for
(`gen.struct_bool_fields`) already existed, and one more thing was broken
besides the print spellings (a whole-DICT bool mark that corrupted unrelated
int values).

**What option B covered, and what it did not**, is the whole of this document:
every PRINTING spelling of a `bool`-annotated field now says `True`/`False`
(`print`, `repr`, `str`, `f'{...}'`, `'%r' %`, a dict value, a list element,
a field read through a bound method, and a method that RETURNS one), and a
bool field still occupies an `int` slot — which is option A, `_TYPE_MAP['bool']
= '_Bool'`, untouched and still needing the full gate. Two shapes the doc's
own step-2 list names are also still wrong and are the reason it is not
CLOSED: a `bool`-annotated PARAMETER (`def show(v: bool): print(v)` → `1`)
and the remaining method-return shapes. Both want the same new thing, a
per-function record of the bool facts captured where the annotations are still
readable — written down in "What is STILL wrong, measured on this tree" below.

Not a duplicate of `bugs/CODEGEN_repr_of_a_bool_prints_1.md` (fixed
2026-09-30) — that one was a `_Bool` value whose C type was already `_Bool`
and whose repr chokepoint had no arm for it. This is the same *class* one
level out: for a struct field the bool-ness is gone before anything can look
at it, so no chokepoint can recover it.

## What I ran and what I saw

The original doc's smoke program, plus its step-2/step-3 matrix, on this tree
before the change (compiled path, CPython alongside):

| | CPython | compiled, before |
|---|---|---|
| `print(b.flag)` | `True` | `1` |
| `print(repr(b.flag))` / `str` / `'%r' %` / `f'{x}'` / `f'{x!r}'` | `True` | `1` |
| `'%d' % (b.flag,)` | `1` | `1` — already right |
| `print(b.n)` (an `int` field) | `5` | `5` — right |
| `print({'k': b.flag})` | `{'k': True}` | `{'k': 1}` |
| `print([b.flag])` | `[True]` | `[1]` |
| `print({'flag': b.flag, 'n': b.n})` | `{'flag': True, 'n': 5}` | `{'flag': 1, 'n': 5}` |
| `print(b.get())` (a method returning the field) | `True` | `1` |

## What landed

1. **`is_python_bool_expr` learned the field** (`mojo/middle/exprtypes.py`).
   It is the ONE predicate every bool-printing consumer already calls
   (`_gen_print`, `_repr_value`, `_stringify_value`, the dict store, the list
   literal), and it gained a `MemberExpr` arm reading `gen.struct_bool_fields`.
   That table was **already there** — `gimple_codegen.py:1653` declares it and
   `module_gen.py`'s struct-field scan populates it for a class-body
   `flag: bool` — but only the struct's generated `_mojo_repr_<Sn>` consulted
   it. The canonical Python shape (`self.flag = flag` in `__init__`, the
   annotation on the PARAMETER) did not reach it at all: that field's type is
   inferred by `_gmi_collect_self_assigns`, a different pass. So
   `_gmi_collect_self_assigns` now takes the set of parameters whose declared
   annotation is `bool` and registers the field it lands on. Both spellings of
   the annotation now register, and both spellings are in
   `test_gimple_runner.py`'s `gimple_bool_annotated_struct_field`.

   The receiver's struct is resolved by a new `_receiver_ctypes` helper rather
   than by `gen._quick_type` alone: `_quick_type` reads `var_types`, which has
   no entry for a MODULE-LEVEL global, so `b.flag` at module scope and the
   identical `b.flag` inside a `def` disagreed until that was fixed. The
   answer is a LIST of candidate types (local, module global,
   struct-identity-recovered parameter, post-store actual type) and a field
   lookup that accepts any of them — a single winner would have been a guess
   about the wrong struct.

2. **The dict bool tag moved from the whole dict to the slot.** This was not in
   the original doc, and it is the more serious of the two: the bool mark was
   `mojo_mark_dict_bool_values`/`mojo_is_bool_dict`, a `_PtrReg` set keyed by
   the DICT's address, and `_mojo_repr_dict` used it to choose the formatter for
   **every** value. So one bool value in a dict made all of them print
   True/False:

       print({'ok': True, 'count': 3})   # CPython {'ok': True, 'count': 3}
                                          # compiled {'ok': True, 'count': True}

   Reachable with no struct at all (`{'x': True, 'y': 5}`), so pre-existing
   and independent. `_DictSlot.kind` already existed for exactly this job
   (`0` int, `1` double, `2` char *) and already survives `_dict_grow`,
   `mojo_dict_update`, `mojo_dict_copy` and `_dict_remove_slot` because they
   all move the slot whole; the fix is the fourth value, `3` = Python bool, set
   by a new `mojo_dict_set_bool` / `mojo_dict_set_bytes_bool`, and the five
   copies of "mark the dict then `mojo_dict_set_int`" are now ONE function
   (`emit_infra.py`'s `emit_dict_int_value_store`). The whole-dict registry and
   both of its entry points are deleted; nothing else read them.

3. **A list/tuple literal of nothing but bools infers `_Bool`**
   (`_infer_list_elem_type`), which routes it to `mojo_repr_list_bools` — the
   helper that already existed for `[True, False]`. The estimate is made HERE
   and not by teaching `_quick_type` that a bool field is a `_Bool`, because
   `_quick_type` also writes the enclosing function's PROTOTYPE and every local
   declaration: claiming `_Bool` for a field the lowering really loads as `int`
   writes a `_Bool x = <int>` store into a `__GIMPLE` body, which gcc rejects
   outright. Only the ALL-bool literal answers `_Bool`; a mixed one joins
   exactly as before, because `TypeLattice.join` widens `_Bool` to `int` and a
   genuine 0/1 int must keep printing as one.

## What is STILL wrong, measured on this tree

```python
class Box:
    def __init__(self, flag: bool, n: int):
        self.flag = flag
        self.n = n
    def get(self):
        return self.flag
    def get2(self) -> bool:
        return self.flag
    def report(self, other: bool):
        print(other)              # CPython True   -> compiled 1

def show(v: bool, n: int):
    print(v)                      # CPython True   -> compiled 1
    print({'k': v})               # CPython {'k': True} -> {'k': 1}

b = Box(True, 5)
print(b.get())                    # CPython True   -> compiled 1
print(repr(b.get()))              # CPython True   -> compiled 1
print({'g': b.get()})             # CPython {'g': True} -> {'g': 1}
print(b.get2())                   # CPython True   -> compiled 1
b.report(True)                    # CPython True   -> compiled 1
show(True, 5)                     # CPython True   -> compiled 1
```

Two shapes, one cause: `_TYPE_MAP` maps `'bool'` to `'int'`, so a
`bool`-annotated value's lowered C type is an ordinary integer, and
`is_python_bool_expr` has no evidence for either shape.

- **A METHOD RETURN** (`get`, `get2`) needs "this call yields a Python bool"
  keyed on the callee. There is no table of return ANNOTATIONS anywhere in the
  tree — `func_return_types` and `func_param_types` hold resolved C types, and
  `'bool'` and `'int'` are `'int'` and `'int64_t'` respectively, which is why
  the annotation has to be captured before it is resolved.
- **A `bool` PARAMETER** (`v: bool`, `other: bool`) needs "this name is a bool"
  for the enclosing function. Note `'bool'` resolves to `'int'` while `'int'`
  resolves to `'int64_t'`, so a bool param IS distinguishable from an int param
  in `func_param_types` — but NOT from a small integer literal's own lowering
  (a small `IntLiteral` also lowers to plain C `int`, see
  `_local_literal_ctype`'s docstring), so keying off `'int'` would be a guess
  that turns `x = 5; print(x)` into `True`.

Both want the same new thing: a per-function record of the bool facts, captured
where the annotations are still readable — `_signature_ctypes`
(`mojo/middle/funcs_shared.py`) is the one chokepoint every free function and
struct method's params go through, and it already receives the FunctionDef.
`gen.current_func_name` is set while a body is lowered, so the param half is
`gen._bool_param_names.get(gen.current_func_name)`; the return half needs the
key the call site uses (`_sms_key(struct, method)` for a method,
`func_param_types`' bare name for a free function) and a `CallExpr` arm in
`is_python_bool_expr` that resolves `node.func`'s receiver the way
`_receiver_ctypes` already does.

Note the trap the original doc recorded and that still holds: `b.get() == True`
is CORRECT today, because a comparison makes its own `_Bool`. A test that only
checks the equality passes while every print spelling is wrong.

## Suite-bucket note

None. `test_gimple_runner.py` (`gimplerunner`, in both `check` and `gate`) is
where these belong, with CPython's exact text as the expectation;
`gimple_bool_annotated_struct_field` and `gimple_dict_of_bool_values` are
there.

## Evidence

- `python3 .tmp/diff.py` style harness (gimple_codegen → `gcc -fgimple` against
  `runtime/fire_runtime.c`, run beside CPython) over the full matrix above,
  before and after.
- Both regression cases were measured FAILING with the source reverted and the
  test kept: `gimple_bool_annotated_struct_field` produced
  `1 0 1 1 ... [1, None] {'flag': 1, 'n': 5}`, and `gimple_dict_of_bool_values`
  produced `{'a': True, 'n': True}` / `{'ok': True, 'count': True}`.
- `python3 test_ptr_registry.py`: 22 passed, 0 failed (the runtime change).
