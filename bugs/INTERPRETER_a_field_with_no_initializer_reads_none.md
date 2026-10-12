# INTERPRETER_a_field_with_no_initializer_reads_none: a `var x: Int` field of a fresh instance is `None`, not 0

**Status: OPEN, not fixed. Found and measured 2026-10-03 while landing the
formal module-frame-slot work (`work/formal15-module-slot-lifetime`); it is in
`myinterpreter.py`, which that work does not touch, so it was filed rather than
fixed.**

Found by a differential test that compared an image against `fire.py run` and
disagreed: `test_formal_globals.py`'s
`frame_global_read_and_mutated_from_functions` expects `1 0 41 41 0` and the
interpreter produced `1 None 41 41 None`. The `41` and the second `41` are
right — they are WRITES followed by reads — and every `None` is a READ of a
field nobody ever assigned.

## What it is

A `struct` that declares a field with no initializer:

```mojo
struct Pair:
    var x: Int
    var y: Int

def main(n):
    var p = Pair()
    print(p.x)
    print(p.y)
    return 0

main(0)
```

`fire.py run` prints `None` twice. CPython is not the question — the language is:
Mojo's `struct` fields are zero-initialized, `doc/ABI.md` says so for the formal
backend and both images print `0`. So this is the interpreter disagreeing with
the language on the most ordinary declaration in it.

**It is not about module level, and not about frames.** Measured:

| program | `fire.py run` | note |
|---|---|---|
| `var p = Pair()` in a function, then `p.x` | `None` | a plain local |
| `_g = Pair()` at module level, then `_g.x` | `None` | same bug, reached through a global |
| `Pair()` with an `__init__` assigning both fields, then `_g.x` | `4` | correct |
| `_g.x = 5; print(_g.x)` with no `__init__` | `5` | a WRITE works; only the READ of an unassigned field is `None` |

The last row is what makes it a bounded bug rather than a broken feature: the
attribute exists, it holds `None`, and a store into it replaces the `None`. So
nothing crashes and nothing is refused — the program just prints `None` for a
field the language says is `0`, which is the failure mode this backend's whole
refusal discipline exists to avoid and the one place it cannot help.

## Where it is

`myinterpreter.py`'s `MojoClass.__call__`, the instance-construction branch:

```python
value = self.interpreter.eval_expr(f.value) if f.value is not None else None
value = self.interpreter._coerce_to_declared_type(value, getattr(f, 'type_ann', None))
setattr(instance, f.name, value)
```

`f.value is None` is exactly the "declared, no initializer" case, and it stores
`None`. `_coerce_to_declared_type` is the one reader that could turn that into
the declared type's zero, and its three arms are all about converting a value
that EXISTS — a float into an `Int`, an int into a `Float`, an int into a `Bool`
— so `None` passes through untouched.

## The next step, exactly

One clause in that branch, using the vocabulary `MojoClass` already owns:
`_ARRAY_ELEM_DEFAULTS` (`{'Bool': False, 'String': '', 'Float16': 0.0,
'Float32': 0.0, 'Float64': 0.0}`) is already the answer for a fixed-size ARRAY
field, reached through `_array_field_default` — so the scalar case is the same
table with an `Int` entry, asked of `type_ann` when `f.value is None`. That is
the whole fix, and putting it in `_coerce_to_declared_type` rather than in the
branch makes the two share it: a coercion that maps `None` to the declared
type's zero is the same statement whether the value came from a missing
initializer or from an expression that folded to nothing.

Two things to check while doing it, because they are what makes this a real
decision rather than a lookup:

* **`List` / `Dict` fields must NOT get `0`.** A container field with no
  initializer is an empty container in Mojo, not a zero, and `0` there would be
  the same plausible-wrong-answer class this bug already is — one level down.
  So the table's scope is the SCALARS, exactly as `_ARRAY_ELEM_DEFAULTS` is, and
  an annotation outside it must keep whatever it gets today rather than being
  guessed at.
* **An annotation this interpreter cannot map must stay untouched.** The same
  conservative rule `formal/model.py`'s `declared_type_kind` follows: claim
  nothing rather than invent a zero for a type whose zero is not known.

## Why it was not fixed here

`myinterpreter.py` is the reference SEMANTICS every `test_formal_*.py` case
compares its images against, and this is a change to it rather than to the
formal backend. Changing the interpreter's construction semantics in the same
commit as a formal-backend change would make the comparison that commit is
verified by stop being independent — the exact tautology
`test_formal_globals.py`'s own header explains. It is one clause in one branch,
and it belongs in a commit whose only subject is the interpreter.