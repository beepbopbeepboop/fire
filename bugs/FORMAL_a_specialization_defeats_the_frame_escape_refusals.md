# A comptime SPECIALIZATION defeats both frame-escape refusals, and the bare spelling beside it is correct

## Status

OPEN — found 2026-10-01 while registering `test_formal_receiver_position.py` for
the test estate (it was named by no spec and in no bucket; it is now
`formal-receiver-position`, in `proofs`, declared red with `expect=`). **2 of 12
cases fail, on arm64.** The root cause is located and the fix is measured; it is
NOT applied here because `formal/model.py` and `formal/build.py` are another
worker's claimed area (`construct:receiver-position-family`,
`construct:frame-address-as-value`). See "The fix" below — it is two
`isinstance(..., F.IdentExpr)` guards, and each is a place where the tree
already says in a comment that the guard is the wrong recogniser.

## What is believed

`f[T](...)` is a comptime specialization, and it names the SAME function `f`
does while contributing no call-time argument of its own. `formal/model.py`
`call_callee_name` exists to be the single recogniser for that, and its own
docstring gives the measurement that makes it safe:

> `def f[type: Int](x: Int, y: Int)` called as `f[1](3, 7)` returns 307, with
> `type`=1, `x`=3 and `y`=7, and each of the three read back correctly on its
> own.

So a specialized call and its bare twin are the same call, and any analysis that
answers a question about one and not the other has a bug.

**Two places in the frame machinery did exactly that**, and they are the two ends
of the same use-after-free:

1. **`formal/model.py` `struct_returned_frame_sites`** reserved the caller's
   block with `isinstance(node.func, F.IdentExpr)` and `node.func.name`. A
   `SubscriptExpr` callee is not an `IdentExpr`, so `stash[1](0, r)` reserved
   **no block**. The callee is the side that COPIES, and it copies into the
   word it was handed — which was an ordinary argument register — so the
   returned address named a register, and `main`'s `stash[1](0, r).a` read
   eight bytes from wherever that register pointed.

2. **`formal/build.py` `_frame_return_status`** classified a `return` whose
   value is a call with `isinstance(value.func, F.IdentExpr)` and
   `value.func.name`. A specialized call missed, so the `return` fell through
   to `words.append(...)` and the function was classified `_RETURN_WORD` — the
   "no path returns a frame address" answer. That one word is load-bearing for
   three further things: `returns_frame[fn.name]` is never set, so no caller
   reserves a block (which is (1) again, from the other side); and
   `fn._image_returns_frame` has no entry for it, so an ENTRY function that
   returns a frame gets no `entry_frame_return_refusal` at all.

The fixpoint in `formal/build.py` is not implicated and in fact makes the
inconsistency visible: `_frame_receivers` already reads
`M.call_callee_name(node.func)` for its own call edges, under the comment

> "One recogniser, four readers (`_check_frame_escapes` and
> `_check_holder_agreements` as well, and the returned-frame edge above),
> because the four have to agree about which function a call is."

Four readers were named there and two of the four — the ones above — were not
using it. The holder fixpoint KNEW `stash` returns a frame while the
block-reserver did not, and the two answers were the two ends of a
use-after-free.

## What was run, and what it saw

Each case measured on its OWN beside its bare-spelling twin, same source, arm64,
this tree. The twins are the measurement: they are the same program with the
brackets removed, so any difference is the specialization and nothing else.

| program | bare spelling | specialized |
|---|---|---|
| `stash` returns its `r` parameter, `main` reads `.a` off the result | **7** (correct) | builds, **exit 0** (source says 7) |
| `ask` returns `origin_of(r)`, `main` returns that | **refused** by name, correctly | builds, **exit 112** — a stack address read as an int |

```
$ python3 test_formal_receiver_position.py
  FAIL  refuse_a_specialized_parameter_returned: --backend=arm64 BUILT a
        construct that has no representation (expected a refusal naming
        'returned from a function that did not create it')
  FAIL  refuse_a_value_only_callee_through_a_specialization: --backend=arm64
        BUILT a construct that has no representation (expected a refusal
        naming 'which is lowered as an operation on a VALUE')
formal receiver position: PASS=10 FAIL=2
```

