# A ONE-FIELD struct's mutating method is a no-op: `self.<field> = …` inside it never reaches the caller

**Area:** FORMAL (the one-word value model; `out self` receivers). Found
2026-10-01 on `work/formal2-re-and-slice` while fixing the derived field set
(`test_formal_bracketed_method_field_set.py`). **NOT FIXED — and it is not the
bracketed-call construct, it is the one that construct uncovered.**

## What was run

```
$ cat onefield.mojo
struct Cell:
    var _value: Int
    def bump(out self):
        self._value = self._value + 4

def main() -> Int:
    var c = Cell()
    c._value = 5
    c.bump()
    printf("v=%d", c._value)
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64 -o onefield.out onefield.mojo
Built: onefield.out  [arm64/macho]
$ ./onefield.out
v=5                       # CPython says v=9
```

**Both architectures, and on the PLAIN spelling** — `c.bump()`, no brackets
anywhere — so this is not the comptime-specialization ABI
(`bugs/FORMAL_x86_64_comptime_specialization_abi.md`) and not the bracketed-call
rewrite (`formal/build.py`'s `_method_call_target`). It is the `out self`
receiver of a one-field struct.

## It is pre-existing, and measured both ways

Run on the tree with `formal/model.py` at its previous contents and on the tree
with this branch's field-set fix: **byte-identical output, `v=5`, both.** The
fix is in this branch because it makes this shape far more REACHABLE, not
because it causes it.

## Why the field-set fix makes it worse, which is the reason it is urgent

`struct_is_one_field` (`formal/model.py`) says a one-field struct's receiver IS
its field — no indirection, no frame. That is the design, and it is what makes
`Optional`, `List`'s inner types and every other single-slot struct cheap. But
it puts the callee's `self.<field> = …` at the far end of an ordinary word, and
the emitter has to write the word **back through the receiver** for the caller's
variable to see it. The measurement says it does not: the callee computes the
new value and drops it.

So the field-set fix moves `Optional` from a two-field struct (wrongly framed,
refused) to a one-field struct (correctly un-framed, **and silently losing every
write through a mutating method**). That trade is strictly better than the
refusal it replaces — a refusal is not a program, and the dependent files are
moved to their next real blocker — but it is only better if the write-back is
fixed, and right now it is not. **The order matters: land this doc's fix before
anything starts emitting programs that mutate a one-field struct's field
through a method.**

The way to confirm the diagnosis on a given program: make the struct TWO fields
and the write appears. Everything measured here that has two fields is correct;
everything with one field loses the write.

## Why it is a separate fix and not part of the field-set change

The two are independent:

* the field-set defect is in `formal/model.py`'s `_self_field_names` — a NAME
  walk, in the build pass, deciding what a struct's layout is;
* this one is in the emitters — a `MemberExpr` store through a one-field
  struct's `out self` receiver, in `formal/arm64_codegen.py` and
  `formal/x86_64.py`, and it reproduces with NO field-set change at all.

Mixing them would make a correct, well-scoped derivation fix carry an unrelated
emitter bug, and would hide which of the two a regression belongs to.

## The next step

The receiver word for a one-field struct IS the field, so the fix is in the
`MemberExpr` store arm of each backend: when the base is a `self`-receiver of a
one-field struct, the store has to land in the CALLER's binding of that word,
not only in the callee's copy of it. `formal/model.py`'s `_one_word_field_map`
is the piece that already knows a one-field struct's receiver is its field
(`struct_is_one_field`'s docstring says the three decisions that ask it "must not
come apart"), so it is the place to start reading.

Two cases for `test_formal_run.py` when it is picked up, both differential
against CPython on both architectures, and both **on the plain spelling** so they
do not depend on the specialization ABI:

1. `out self`, no arguments: the program above, `v=9`.
2. `out self` with a runtime argument, so the value cannot be confused with a
   stale register: `def bump(out self, k: Int): self._value = self._value + k`,
   called `c.bump(4)`.

A third worth adding at the same time, because it is the shape the stdlib
actually uses and it is where a receiver-parameterised fix would show its
second-order effects: a one-field struct stored in a CONTAINER and mutated
through the container's element (`items[0].bump(4)`).

## What was measured, and what was not

* The repro, on arm64 and x86-64, on this branch and on the previous
  `formal/model.py`.
* That adding a second field makes the write appear (the same program with
  `var _value: Int` / `var pad: Int`).
* **NOT measured: the sweep delta, and NOT measured: whether any file the field-set
  fix moves to a build lands on this shape.** The second is the one that decides
  how urgent this is, and it needs a full sweep — which is the integrator's, not
  a worker's.