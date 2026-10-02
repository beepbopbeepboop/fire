# FORMAL_a_negative_class_constant_is_not_a_literal: `-3` is an `UnaryOp`, so `class C: A = -3` is refused, and the refusal is right for the wrong reason

**Area:** FORMAL (shared model — `formal/model.py`'s literal classification).
**Status: OPEN, measured, not fixed.** Found on `construct:sweep5:hostmods-core`
(2026-10-02) by `test_formal_core_hostmods.py`'s enum corpus, which is the first
thing in the tree to put a negative value in an enum member and therefore the
first to hit it.

## What I ran

```console
$ cat t.py
class C:
    A = -3
    B = 7
def main() -> int:
    printf("%lld %lld\n", C.A, C.B)
    return 0
$ python3 fire.py build --formal --no-prove -o /tmp/t t.py
build: C.A reads a class-level constant of C, whose value is `-3` — and a formal
value is one 64-bit word with nowhere to keep a non-literal one: a class-level
constant's value is written in the class body, and this path has no module-global
storage to read it back out of …
```

## What I saw, and what I expected

**Expected:** `-3` is a literal. It is one token wider than `3` and it is exactly
representable in the word this path already uses for `3`.

**Saw:** refused, with a message that says the value "is not a value this build
can materialize". The message is FALSE about `-3` and that is the whole problem:
a reader who believes it goes looking for something non-literal in their own
source, and there is nothing there.

The cause is one line of the shared model:

```console
$ python3 -c "
import sys; sys.path.insert(0,'.')
import fire_compiler as F, formal.model as M
st = [s for s in F.Parser(F.py_tokenize('class C:\n    A = -3\n')).parse_module()
      if type(s).__name__=='StructDef'][0]
print(type(st.fields[0].value).__name__, M.literal_default_word(st.fields[0].value))"
UnaryOp ('opaque', None)
```

`literal_default_word` recognises `IntLiteral`, `BoolLiteral` and `StringLiteral`
and returns `DEFAULT_OPAQUE` for everything else. A negative number parses as
`UnaryOp('-', IntLiteral(3))`, so it falls into the opaque arm — and `3` with a
minus in front of it is the most obviously-foldable expression in the language.

## Why it is NOT fixed here

The direction of the failure is SAFE — a refusal, never a wrong number — and the
fix is not small in the way it looks. `literal_default_word` is the shared
classifier behind `class_constant_word` AND `struct_default_word`, so it decides
what every dataclass field default, every class-level constant and every
`comptime` binding in the tree can materialize. Widening it changes the answer
for every one of those, which is a change to the tree's shared value model and
belongs to whoever owns that, not to a host-module change.

It was found on `sweep5:hostmods-core`, whose claim is the four host modules, and
the one place it bit is an enum member's `.value` — where the fix would have been
a one-line special case in `_enum_member_sites` and would have been exactly the
kind of special-case this repo forbids. So the enum corpus documents the boundary
instead of encoding it, and says which document owns it.

## The exact next step

Teach `literal_default_word` the folds that are exact, in the order the
`DEFAULT_*` arms already imply:

1. `UnaryOp('-', IntLiteral(n))` → `DEFAULT_INT, -n`, and `UnaryOp('+', …)` →
   `DEFAULT_INT, +n`. Measure the double-negative case (`--3` is a syntax error in
   Python, so there is nothing to guard).
2. `UnaryOp('~', IntLiteral(n))` → `DEFAULT_INT, ~n`. Exact, and worth checking
   against CPython's own answer rather than assuming: `~3` is `-4`.
3. Then, separately and only if something wants it, literal-only ARITHMETIC
   (`1 + 2`), which is a bigger widening because `+` on two words is a different
   claim than `+` on two literals.

Each step needs its own case in whatever test covers `literal_default_word`, and
the corpus for step 1 is the enum table in
`test_formal_core_hostmods.py` — `ENUM_CASES` carries `int_neg` in a comment
saying precisely which document this is, so restoring the case is the assertion
that the fix landed.

**Do not fix it in the hostmod.** `formal/hostmods/enum.mojo` must keep saying
that `A = -3` is refused, because that is still true after any fix that lands
only in `enum_member_accessor`; the message it produces is the shared one and it
is what a reader of that file will see.
