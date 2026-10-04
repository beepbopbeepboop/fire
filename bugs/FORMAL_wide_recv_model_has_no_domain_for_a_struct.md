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
```