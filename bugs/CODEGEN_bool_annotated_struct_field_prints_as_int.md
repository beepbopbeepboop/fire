# CODEGEN: a `bool`-annotated struct FIELD prints as 1/0 in every spelling

**State: OPEN, found 2026-09-30 while smoke-testing the
`construct:compiled-silent-wrong-values` batch, mechanism located, not
fixed.** Not a duplicate of
`bugs/CODEGEN_repr_of_a_bool_prints_1.md` (fixed 2026-09-30) — that one was
a `_Bool` value whose C type was already `_Bool` and whose repr chokepoint had
no arm for it. This is the same *class* one level out: for a struct field the
bool-ness is gone before anything can look at it, so no chokepoint can recover
it.

## What I ran and what I saw

```python
class Box:
    def __init__(self, flag: bool, n: int):
        self.flag = flag
        self.n = n

def main():
    b = Box(True, 5)
    print(b.flag)
    print(repr(b.flag))
    print(b.n)
    c = Box(False, 5)
    print(c.flag)
    print('%r' % (b.flag,))
    print(f'{b.flag}')
    d = {'k': b.flag}
    print(d)
main()
```

| | CPython | compiled |
|---|---|---|
| `print(b.flag)` | `True` | `1` |
| `print(repr(b.flag))` | `True` | `1` |
| `print(b.n)` (an `int` field) | `5` | `5` — **correct** |
| `print(c.flag)` | `False` | `0` |
| `print('%r' % (b.flag,))` | `True` | `1` |
| `print(f'{b.flag}')` | `True` | `1` |
| `print({'k': b.flag})` | `{'k': True}` | `{'k': 1}` |

Every spelling is wrong and none says anything: exit 0, a plausible number.
The `int` field in the same struct is right, so it is specific to `bool`.

## Mechanism

`_TYPE_MAP` maps `'bool': 'int'`, so `_resolve_type('bool')` returns `'int'`
(verified by instrumenting `_resolve_type` on this exact source: six calls,
all `'bool' -> 'int'`). Everything downstream therefore sees an ordinary
integer:

```c
typedef struct Box { int64_t __mojo_type_id; int flag; int64_t n; } Box;
void __GIMPLE Box___init__ (Box * self, int flag, int64_t n) { self->flag = flag; }
...
_t4 = b->flag;        /* lowered type `int` */
mojo_print (<sprintf %d of _t4>);
```

A `BoolLiteral` also lowers to `int` on purpose — see
`_lower_BoolLiteral`'s own comment, quoted in
`mojo/backend_gimple/emit_calls.py`'s `str()` lowering: "`_lower_BoolLiteral`
returns ctype 'int' (not '_Bool')", and other sites depend on it. So a plain
`print(True)` is handled by `_gen_print`'s `_Bool`-or-`_bool_valued` arms, and
a `bool` FIELD has neither: it is not `_Bool`, and `_bool_valued` (the set
`_record_bool_valued` fills, keyed by NAME, for `b = True`) is not consulted
for a `MemberExpr` at all — `is_python_bool_expr` checks
`isinstance(node, IdentExpr) and node.name in gen._bool_valued`, which a field
access can never satisfy.

So the information is destroyed at `_resolve_type` and there is no chokepoint
left that could recover it.

## Two candidate fixes, and the trade-off between them

**A. `_TYPE_MAP['bool'] = '_Bool'`.** The real fix: the annotation says bool,
so the C type should say bool, and every existing `_Bool` arm
(`_gen_print`, `_repr_value`, `_stringify_value`, `mojo_bool_to_str`) starts
answering for free — the field read lowers to `_Bool`, the struct field is
declared `_Bool`, and the dict store's `is_python_bool_expr` fires on
`_quick_type(MemberExpr) == '_Bool'`.

The cost is GIMPLE's typing rules. `__GIMPLE` requires both operands of a
binary expression to be the IDENTICAL type, so every `bool`-annotated value
reaches arithmetic and comparison as `_Bool` where it used to be `int`:
`n: bool; n + 1`, `n == True`, `f(n)` where `f` declares `int64_t`, a
`bool` FIELD read passed to something expecting `int`. Each needs a coercion
emitted at the right place, and the same widening is what the project's
existing boxing helpers (`_to_int64`, `mojo_box_int`) exist for. This is a
real change to a shared type table with a wide blast radius — it needs the
full gate and its own session, not a patch.

**B. Record the bool fields and consult the map.** The codebase already
carries per-struct side tables for exactly this kind of thing —
`struct_field_types`, `_field_elem_types`, `_field_dict_val_types`,
`_struct_field_kinds` — so a `_field_is_bool: dict[str, set]` populated where
the StructDef's annotations are still readable, and consulted by the four
consumers that already have a `_Bool` arm (`_gen_print`, `_repr_value`,
`_stringify_value`, the dict store) is the conservative shape and touches no
type table.

Its honest limit: it is a *print/str/repr* fix only. A bool field still
occupies an `int` slot, so a program that relies on the width or on
`isinstance` still sees an int. A is the fix; B is the one that can land
without a type-table decision.

## Also found alongside it, and part of the same smoke test

A `bool`-annotated struct field is not the only place a value's real type is
lost before a chokepoint sees it. The same smoke program also showed
`def show(t): print(t)` called with `show(1.5)` printing `1` and `show("s")`
printing a pointer decimal — a genuine **float** passed to a parameter whose
slot is `int64_t`, truncated at the call site. That one is already documented,
with both halves of its fix located, in
`bugs/CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md` ("Also
unfixed and worth knowing"), and is not repeated here.

## Exact next step

1. Decide A or B. B is the smaller, safer landing and is what I would do first:
   `_field_is_bool` populated from the StructDef's field annotations at the
   point `struct_field_types` is built (the annotation is still in hand
   there), consulted by the four `_Bool` consumers.
2. Under either, cover: `print(f)`, `repr(f)`, `'%r' % (f,)`, `f'{f}'`,
   `str(f)`, `{'k': f}`, `[f]`, a list-of-bools-field, and a bool field read
   through a bound method (`b.flag` where `b` is a `self` parameter).
3. Then measure the same matrix for a **method return**: `def flag(self):
   return self.flag` with a `bool` field. That is the shape most real code
   uses. **Measured 2026-09-30, and it is ALSO broken**, so it belongs in the
   same test rather than being assumed to follow:

   ```python
   class Box:
       def __init__(self, flag: bool):
           self.flag = flag
       def get(self):
           return self.flag

   b = Box(True)
   print(b.get())          # CPython True   -> compiled 1
   print(repr(b.get()))    # CPython True   -> compiled 1
   print(b.get() == True)  # CPython True   -> compiled True
   ```

   The method's return type is inferred from its body, and the body is
   `return self.flag` — an `int` field — so the inference lands on `int64_t`
   exactly as the direct read does. Note the third line: `b.get() == True` is
   CORRECT, because the comparison itself produces a `_Bool`. So a test that
   only checks the equality would pass while the two print spellings are
   wrong, which is the same trap `CODEGEN_repr_of_a_bool_prints_1.md`
   documents for `print` vs `repr`.

## Suite-bucket note

None. `test_gimple_runner.py` (`gimplerunner`, in both `check` and `gate`) is
where these belong, with CPython's exact text as the expectation.
