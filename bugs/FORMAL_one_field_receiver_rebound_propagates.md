# FORMAL_one_field_receiver_rebound_propagates: `self = other` on a ONE-FIELD struct copies where CPython rebinds a name

**Area:** FORMAL (`formal/build.py`'s `_collect_receiver_rebinds`, and the
one-field receiver write-back in `formal/model.py`'s `receiver_writeback_name`).
**Status: OPEN, NOT FIXED, one silent wrong answer plus two measured
refusals that are over-broad — all three from one premise, which is false.**

Found 2026-10-02 on `work/formal8-10` while answering
`FORMAL_receiver_copied_to_another_name_does_not_take_effect.md` (deleted: its
central claim is refuted by CPython — see §1).

## 1. The premise, which is what the whole `self = X` rule gets wrong

**Assigning to `self` inside a method REBINDS THE LOCAL NAME. Python has no
"assign the receiver" operation, so nothing is copied into the object the
caller holds**, and the method's own later `self.<field>` reads and writes go
to whatever `self` now names.

Measured, CPython 3.14, four shapes:

```python
class R:
    def __init__(self): self.a = 0; self.b = 0
    def copy_from(self, other): self = other
    def zero(self):           self = R(); self.a = 5; self.b = 6
    def via_local(self):
        t = R(); t.a = 5; t.b = 6; self = t

r = R(); r.zero();               print(r.a, r.b)   # 0 0
p = R(); q = R(); p.a = 1; q.a = 2
p.copy_from(q);                 print(p.a, q.a)   # 1 2
s = R(); s.via_local();          print(s.a, s.b)   # 0 0
w = R(); w.a = 7
w.rebind()                       # def rebind(self): self = 5
print(w.read())                                     # 7
```

**Every one of those is a program CPython RUNS.** `bugs/FORMAL_receiver_
copied_to_another_name_does_not_take_effect.md` asserted the first table was
`a=2 b=2` and called the difference a silent wrong answer; it is `a=1 b=2`,
which is what both backends answer. That doc is deleted, and the two rows that
now pin it —
`both_arch_receiver_copied_from_another_keeps_the_callers_value` and
`both_arch_receiver_assigned_a_construction_keeps_the_callers_value` in
`test_formal_run.py` — are the anti-rot for exactly this misreading.

## 2. The one shape that IS a silent wrong answer: a ONE-FIELD struct

```mojo
struct T:
    var a: Int
    def take(out self, other: Self):
        self = other

def main(n):
    var x = T(); x.a = 1
    var y = T(); y.a = 2
    x.take(y)
    printf("a=%d", x.a)
```

| | |
|---|---|
| CPython | `a=1` |
| arm64 | **`a=2`** |
| x86-64 | **`a=2`** |

Builds, runs, exits 0. A one-field struct's receiver is its single WORD rather
than an address, and `receiver_writeback_name` has the method RETURN the
receiver so the call site stores it back — which is what makes
`self._value = self._value + k` reach the caller. So the store `self = other`
is propagated to the caller's object, and CPython propagates nothing.

**Why this one cannot be told apart from a shape that must keep working.**
`_rewrite_self_fields` runs BEFORE `_collect_receiver_rebinds`
(`_prepare_functions:10335` then `:10463`), and it collapses `recv.<field>`
into `recv`. So for a one-field struct

```python
def take(self, other): self._value = other._value      # CORRECT: x._value == 2
```

becomes `self = other` after the rewrite — **the same text** as the hand-written
rebinding above, and the two need OPPOSITE answers. `struct_is_one_field` is
what the collector skips on today, with the comment that the rewrite's own
store reaches the caller through the write-back; that comment is right about the
mechanism and it is why the skip cannot simply be deleted.

**The exposure is small, and that is measured.** `self = <a parameter of the
receiver's own type>` — the shape above — appears in **0 of 415 repository
files and 0 of 587 stdlib files** (a parse plus one walk per method; the same
census that found 155 sites of the wider `self = <anything>` family, 115 of
them in `__init__` bodies that a different refusal already covers). So nothing
in either corpus is relying on today's answer, and a refusal costs nothing
there.

## 3. Two refusals that are over-broad, from the same premise

| shape | CPython | this path |
|---|---|---|
| `self = t`, `t` a LOCAL of the receiver's own type | runs, `a=0 b=0` | **refused**: "points the method at a different word" |
| `self = 5`, and no field is read after it | runs, `read() == 7` | **refused**, same message |

Both are refused by `receiver_rebound_from_a_word_refusal`, whose text says
"CPython rejects this shape outright, so the source is not a program that
computes a different answer". For `self = t` that is false: `t` is an address
of the same layout, exactly as `other` is, and the rule already treats the
parameter spelling as a copy (§1's deleted doc called the difference "a rule
of the form 'never rebind a receiver' would break it for no reason"). The two
spellings of the same rebinding are decided differently by whether the value
happens to be a parameter.

**The part of the message that is right, and is why the rule is not simply
deleted.** `self = 5` FOLLOWED BY a field read is a real hazard: CPython
raises `AttributeError: 'int' object has no attribute 'a'` and this path would
read `[5 + 8·slot]` — a load from wherever the word points. So the rule is
sound for the shapes where the rebound word is not an address of the receiver's
layout AND a field is read through it afterwards, and over-broad for the rest.
Deciding where that line is needs the answer to "may a method rebind its own
receiver at all", which is a question about the by-reference design
(`bugs/FORMAL_wide_receiver_by_reference.md`) rather than about this rule.

## 4. The next step, and the decision it needs

Two questions, in this order, and the first is a decision rather than an
implementation:

1. **Is `self = X` inside a method MEANINGFUL on this path at all?** For a
   multi-field receiver the answer is already yes and correct (the receiver
   register is the address and rebinding it is Python's own semantics, §1). For
   a one-field receiver the write-back makes the same source mean "assign the
   caller", which is the wrong reading. The consistent rule is "a rebinding
   stays inside the method", which for one field means the write-back must be
   SUPPRESSED on a path that rebinds the receiver — a property of the method,
   decidable at the call site from the same evidence `_apply_receiver_writeback`
   already has (does this method assign its receiver?), and cheaper than a
   refusal. Refusing is the fallback and costs nothing in either corpus (§2).
2. **Then the over-broad refusals**, which need the line drawn between "the
   value is an address of the same layout" (allowed, §1) and "the value is a
   word and a field is read through it after" (refused, and it is a real
   hazard). `_value_may_be_a_frame` is the recogniser both halves already go
   through; the missing half is the "and a field is read afterwards" test.

**Not fixed here, deliberately.** Both are a change to what a receiver means on
one of the two paths, in a file (`formal/build.py`) several workers are editing
this round, and the measurement that says the cheap answer is cheap (§2) is a
reason to take it deliberately rather than as a side effect of a bug doc about
a multi-field struct — which turned out to describe CPython incorrectly.

## 5. Reproducing every number here

```console
$ python3 /tmp/y.py                     # the four CPython shapes of §1, as written
1 2 / 0 0 / 0 0 / 7
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/onefield.mojo
$ ./.tmp/x                              # arm64 and x86_64: "one-field a=2"
$ python3 test_formal_run.py -k receiver   # the two pinned rows, both backends
```