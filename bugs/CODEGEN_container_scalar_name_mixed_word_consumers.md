# CODEGEN: a name rebound between a container and a scalar is a word, but its consumers read a stale static kind

Found 2026-11-12 while closing the mixed-kind-name box work. The box covers
SCALAR-in-a-name (`x = 1.5; x = "s"`) and a container/scalar PARAMETER. A name
that is a container at one store and a scalar at another compiles to an
`int64_t` word already (`resolve_shared._infer_local_var_types_core` answers
`int64_t` for a `_multi_kind_locals` name), but its READS do not dispatch on
the runtime kind: they trust a stale/pinned static `_actual_types` entry. The
result is a SIGSEGV or garbage at exit 0 for a program CPython runs.

## What I ran

```python
import sys
sys.path.insert(0, '.')
from test_gimple_runner import compile_mojo_to_gimple_exe
src = 'def main():\n    x = [1, 2]\n    print(x)\n    x = 3\n    print(x)\nmain()\n'
exe = compile_mojo_to_gimple_exe(src)
```

Actual (each case run and compared with CPython on the same text):

| program | compiled | CPython |
|---|---|---|
| `x = [1, 2]; print(x); x = 3; print(x)` | `[1, 2]\n` then SIGSEGV | `[1, 2]\n3\n`, rc 0 |
| `x = "s"; print(x); x = [1, 2]; print(x)` | `s\n` then raw heap bytes, rc 0 | `s\n[1, 2]\n` |
| `x = [1, 2]; print(len(x)); x = 5; print(len(x))` | `2\n` then SIGSEGV | `2\n` then `TypeError`, rc 1 |
| `x = 5; print(len(x)); x = [1, 2]; print(len(x))` | SIGSEGV on `len(5)` | `TypeError`, rc 1 |
| `x = [1, 2]; print(str(x)); x = 5; print(str(x))` | `[1, 2]\n` then SIGSEGV | `[1, 2]\n5\n` |
| `x = []; print(bool(x)); x = 0; print(bool(x))` | `1\n0\n` | `False\nFalse\n` |
| `x = [1]; print(x); x = {"a": 1}; print(x)` | OK | OK |
| `x = 3; print(x); x = [1, 2]; print(x)` | OK (first store is the scalar) | OK |
| `x = [1, 2]; print(x == [1, 2]); x = 5; print(x == 5)` | OK | OK |

So the representation is close: the value IS a valid word (a list pointer,
an int, or a scalar pointer), and list-then-dict works. What breaks is each
consumer that resolves the name's C type once and reads that kind.

## Why

- `emit_infra.mixed_container_locals` records only container-vs-container
  disagreement (`MojoList *` / `MojoDict *` / `MojoSet *`).
- `emit_infra.mixed_scalar_locals` records only scalar-vs-scalar disagreement
  (`int` / `double` / `str`).
- A container + a scalar name is in NEITHER set. The store site therefore does
  not take the `_mixed` `int64_t` declaration arm for its own reasons; it gets
  `int64_t` from the pre-pass's `_multi_kind_locals` verdict instead (that part
  is right), but a float or str store into it is not boxed (the
  `_scalar_mixed` arm is false), so kind information is lost on the way in as
  well as on the way out.
- On the read side `_gen_print`'s dispatch (and `_lower_builtin_len`, `bool`,
  f-strings) consults `_get_actual_type` / `_actual_types`, which is a
  compile-time record of a value seen earlier in the function, not a
  flow-sensitive runtime kind. After `x = [1, 2]`, a later `print(x)` still
  reads it as `MojoList *` even when the last executed store was `x = 3`.

The runtime helpers for the right answer already exist and are used for the
OTHER mixed shapes: `_repr_boxed_container` (dict → set → list → str → int,
one word), `_len_of_boxed` (registered containers, bytes, str, then
`mojo_list_len`), and the box-aware arms in `mojo_len_word`. This bug is
routing those consumers to them for a "container/scalar name", plus boxing
the scalar stores so a float does not become its raw bit pattern and a str is
recognizable.

## Exact next step

1. Add `emit_infra.mixed_value_locals(gen)`: names in the current function
   body with at least one CONTAINER binding (`_CONTAINER_KIND_TYPES`) and at
   least one non-container binding (any scalar or unknown pointer). Cache it
   per function like `mixed_container_locals`, and reset it in `_reset_func`.
2. Treat that set as an `_int64_t` name at both declaration and store:
   `emit_stmts._gen_stmt_AssignStmt`'s `_mixed` arm includes it, and the
   `_scalar_mixed` store box arm includes it (float → `mojo_box_from_double`,
   str → `mojo_box_from_str`, bool → `mojo_box_from_bool`; int and container
   stores stay bare words).
3. Route consumers for a name in the set through the existing runtime
   dispatchers: `_gen_print` / `str` / `repr` → `_repr_boxed_container`,
   `len` → `_len_of_boxed` (and make the no-length kinds raise `TypeError`,
   as CPython does, rather than falling through to `mojo_list_len`),
   `bool`/truthiness → the `_dyn_word_locals` runtime predicate, iteration and
   subscript → the existing dynamic container dispatch.
4. Pin the cases above (the first six rows are the ones that fail) in
   `test_mixed_kind_name_representation.py`, each against CPython on the same
   text.

Do NOT widen `mixed_scalar_locals` alone: a name that only holds two scalars
must keep the existing behaviour, and a container store must not be boxed
(there is no box constructor for it, and the pointer word is already right).
