# `formal/examples/wide_recv.mojo` has no proof because the semantic model has no domain for a STRUCT, and it is not in `EXPECTED_FAILURES`

**Area:** FORMAL (the arm64 semantic model — `formal/arm64_proof_gen.py`'s
`_expr_go`). Found 2026-10-03 on `work/formal18-6`; measured, not fixed. The
nearest owner is `formal16-8` (`bugs/FORMAL_wide_receiver_by_reference.md`), which
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

Which one is right is not this doc's call. What is this doc's is that the choice
has not been made, and that until it is, the `formal` job is red for a reason no
marker records.

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