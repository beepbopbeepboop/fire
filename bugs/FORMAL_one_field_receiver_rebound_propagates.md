# FORMAL_one_field_receiver_rebound_propagates: `self = other` on a ONE-FIELD struct copies where CPython rebinds a name

**Status 2026-10-04 (`work/formal27-4`): §2 FIXED, §3's one-field half with it,
and §3's two MULTI-FIELD refusals FIXED — §3 is closed. Nothing remains here;
this document is kept (rather than deleted with the fix) only because §1 and §2
are the MEASUREMENT a reader needs before re-deriving them, and the two rows
that pin §1's refutation are named below.**

**Area:** FORMAL (`formal/build.py`'s `_collect_receiver_rebinds` and
`_collect_one_field_receiver_rebinds`, the one-field receiver write-back in
`formal/model.py`'s `receiver_writeback_name`, and the new
`_receiver_unused_after` liveness reader).

Found 2026-10-02 on `work/formal8-10` while answering
`FORMAL_receiver_copied_to_another_name_does_not_take_effect.md` (deleted: its
central claim is refuted by CPython — see §1).

## 0. What landed, 2026-10-03 (`work/formal10-4`)

**§2 is closed, and it is closed by a rule that had to be asked BEFORE the
rewrite.** The obstacle §2 names is the right one: `_rewrite_self_fields`
collapses `recv.<field>` onto `recv`, so `self.a = other.a` and a hand-written
`self = other` are the same text by the time `_collect_receiver_rebinds` runs,
and the two need opposite answers. So the question moved rather than being
sharpened:

| | where | what |
|---|---|---|
| the question | `formal/build.py`, `_collect_one_field_receiver_rebinds`, called at the TOP of `_prepare_functions`'s per-function loop | asks "does a one-field MUTATOR assign its receiver BY NAME a name of its own type" while `self.a = …` is still spelled with the field |
| the recogniser | `formal/model.py`, `receiver_own_type_names` | `(parameters, locals)`, from declarations only — `other: Self` / `other: R`, and `var t = R()`. One function for both receiver rules; `one_field_mutating_methods` now takes its member name from the new `method_member_name` rather than a second copy of that loop |
| the refusal | `formal/model.py`, `one_field_receiver_rebind_refusal` | one wording for both architectures, naming the parameter/local and what Python does instead |
| the cost | `tools/formal_receiver_rebind_census.py` (new) | **0 sites in 370 files.** 51 hand-written `self = …` in one-field methods: 23 constructions of their own struct, 28 values the method computed, **not one** name of the receiver's own type |

Measured, both architectures, after: `T.take()` with `self = other` is refused
with `` `other` is a parameter of this method and holds a `T` ``; the same for
the local spelling; and `self.a = other.a` → `a=2`, `self = self + 4` → `a=5`,
`Bool.__iand__`'s spelling included, all unchanged. `test_formal_run.py`:
`one_field_receiver_rebound_to_a_parameter_is_refused`,
`one_field_receiver_rebound_to_a_local_of_its_own_type_is_refused` (both build
both backends and require identical wording), and three guards in
`BOTH_ARCH_CASES` — the field store, the word-shaped rebinding the stdlib's
in-place operators use, and a PLAIN receiver's rebinding, which is left alone
because a receiver that is never handed back cannot reach the caller anyway.

**Refused rather than delivered, and the reason is the ABI, not caution.** One
return word is already the receiver, and Python's own reading of the store is a
write into the aliased object's own caller — a second word this path does not
have. Suppressing the write-back instead would be right when the method stores
nothing else afterwards and silently wrong when it does, because Python sends
every later `self.a = v` through the alias.

## 0a. What landed, 2026-10-04 (`work/formal27-4`): §3's TWO refusals, and the
## rule they were over-broad for

Both rows of §3 were **CPython programs this path refused**, and the reason
neither is a defect is the same sentence in two directions: a multi-field
struct's receiver IS an address, and Python's rebinding of a name is faithful
for the method's own body while the caller's frame is untouched — which is also
Python's answer.

