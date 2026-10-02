# CODEGEN: a `bool`-annotated struct FIELD prints as 1/0 in every spelling

**State: PARTIALLY FIXED (2026-10-01). Option B landed: every printing
spelling of a `bool`-annotated field now says `True`/`False`. Option A — the
real fix — is untouched and still needs the full gate; what is left of it is
written down at the bottom.**

Not a duplicate of `bugs/CODEGEN_repr_of_a_bool_prints_1.md` (fixed
2026-09-30) — that one was a `_Bool` value whose C type was already `_Bool`
and whose repr chokepoint had no arm for it. This is the same *class* one level
out: for a struct field the bool-ness is gone before anything can look at it, so
no chokepoint can recover it.

## What was fixed (option B, 2026-10-01)

**The table already existed.** `struct_bool_fields` is populated from a
`bool`-annotated class-body `VarDecl`, and the struct's own generated
`__repr__` has consulted it all along — which is exactly how this survived:
`print(b)` said `flag=True` while `print(b.flag)` said `1`. But for the doc's
own shape, `def __init__(self, flag: bool): self.flag = flag`, the annotation
is on the *parameter*, so the table was empty: nothing registered the field,
because `_gmi_collect_self_assigns` keeps only the field's resolved ctype
(`_resolve_type('bool')` → `int`) and the bool-ness has nowhere to go.

Three pieces, in the order they had to be written:

1. **`_gmi_collect_self_assigns` records it** (`mojo/middle/module_shared.py`).
   That walk is the one place that knows BOTH that a parameter is annotated
   `bool` and which `self.<field>` it feeds, so the annotation is spent there
   rather than recovered later. The set of bool-annotated parameter names for
   the method being scanned rides on `gen._gmi_bool_params` (declared in
   `GimpleGen.__init__` for the same self-hosting reason as `_bool_valued`
   right above it: a field created lazily behind `hasattr` reads as
   existing-but-NULL self-hosted). Re-walking the body in `module_gen.py` to
   recover the parameter→field link instead would be exactly the quadratic
   rescan `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
   is about.
2. **`is_python_bool_expr` gained a `MemberExpr` arm and a `CallExpr` arm**
   (`mojo/middle/exprtypes.py`), resolving the receiver's struct — `self`
   inside the struct's own method, otherwise the receiver's own type. This is
   the ONE shared predicate every bool consumer already uses (`_gen_print`,
   `_repr_value`, `_stringify_value`, the dict store), so one arm reaches all
   of them and none of them can disagree about the same value.
3. **A list literal of bool fields.** `_lower_list_literal` asks the same
   predicate for its element type, because a list's generic repr both formats a
   slot as `"1"` AND reads a `False` (0) slot as the `None` sentinel: `[b.flag,
   c.flag]` printed `[1, None]`, not `[1, 0]`. Only the repr route changes —
   `list_suffix('_Bool')` is `'int'`, so the append suffix, the slot layout and
   every per-slot reader are unchanged. This is the list-side twin of
   `mojo_mark_dict_bool_values`.

Measured on the doc's own program, and on a second one covering the shapes the
doc's step 2 lists:

| | CPython | before | after |
|---|---|---|---|
| `print(b.flag)` | `True` | `1` | `True` |
| `print(repr(b.flag))` | `True` | `1` | `True` |
| `print('%r' % (b.flag,))` | `True` | `1` | `True` |
| `print(f'{b.flag}')` | `True` | `1` | `True` |
| `print(str(b.flag))` | `True` | `1` | `True` |
| `print({'k': b.flag})` | `{'k': True}` | `{'k': 1}` | `{'k': True}` |
| `print(b.get())` (method return) | `True` | `1` | `True` |
| `print(repr(b.get()))` | `True` | `1` | `True` |
| `[b.flag]` | `[True]` | `[1]` | `[True]` |
| `[b.flag, c.flag]` | `[True, False]` | `[1, None]` | `[True, False]` |
| `print(b.flag)` where `b` is a `self` parameter | `False` | `0` | `False` |
| `print(b.n)` (an `int` field) | `5` | `5` | `5` — unchanged |
| `b.flag + 0` | `1` | `1` | `1` — unchanged |
| `b.flag == True` | `True` | `True` | `True` — unchanged |

Regressions: `gimple_bool_annotated_struct_field` and
`gimple_bool_field_in_a_list_and_through_a_receiver` in
`test_gimple_runner.py`. The first pins every printing spelling rather than the
easiest one to look at, and carries the `int` field and the two arithmetic
spellings as the controls that a fix did not turn a bool field into something
else.

## What is NOT fixed, and why

**A bool field still occupies an `int` slot.** Every printing chokepoint now
answers, and anything that depends on the *width* or on `isinstance` still
sees an integer. That is option A, and this document's own analysis of it
stands: `_TYPE_MAP['bool'] = '_Bool'` is the real fix, `__GIMPLE` requires both
operands of a binary expression to be the IDENTICAL type, so `self.count +=
self.flag` becomes `int64_t += _Bool` — a GIMPLE operand-type error. That is
exactly why none of the three fixes above touches a ctype or `_quick_type`, and
why they cannot be folded into option A later for free.

**One receiver shape is not claimed.** `struct_bool_methods` records a method
only when every `return` reads a bool field off a receiver this pass can
*name*: `self`, or a parameter annotated with a struct name. A return of
`factory().flag`, or of a field off a subscripted or computed receiver, is not
claimed — answering `True` there would be a guess, and the doc's own rule
("a program that says nothing is worse than one that says the wrong thing")
argues against it.

Regressions verified: `test_gimple.py` 348 pass / 1 fail and
`test_runtime_diff.py` 39 pass / 0 fail, both byte-identical to the pre-change
baseline; `test_gimple_runner.py` green apart from its two pre-existing
failures.

## Original report follows

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
