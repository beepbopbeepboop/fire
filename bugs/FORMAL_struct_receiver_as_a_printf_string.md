# FORMAL_struct_receiver_as_a_printf_string: `%s` of a value that is not text

**Status: the two-field case was already refused; the `INT_KIND` case is FIXED
and measured before and after on both architectures; ONE case remains open and
it needs a table another worker has claimed.** This file was filed on
2026-09-29 from a SIGSEGV; what follows is what that SIGSEGV was, what is now a
build error, and the one shape of it that still faults.

## What was measured, then and now

Every row is a real build and a real run on this tree, both architectures.

| program | at the filing | now |
|---|---|---|
| `c = C(1, 2); printf("%s", c)` — a TWO-field class | SIGSEGV 139 | **refused** before this file was read: `frame_receiver_escape_refusal`'s `FRAME_C_VALUE_CALLS` branch |
| `c = C(1, 2); print(c)` | SIGSEGV 139 | refused, `FRAME_VARIADIC_BUILTIN_CALLS` |
| `printf("%s", str(c))` on the same | — | refused by the above; `str()` of a one-field receiver is the *value* (see below) |
| `var a = 5; printf("[%s]", a)` | SIGSEGV 139 | **refused** — `model.printf_text_conversion_refusal` |
| `var a = 2 + 4; printf("[%s]", a)` | SIGSEGV 139 | **refused** — same, and the shape a real program writes |
| `printf("[%s]", one_field_int_struct)` | **SIGSEGV 139** | **STILL SIGSEGV 139** — see the open item |

The two-field rows were already fixed when this session read the file; the
filing's `printf("%s\n", c)` reproducer does not reproduce on this tree. The
`%s`-of-a-plain-integer rows are new measurements of the same class and are the
family's real remaining content: `%s` is the one printf conversion that
**dereferences** its argument — every other one renders the word it is handed —
so an integer is not a wrong rendering of it, it is a walk off the end of
whatever the number points into.

## What landed

`formal/model.py`: `PRINTF_TEXT_CONVERSIONS_CALLEES`,
`printf_conversion_specifiers` (the format-string scan) and
`printf_text_conversion_refusal` (the decision and the message). Both emitters
ask it from `_emit_call`, where the format string and the varargs are last in
hand together. `print()` needed nothing: it builds its OWN format from each
operand's kind (`_print_call`) and already refused the case it cannot tell,
which is why `printf` — the spelling the whole corpus uses, taking a format the
source wrote — was the only hole.

**The vararg arithmetic is the part that has to be right, and it is a real trap.**
The position of a `%s` in the OUTPUT is the position of its argument in the
varargs list, so a scanner that miscounts refuses the WRONG argument — which is
worse than not looking, because the message would name a name the program never
misused. Two things read as nothing and are not: `%%` (a literal percent, which
`print_literal` doubles precisely so the scan can tell it from a conversion) and
a `*` width or precision (which consumes an argument). `printf_conversion_specifiers`
counts `*` as its own conversion for that reason, and
`printf_star_width_and_literal_percent_keep_the_varargs_aligned` in
`test_formal_run.py` is pinned so that a scanner which drops either one lands a
`%s` on the integer `7` and fails the build. Its expected bytes were checked
against the C library on this host, not derived from the image.

## The narrowing, and why it is not `kind == INT_KIND`

`INT_KIND` is this model's **default** for a word, so three shapes that are
containers all carry it: an unannotated parameter (`def show(s):
printf("[%s]", s)` — measured working on both architectures, `[abc]`), a call
result whose callee declares no return type, and a loop variable over a name.
Reading "not known to be text" as "not text" would refuse every function in the
corpus that takes a string it was never told about.

So the evidence is positive, and it is the same predicate the container-element
refusal already uses: `ValueKinds.own_shape_kind` — a statement of THIS
function bound the name to an integer **on that statement's own shape**. One
predicate, two families, and two architectures that cannot disagree about which
names carry it. `None` (the source does not say) is the permissive answer and
stays that way; the gap it leaves is the one the note above `ValueKinds`
already records as the remaining one for `print`, and it is a kind-table gap
rather than a conversion gap.

## A ONE-FIELD struct prints its field, and that is not a bug

The filing says "a one-field struct too, so it is not about the frame:
`struct_is_framed` is `False` for one field and the receiver IS the field, and
it still crashes". The second half is still true for `%s`. The first half is not
a defect at all, and it is worth recording because it looks like one:

```
class One:  x: int
var c = One(7)
print(c)          ->  7
printf("%d", str(c))  ->  7
```

Both build, both run, and `7` is what CPython's value model means by a
one-field record on this path — `model.one_word_receiver_kind` is the statement
of it, and `str(c)` returning the field is the same convention `len(self.n)`
relies on. (CPython prints `<__main__.One object at 0x…>`, and that divergence
is the documented one-word convention, not a bug in either direction.) What is
wrong is only the `%s`: `7` is a number, so `%s` dereferences it.

## The open item, and whose it is

`printf("[%s]", c)` where `c` is a one-field struct **still faults** (exit 139,
both architectures, from a green build). The reason is structural: a one-field
struct has no frame, so there is no frame address for
`frame_receiver_escape_refusal` to key on, and no statement of this function
bound `c` to an integer — `c`'s own-shape evidence is `One(7)`, a CALL, which
`_own_shape_of` deliberately counts as no evidence at all.

Closing it needs a `{name: struct}` table for a construction whose result is ONE
WORD — the mirror of `fn._frame_candidates`, keyed on what a one-word
constructor binds rather than on what a frame constructor binds, filled from
`_constructor_bindings` over the NON-framed structs. **That table is
`formal3-3`'s claim**: it is the stated next step of
`bugs/FORMAL_eq_dispatch_on_a_frame_receiver.md` §1 (the same table would fix
`a == b` on a one-field struct, which has the identical shape and the identical
cause), and building it here would be two branches answering one question — the
exact failure `_frame_candidates` exists to prevent.

So the one-field `%s` waits for that table, and when it lands the site is
`_printf_arg_is_text` in the two backends: a name in the one-word table is
`False` for a `%s` conversion, and that is a three-line addition to a hook
that already exists.

## The dataclasses consequence, still refused for the same reason

`@dataclass`'s `repr=True` is the DEFAULT and generates `__repr__` as
`C(x=1)`. That is not the inherited `object.__repr__` a bare class would
otherwise reach, so it cannot be waved through as "the same as a bare class" —
even though a bare class had the same crash. So `repr=True` is refused, and
`repr=False` is refused for the same reason rather than offered as a way around
it. Both are pinned by `test_dataclasses_formal.py`, and that refusal is now
quoting a hole that is two thirds closed: a two-field struct is refused, a
plain integer is refused, and only a one-field struct still gets through.

## Verification

    python3 test_formal_run.py printf_s_of_an_integer_is_refused \
        printf_s_of_an_arithmetic_result_is_refused \
        printf_s_of_a_parameter_a_literal_and_a_bound_string_still_print \
        printf_star_width_and_literal_percent_keep_the_varargs_aligned
    # 4 PASS, and `test_formal_run.py` as a whole PASS=520 FAIL=5 with the 5
    # measured identical at 1d5a25ed.

    python3 test_formal_value_model.py a_percent_s_of_an_integer_is_refused
    # PASS — `run_refusal` builds BOTH architectures and requires the identical
    # message from each, which is the assertion that matters for a defect the
    # two backends SHARE.

    python3 test_formal.py -j 8
    # PASS=41 KNOWN-GAP=4 FAIL=0, unchanged.
