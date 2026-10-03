# FORMAL_one_field_receiver_rebound_propagates: `self = other` on a ONE-FIELD struct copies where CPython rebinds a name

**Area:** FORMAL (`formal/build.py`'s `_collect_receiver_rebinds` and
`_collect_one_field_receiver_rebinds`, and the one-field receiver write-back in
`formal/model.py`'s `receiver_writeback_name`).
**Status: §2 FIXED (the silent wrong answer) and §3's one-field half with it;
§3's two MULTI-FIELD refusals remain OPEN, now with the corpus measurement that
says what narrowing them would cost.**

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
there. Re-measured 2026-10-03 with `tools/formal_receiver_rebind_census.py`,
which asks the RULE's own recogniser rather than a second reading of it: 151
sites in 34 files, 51 under a one-field owner, and **0** of them a parameter or
a local of the receiver's own type — §0's rule costs nothing in either corpus.

## 3. Two refusals that are over-broad, from the same premise — STILL OPEN,
## and now measured rather than argued

| shape | CPython | this path |
|---|---|---|
| `self = t`, `t` a LOCAL of the receiver's own type, **multi-field** owner | runs, `a=0 b=0` | **refused**: "points the method at a different word" |
| `self = 5`, and no field is read after it, **multi-field** owner | runs, `read() == 7` | **refused**, same message |

Re-measured on both architectures 2026-10-03 (`work/formal10-4`): both still
refuse, with `receiver_rebound_from_a_word_refusal`'s wording, and the parameter
spelling of the same rebinding still builds and answers `a=1`. So the two
spellings of one rebinding are still decided differently by whether the value
happens to be a parameter.

**Why the first row is not simply allowed, which is what §0's rule for one-field
owners does.** The census (`tools/formal_receiver_rebind_census.py`, 100 framed
sites in 25 files) finds **exactly one** site of this spelling in the corpus,
and it is a CONSTRUCTOR: `std/utils/index.mojo:231`, `var tup = Self(); …;
self = tup`. A frame receiver's rebinding is faithful for the method's own body
— the receiver register becomes the other frame's address, which is exactly what
Python's rebinding does, and the caller's frame is untouched, which is also
Python's answer. But in a constructor the caller's object IS the one being
initialised, so the faithful lowering hands back a frame nobody wrote and the
caller silently reads zeros where CPython raises `AttributeError`. Allowing the
spelling would trade a loud refusal for a silent wrong answer **on the only
program in the corpus that uses it**, and would fix nothing: no file needs it.
So the line that would actually be defensible — "allow the local spelling except
in a constructor" — buys 0 files and costs the 1 that is currently refused. That
is a judgement about the by-reference design, not a mechanical gap, which is
where §4 puts it.

**The part of the message that is right, and is why the second rule is not
simply deleted.** `self = 5` FOLLOWED BY a field read is a real hazard: CPython
raises `AttributeError: 'int' object has no attribute 'a'` and this path would
read `[5 + 8·slot]` — a load from wherever the word points. So the rule is sound
for the shapes where the rebound word is not an address of the receiver's layout
AND a field is read through it afterwards, and over-broad for the rest.

## 4. The next step, and the decision it needs

Question 1 is **DONE** (§0), by refusal rather than by suppressing the write-back
— the ABI has one word and Python's reading of the store needs a second.

Question 2 is unchanged and is the whole of what is left:

1. **The local spelling of a rebinding, for a FRAMED owner** (§3 row 1). The
   recogniser exists — `model.receiver_own_type_names` returns the locals as well
   as the parameters, and the framed rule uses only the parameters today — so the
   change is one set. What is missing is the decision: whether "a rebinding
   stays inside the method" is also the right rule when the object being
   pointed at is the one being CONSTRUCTED, which is the only shape the corpus
   contains and the only shape where the faithful answer is a broken program.
2. **Then `self = <word>` with no field read through the rebound receiver
   afterwards** (§3 row 2), which needs the line drawn between "the value is an
   address of the same layout" (allowed, §1) and "the value is a word AND a field
   is read through it after" (refused, and it is a real hazard).
   `_value_may_be_a_frame` is the recogniser both halves already go through; the
   missing half is the "and a field is read afterwards" test, which is flow
   analysis over the rebinding rather than a fact about the declaration.

Both are a question about the by-reference design
(`bugs/FORMAL_wide_receiver_by_reference.md`) rather than about this rule, which
is why they are still here and §2 is not.

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
      both_arch_one_field_stores_through_the_receiver_still_reach_the_caller \
      both_arch_one_field_plain_receiver_rebinding_is_left_alone
```
