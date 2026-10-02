# FORMAL_an_attribute_read_through_an_unclassified_base_reads_zero: a wrong answer where CPython raises, and the reason `.value` on an enum member was 0

**Area:** FORMAL (both backends' member-access lowering). **Status: OPEN,
measured, deliberately not changed.** Found on `construct:sweep5:hostmods-core`
(2026-10-02) while making `enum` safe to ship; it is the mechanism underneath
that fix and it is broader than it looks.

## What I ran

```console
$ cat t.py
class C:
    A = 7
def main() -> int:
    printf("%d %d\n", (7).foo, C.A.value)
    return 0
$ python3 fire.py build --formal --no-prove -o /tmp/t t.py && /tmp/t
0 0
```

CPython raises `AttributeError` for both, and says so precisely:
`'int' object has no attribute 'foo'` / `'int' object has no attribute 'value'`.

## What it is

`formal/arm64_codegen.py`'s member-access lowering ends in an arm documented as:

> Non-named base (call result, literal, …): evaluate the base for side effects;
> formal has no object model, so the field itself reads as 0.

and `formal/x86_64_codegen.py` has the same one. So `EXPR.attr` answers **0** when
`EXPR` is anything the image cannot classify as a struct — a literal, a call
result, a word whose binding no analysis settled. Both backends agree, so this is
not a parity gap; it is a decision, and the decision is wrong in the one
direction that produces a plausible number.

**A refusal is available and is not taken.** The very next thing the path does
for a base it DOES recognise — a frame holder whose slot key is missing — is
`CodegenError`. So the tree can say "I cannot read this" and here it says "it is
0". Every other ambiguous read on this path takes the conservative direction, and
this is the exception:

* `class_constant_word` refuses a non-literal constant precisely so it cannot be
  "read as the zero an unwritten slot would give";
* `module_state_no_storage` refuses a module-level name that does not fold, for
  the same sentence;
* `refuse_none_comparisons` refuses the one construct where folding `None` to 0
  is observable.

## Why it is NOT fixed here, even though it is a wrong answer

**Because the fix is not a one-liner and it is not this claim's.** A member read
on a word is genuinely ambiguous in this model — a one-field struct's receiver IS
its field, a multi-field struct's receiver is a frame address, and an ordinary
word is an integer — so refusing every unclassified base would refuse real
programs, and guessing is what produced the wrong answers in the first place.
Getting it right needs the base to be classified, which is
`formal/model.py`'s holder analysis, not a change to two emitters' fall-through.

It was also deliberately NOT special-cased away for `enum`. A patch that taught
the emitter to treat `.value` as "the base, unchanged" would have made the test
green and left `(7).foo` still reading 0 — the shape this repo calls a "wrong
answer wearing a working-looking name". The `enum` fix went into the shared
rewrite instead (`formal/build.py`'s `_enum_member_sites`), where the accessor is
answered from the DECLARATION and never reaches an emitter at all.

## The blast radius, as far as it was measured

The hazard needs a base the image cannot classify AND a member the source reads.
In this tree's own sources that is rare — the sweep's `print() cannot classify`
family is a different mechanism (an argument to `printf`) — but it is not zero,
and it is silent in every case, which is the property that makes it worth a
document rather than a note.

## The exact next step

1. **Narrow the fall-through where the base is provably NOT a struct.** A
   `MemberExpr` whose object is a `Literal` node is the clean case: a literal has
   no storage, no type and no fields on this path or any other, so `7.foo` is
   always an `AttributeError`. Refusing that costs no real program and removes
   the whole `(7).foo` family. Do this in the SHARED place both backends read
   (`formal/build.py`, beside `refuse_none_comparisons`) so the two
   architectures cannot disagree.
2. **Then the parameter case**, which is not narrow: a parameter's binding is not
   visible to the emitter at all, which is what the existing "field access
   through 'x', and this path has no way to say what 'x' holds" message is for —
   and that message IS raised for a store. So a parameter STORE refuses and a
   parameter LOAD reads 0, which is the inconsistency worth naming. Either both
   refuse or the docstring at the fall-through has to say why not.
3. **A test that asserts the refusal**, not the 0. There is none today, which is
   why this survived: `test_formal_core_hostmods.py`'s `enum-absent` group pins
   the MODULE-side absences, and nothing pinned the emitter's fall-through.