| §3 row | what landed |
|---|---|
| `self = t`, `t` a LOCAL of the receiver's own type | **allowed**, by asking `model.receiver_own_type_names`'s SECOND set where the rule asked only the first. `var t = R()` is an address of the receiver's own frame layout, so `self = t` repoints the method exactly as Python does. Measured `a=7 b=8` on CPython 3.14 and on both backends. A **constructor** is excluded, which is §3's own decision: this path never CALLS a constructor (`model.init_body_stores` inlines the stores at the construction site), so the frame a rebinding would repoint at is one no caller ever wrote |
| `self = 5`, no field read afterwards | **allowed**, by `_receiver_unused_after` — the "and a field is read afterwards" test §4 said was missing. A rebinding nobody reads cannot drop a store, and a multi-field receiver is never handed back (`model.receiver_writeback_name` is a ONE-FIELD mutator's mechanism and answers None here), so the caller's slot is untouched. Measured `read() == 7` on CPython 3.14 and on both backends |

**Both exemptions are gated on the receiver being an ADDRESS**, which is what
keeps the one-word holder of a placed frame refused: there the receiver WORD is
the frame address the caller still holds, so the same assignment destroys it,
and no liveness test makes that sound. Measured, still refused on both
architectures:
`receiver_rebound_to_a_word_is_refused_on_a_one_word_holder_of_a_frame`.

**The liveness test is POSITION-SENSITIVE, and that is the whole of it.**
`self.a = 1` BEFORE `self = 5` is a store that reaches the caller and
`self.a = 1` AFTER it is a store into whatever word `5` is, so "is the name
mentioned anywhere" would refuse the first program for the second one's reason.
`_receiver_unused_after` walks the body once in `iter_nodes_with_parent`'s
pre-order and asks whether any node PAST the rebinding statement's own subtree
mentions the receiver; the guard row is
`both_arch_a_store_before_the_rebinding_still_reaches_the_caller` (`a=9`, which
is CPython's answer).

**Three rows that pinned the over-broad refusal became rows that pin the
narrowed rule**, which is the honest way to narrow a rule whose rows are its
anti-rot: `receiver_rebound_to_a_word_then_read_is_refused` (the same program
plus the one store that makes the hazard real — this is the hazard half),
`receiver_rebound_under_another_spelling_is_refused` (`this = 5; this.a = 1`, so
it still says the rule reads the receiver SET and not the literal `self`, and it
now also says the liveness reader does), and `receiver_rebound_to_a_call_is_refused`
(a rebinding to a CALL, with `f` DEFINED — a row whose only defect was an
undefined callee would now be reporting the linker's diagnosis instead of this
rule's).

`model.receiver_rebound_from_a_word_refusal` states all three allowed shapes,
because a refusal that lists two of the three things it permits sends the reader
to the wrong conclusion.

**One thing this measurement does NOT claim:** that the corpus gains a file. The
census §0 quotes already says the corpus has **0** sites of the local spelling,
and the `self = 5` spelling is 0 stdlib sites for the same reason (`bool.mojo`
and the other in-place operators are ONE-field owners, which this change does
not touch). What it buys is that the two shapes are answered the way CPython
answers them instead of refused, which is what §3 asked for.

## 1. The premise, which is what the whole `self = X` rule gets wrong

**Assigning to `self` inside a method REBINDS THE LOCAL NAME. Python has no
"assign the receiver" operation, so nothing is copied into the object the caller
holds**, and the method's own later `self.<field>` reads and writes go to
whatever `self` now names.

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

**The last two rows of that table are §3's two rows, and `self = 5` with the
reads in ANOTHER method is the one whose refusal was over-broad** — a program
CPython runs, which answered `7` here and answered `read() == 7` on both
architectures after §0a.

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
there. Re-measured 2026-10-03 with `tools/formal_receiver_rebind_census.py`,
which asks the RULE's own recogniser rather than a second reading of it: 151
sites in 34 files, 51 under a one-field owner, and **0** of them a parameter or
a local of the receiver's own type — §0's rule costs nothing in this corpus.

## 3. Two refusals that were over-broad, from the same premise — FIXED
## 2026-10-04, by §0a

| shape | CPython | this path, then | this path now |
|---|---|---|---|
| `self = t`, `t` a LOCAL of the receiver's own type, **multi-field** owner | runs, `a=0 b=0` | **refused**: "points the method at a different word" | **runs**, `a=7 b=8` |
| `self = 5`, and no field is read after it, **multi-field** owner | runs, `read() == 7` | **refused**, same message | **runs**, `read() == 7` |

Re-measured on both architectures 2026-10-03 (`work/formal10-4`) before the fix:
both refused, with `receiver_rebound_from_a_word_refusal`'s wording, and the
parameter spelling of the same rebinding already built and answered `a=1`. So
the two spellings of one rebinding were decided differently by whether the value
happens to be a parameter — and the parameter spelling is the one §1's
measurement shows is right.

**Why the first row was not simply allowed, which is what §0's rule for one-field
owners does.** The census (`tools/formal_receiver_rebind_census.py`) finds
**exactly one** site of this spelling in the corpus, and it is a CONSTRUCTOR:
`std/utils/index.mojo:231`, `var tup = Self(); …; self = tup`. A frame
receiver's rebinding is faithful for the method's own body — the receiver
register becomes the other frame's address, which is exactly what Python's
rebinding does, and the caller's frame is untouched, which is also Python's
answer. But in a constructor the caller's object IS the one being initialised, so
the faithful lowering hands back a frame nobody wrote and the caller silently
reads zeros where CPython raises `AttributeError`. That is the judgement §0a
implements: allow the local spelling, refuse it in a constructor. (It buys 0
files and costs the 1 that was already refused — `init_body_stores` refuses
that shape at the construction site in any case, which is measured and is why
the exclusion costs nothing.)

**The part of the message that was right, and is why the second rule needed the
liveness half rather than deletion.** `self = 5` FOLLOWED BY a field read is a
real hazard: CPython raises `AttributeError: 'int' object has no attribute 'a'`
and this path would read `[5 + 8·slot]` — a load from wherever the word points.
So the rule is sound for the shapes where the rebound word is not an address of
the receiver's layout AND a field is read through it afterwards, and over-broad
for the rest — which is exactly the line `_receiver_unused_after` draws.

## 4. The next step: DONE

Question 1 (**§3 row 1**) was **DONE** by §0a: the recogniser existed
(`model.receiver_own_type_names` returns the locals as well as the parameters)
and the decision — a constructor is the one exclusion, because the object being
pointed at is the one being CONSTRUCTED — is now made and written down at the
site that takes it.

Question 2 (**§3 row 2**) was **DONE** by the same change: `_value_may_be_a_frame`
was already the recogniser both halves go through, and the missing half was the
"and a field is read afterwards" test, which is `_receiver_unused_after`.

What remains is not a question about this rule. Both rows were questions about
the by-reference design (`bugs/FORMAL_wide_receiver_by_reference.md`), and the
answer to both was that the by-reference design is already right and the RULE
was reading it too strictly.

## 5. Reproducing every number here

```console
$ python3 /tmp/y.py                     # the four CPython shapes of §1, as written
1 2 / 0 0 / 0 0 / 7
$ python3 tools/formal_receiver_rebind_census.py    # §0's cost: 0 aliasing sites
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/onefield.mojo
build: T.take() assigns its receiver `self` the name `other`, and `other` is a
  parameter of this method and holds a `T`, so this is Python REBINDING …
$ python3 test_formal_run.py one_field_receiver_rebound_to_a_parameter_is_refused \
      one_field_receiver_rebound_to_a_local_of_its_own_type_is_refused \
      receiver_rebound_to_a_word_then_read_is_refused \
      receiver_rebound_to_a_word_is_refused_on_a_one_word_holder_of_a_frame \
      both_arch_receiver_rebound_to_a_local_leaves_the_callers_object \
      both_arch_receiver_rebound_to_a_word_nobody_reads_again_leaves_the_callers_object \
      both_arch_a_store_before_the_rebinding_still_reaches_the_caller
```