Both images EXIT 0 or exit with a stack address. That is the shape these
refusals exist for: `bugs/FORMAL_frame_receiver_handoff.md` §D4 records the same
program with the position check lifted answering "10 on arm64 and 0 on x86-64
where the source says 7 — a use-after-free, and the two architectures
disagreeing about what the reused bytes held", and it names the fix as exactly
this: make the recogniser see the specialization.

Confirmed from the analysis side, which is what makes the mechanism rather than
a guess. With `_prepare_functions` run directly on the `origin_of` program:

```
ov_plain:  main status=frame  returns_frame=R
ov_spec:   main status=word   returns_frame=None     <-- the misclassification
```

and on the `stash` program, both spellings agree that `stash` returns a frame
(`status=frame`), so the divergence in (1) is downstream of that and is purely
the block reservation.

## Why it matters

These are the LAST TWO cases in a file whose other ten pass, and they are the
two that assert a refusal. So the file's own coverage is: this construct is
checked, and on the specialized spelling the check does not fire and the program
is wrong.

The wider shape is that `f[T](...)` is not an exotic spelling on this path. It
is how a comptime-parameterized generic is CALLED, and `formal-frame-by-value`
and `formal-comptime-mlir` both landed constructs that produce them. Every
`isinstance(..., F.IdentExpr)` guard on a call's callee is a candidate, and this
tree has a list of them — `formal/model.py` lines around 10507, 11138, 11764,
11801, 12280, 12282, 12452, 12692, 12795 (plus 12907, which is the one fixed
here) and 11400/11448 in the diagnostic spellers, where the effect is a
message that names `?` instead of the function. The diagnostic ones are
cosmetic; the two that decide a REPRESENTATION are not, and those are the pair
above.

## The fix

Two guards, both already measured green on this tree and both reverted from my
branch because the area is claimed. Applying both makes the four measurements
above agree: `spec` answers **7** (was 0) and `ov_spec` is **refused with the
same message as `ov_plain`** (was building with exit 112).

1. `formal/model.py` `struct_returned_frame_sites`, in the `for node in
   iter_nodes(...)` loop — replace

   ```python
   if not isinstance(node, F.CallExpr) \
           or not isinstance(node.func, F.IdentExpr):
       continue
   st = returns_frame(node.func.name)
   ```

   with a `M.call_callee_name(node.func)` read (None ⇒ `continue`).

2. `formal/build.py` `_frame_return_status`, in the `return`-value walk —
   replace `isinstance(value, F.IdentExpr)` + `value.func.name` with
   `M.call_callee_name(value.func)`.

Both sites want the same comment, and the tree's own wording for it is at
`formal/build.py:2228` ("`model.call_callee_name`, and NOT `node.func.name`: a
comptime specialization `f[T](r)` names the same function `f` does, contributes
no call-time argument of its own, and so lands the frame on `f`'s parameter at
exactly the position the bare spelling would"). Note that the comment there
already explains WHY — which is the evidence that the two guards above are
oversights rather than decisions.

**Then**: with both applied, `refuse_a_specialized_parameter_returned` is still
red, and for a good reason worth reading before changing it.
`bugs/FORMAL_frame_receiver_handoff.md` §D4 and the "Lifting the return refusal
for a received holder is sound, and is not done here" paragraph after it say
the return refusal for a RECEIVED holder is deliberately still on, and that
lifting it needs §11's two channels to be refusals first. So that case's
expectation is correct as written and the fix above is what it is waiting for;
the second case (`refuse_a_value_only_callee_through_a_specialization`) will
then be refused with the SAME message as its bare twin and goes green, which is
the anti-rot working: both `expect=` markers report themselves as FAILURES the
moment this lands, and `formal-receiver-position` drops them in that commit.