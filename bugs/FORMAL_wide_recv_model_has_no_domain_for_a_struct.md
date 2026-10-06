# `formal/examples/wide_recv.mojo` has no proof because the semantic model has no domain for a STRUCT, and it is not in `EXPECTED_FAILURES`

**Area:** FORMAL (the arm64 semantic model — `formal/arm64_proof_gen.py`'s
`_expr_go`). Found 2026-10-03 on `work/formal18-6`.

**Status 2026-10-04: the CHOICE is made and it is "state it as a gap"; the marker
is in `test_formal.py::EXPECTED_FAILURES` and the x86-64 half's honesty is pinned
by `test_formal_call_proof_gen.py::TestAPlaceholderModelClaimsNothing`. The
struct domain itself is NOT done and is not a light worker's row.** What the
measurement added, which the text below did not know: **x86-64 does not refuse
this program at all** — it catches the generator's exception, emits
`def main_go (n : UInt64) : UInt64 := n` with a NOTE that nothing downstream is
claimed, omits the AST bridge and the run tests with their reasons, and ends in a
`sorry` end-to-end theorem. The image exits 4, `main_go n` is `n`, and the file
says so. So the two backends DISAGREE on this shape (arm64 refuses, x86-64
disclaims) and neither claims the program is proved.

**The decision, and why it is not "a marker is cheaper":** the fix is a
value-model project — `mojo` becomes a function of an ENVIRONMENT rather than of
one word, every field read projects out of it, `Point()` starts with the class
defaults — shared by both backends and by the Lean proof, and it is the same work
`subscript_var` asks for one type further. It sits behind
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` and
`bugs/FORMAL_string_value_model.md`, i.e. the tagged-value convergence; a
half-model that answers some field reads and not others is worse than none. And
"make the two backends alike" would mean arm64 giving up an admitted theorem it
does not have, for no coverage.

The nearest owner is `formal16-8` (`bugs/FORMAL_wide_receiver_by_reference.md`), which
owns the frame-contract half of this example and does not claim the model's
domain.

**Status: the choice is MADE and the recording half is landed — `wide_recv` is
in `test_formal.py`'s `EXPECTED_FAILURES` with this failure's own words, and a
test pins both the refusal and the marker to each other. The model domain is
still not there, and §"Why the domain is the next thing" says what it costs.**

## What I ran

```console
$ python3 -c "…" probe_all.py arm64          # every formal/examples/*.mojo through
                                            # compile_formal(prove=True, check=False)
wide_recv   FAIL  NotImplementedError: model: a struct field read has no value in
                the semantic model (a `UInt64 → UInt64` function over the source's
                arithmetic); refusing rather than modelling it as 0, which would
                be a false statement about the source
```

Identical on **master's tip** (`6ccb36df`) and on this branch's base
(`86d60026`). No Lean: the refusal is at GENERATION time.

## What it is, exactly

`formal/examples/wide_recv.mojo` is the two-field receiver example:

```mojo
struct Point:
    var x: Int
    var y: Int
    fn set_x(self, v: Int): self.x = v
    fn get_x(self) -> Int: return self.x
    fn get_y(self) -> Int: return self.y

def main(n) -> Int:
    var p = Point()
    p.set_x(3)
    p.set_x(4)
    return p.get_x() + p.get_y()
```

and the refusal comes from `_expr_go`'s last arm (`formal/arm64_proof_gen.py:722`):

```python
if isinstance(e, (F.MemberExpr, F.SubscriptExpr)):
    _no_value_model(e, "struct field read" if isinstance(e, F.MemberExpr)
                    else "list subscript")
```

`get_x` returns `self.x`, so translating `main`'s body reaches a field read, and
the model's domain is `UInt64 → UInt64` — a function of the ENTRY argument. A
struct's field is not a function of `n`: `p.x` is 4 and `p.y` is 0 whatever `n`
is. So there is no term to emit, and answering 0 would be a false statement about
the source, which is why the arm refuses rather than defaulting.

**The machine half is fine.** `bugs/FORMAL_wide_receiver_by_reference.md` §"The
proposition" quotes the emitted `main_Point_set_x_frame_contract` — the mutator's
frame contract generates — and the corpus's run tests build and run this program
on both architectures. What is missing is the SOURCE half, and it is a model
domain, not a lowering.

**This is the same shape as `subscript_var`, which IS recorded.** That example's
marker in `test_formal.py` says it outright: "the semantic model `mojo : UInt64 ->
UInt64` has no domain for a list, so `a[i]` has no value in it". A struct field
read is the same gap with a different syntax, and it has no marker.

## Why nothing in the tree records it

`test_formal.py`'s `EXPECTED_FAILURES` holds `fib`, `countdown`, `wge` and
`subscript_var` — **not `wide_recv`** — and `tools/suite.py` registers

```python
test('formal', [PY, 'test_formal.py'], j=True, deps=['preflight', 'prooflib'], …)
```

with no `expect=`. So `wide_recv` is an UNEXPECTED failure of a job the registry
says must be green, and it is a different failure from the four that are marked.
A job that is red for an unmarked reason is the expensive kind of red: the next
session reads the marker list, sees the file is not in it, and re-derives this.

## The next step

**Both directions below are now decided; what remains is the struct domain, and it
is named in the Status at the top with the claims it sits behind.** The text is
kept because the two directions are the two ways this could be closed and a
reader deciding to close it needs to know which one this tree took and why.

Two directions, and the choice is a decision rather than an exercise:

* **give the model a struct domain** — `mojo` becomes a function of an
  environment rather than of one word, every field read projects out of it, and
  `Point()` starts with the class-level defaults the language gives it. That is
  the same work `subscript_var`'s marker asks for (a list domain plus "a memory
  image for the blob"), one type further, and it is a value-model change shared
  by both backends and the Lean proof.
* **or state it as a gap**, the way `subscript_var` is: add `wide_recv` to
  `test_formal.py`'s `EXPECTED_FAILURES` with the reason "the model has no domain
  for a struct, so a field read has no value in it" — which is true, costs
  nothing to run, and keeps the marker list an honest account of what the job
  cannot do.

Which one is right WAS not this doc's call; it is now, and it was the second.
`test_formal.py -j 1 wide_recv` reports `PASS=0 KNOWN-GAP=1 FAIL=0` with the
shared generator's own refusal as the detail, so the marker list is an honest
account of what the job cannot do rather than a list of four proofs with a fifth
unrecorded.

## 0. The choice, made (2026-10-04, `work/formal19-5`): recorded, and the marker
## is pinned to the measurement

**The second direction, and the reason the first is not this session's work.**
The choice is not a coin flip between two similar amounts of effort: the two
directions are one line long and one multi-session change, and the long one is
the SAME change `subscript_var` is already carrying an entry for. Measured
reasons, not preference:

* **The two missing facts are `subscript_var`'s two missing facts, one type
  over.** That marker's own words: "The first term needs a list domain in the
  model and a memory image for the blob; the second is a `Frame.frameToEnv`-shaped
  fact about the blob." A struct needs the first term's domain (a projection out
  of an environment) and the second term's relation (the frame's slots ARE the
  struct's fields), and nothing in this example lets one be done without the
  other: `_expr_go`'s Python evaluator tracks `p` as a field map and emits
  `(4 : UInt64)` for `p.get_x()`, but the emitted Lean term is only a statement
  about the SOURCE once the frame stores at `[rsp + k]` are related to those
  fields, and no emitted term does that.
* **It is a change to `mojo` itself**, so it lands on every generated proof:
  `mojo`, `eval_eq_mojo`, the run tests, every per-export contract and both
  backends' generators. `mojo : UInt64 → UInt64` is quoted by name in eleven
  places in `formal/arm64_proof_gen.py` alone. A value-model change of that
  width is a project, and it is the one `bugs/FORMAL_proof_coverage_census_2026-10-03.md`
  and `formal16-8`'s doc both already point at.

**What landed, and why recording it is not silence.** `test_formal.py`'s
`EXPECTED_FAILURES` holds `wide_recv` with the failure's own words — the refusal
is `NotImplementedError: model: a struct field read has no value in the
semantic model …`, and the marker's reason contains the generator's own phrase
`struct field read`. The file's contract for an entry is "known unproven, for
the stated reason — NOT 'passing'", so this converts an UNEXPECTED failure of a
job the registry says must be green into a declared one; nothing is stubbed with
`sorry`, and `test_formal.py`'s own stale check reports the entry the day the
example starts passing.

**And it cannot rot quietly**, which is the part that matters, because a marker
whose reason has drifted from the failure is worse than no marker.
`test_formal_call_proof_gen.py::TestStructFieldHasNoValueInTheModel` pins three
things, all Lean-free:

1. the example is still refused, and the refusal still contains
   `struct field read` — so a model that grows a struct domain fails here first,
   with the reason spelled out, instead of leaving a marker that forgives
   nothing;
2. `test_formal.py`'s marker names this refusal (so the two cannot become two
   accounts of one gap);
3. **the program still builds on BOTH backends with proof generation off** — the
   measurement that decides which side of the boundary this example is on. It is
   a model-domain gap, not a lowering one, and if that ever stops being true the
   marker is wrong and this says so.

`python3 test_formal_call_proof_gen.py`: 61 tests, 0 failures.

## Why the domain is the next thing, stated as the size it is

One field read needs, all of it before `wide_recv` can be proved:

1. **a struct in the model's domain.** `mojo` becomes a function of an
   environment; `Point()` starts from the class-level defaults the language
   gives it (`0` for an unannotated `var x: Int`), and a field read projects
   out of it. `subscript_var` wants the same with a list and a "memory image for
   the blob".
2. **the frame's slots related to those fields.** The source value is `4`; the
   machine's is the word the emitter stored at `[rsp + k]`, and nothing emitted
   says they are the same word. `Frame.frameToEnv`-shaped, per
   `bugs/FORMAL_wide_receiver_by_reference.md`.
3. **the method call's value.** `p.get_x()` is a call whose receiver is a frame
   address; the model needs the frame's contents as an environment value, which
   is (1) and (2) again from the other side.

Nothing here is a dataflow question, and none of it is reachable by making the
generator more careful: the term it would have to emit does not exist yet.

## Reproducing

```console
$ cd "$(git rev-parse --show-toplevel)"
$ python3 -c "
import sys, os; sys.path.insert(0, os.getcwd())
import formal.build as B
try:
    B.compile_formal('formal/examples/wide_recv.mojo', output='.tmp/wr.aout',
                     prove=True, check=False)
except Exception as e:
    print(type(e).__name__, e)"
NotImplementedError model: a struct field read has no value in the semantic model
$ python3 test_formal_call_proof_gen.py TestStructFieldHasNoValueInTheModel
```
