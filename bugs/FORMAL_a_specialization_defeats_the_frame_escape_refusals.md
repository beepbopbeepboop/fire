# A comptime SPECIALIZATION defeats both frame-escape refusals, and the bare spelling beside it is correct

## Status: the MECHANISM is fixed and measured, and on 2026-10-02 a THIRD
## representation guard and both diagnostic spellers were fixed with it; the
## three reds in the file remain, and each one's ACTUAL cause is identified, is
## not a specialization defect any more, and belongs to a lane that holds the
## claim

The two guards named below are in the tree. What they fixed is real and measured:
a specialized call and its bare twin are ONE call, and the two frame ends had
disagreed about that. What they do NOT do is make
`test_formal_receiver_position.py` green, and the reason is worth writing down
because the original filing's last paragraph predicted the opposite.

    $ python3 test_formal_receiver_position.py
    formal receiver position: PASS=11 FAIL=3

Re-measured 2026-10-02 on `work/formal8-1`, unchanged and for the same three
reasons: **PASS=13 FAIL=3**, and the three are the same three names
(`refuse_a_specialized_parameter_returned`,
`refuse_a_dotted_specialized_callee_names_it`,
`refuse_a_value_only_callee_through_a_specialization`) with the same messages.
Each belongs to a doc another lane holds — `FORMAL_frame_receiver_handoff.md`
(the first and the third) and `FORMAL_method_call_on_a_subscripted_receiver.md`
(the second) — so nothing here moved them, and the fourth item below is still
the integrator's.
      FAIL refuse_a_specialized_parameter_returned            (expected)
      FAIL refuse_a_dotted_specialized_callee_names_it        (not in the filing)
      FAIL refuse_a_value_only_callee_through_a_specialization (different message)

`formal-receiver-position` in `tools/suite.py` still carries an `expect=` for this
doc and forgives them; its reason string says "2 of 12" and the file now has 3 of
14, so the string is stale — **that edit is the integrator's, and this worker did
not touch `tools/suite.py`.** All three cases assert a refusal; none of the three
BINDS anything wrong any more.

---

## 1. What landed

Two `isinstance(..., F.IdentExpr)` guards replaced with `M.call_callee_name`, in
the two places the filing named, and each is now the tree's single recogniser for
"which function does this call name":

1. **`formal/model.py::struct_returned_frame_sites`** — the CALLER's half, which
   reserves the block a returned frame has to land in. It read
   `node.func.name`, so `stash[1](0, r)` reserved **no block**: the callee is the
   side that COPIES, it copied into the word it was handed — an ordinary argument
   register — and `main`'s `stash[1](0, r).a` read eight bytes from wherever that
   register pointed.
2. **`formal/build.py::_frame_return_status`** — the CALLEE's half, which
   classifies what a function gives back. A specialized call missed, so the
   `return` fell through to `words.append(...)` and the function was classified
   `_RETURN_WORD` — "no path returns a frame address". That one word is load
   bearing three ways: `returns_frame[fn.name]` is never set (which is (1) again
   from the other side), and `fn._image_returns_frame` has no entry for it, so an
   ENTRY function returning a frame got no `entry_frame_return_refusal` at all.

The fixpoint was never implicated, and it is what made the inconsistency visible:
`_frame_receivers` already read `M.call_callee_name(node.func)` for its own call
edges, under a comment naming "one recogniser, four readers" — and two of the
four were not using it. The holder fixpoint KNEW `stash` returned a frame while
the block-reserver did not, and the two answers were the two ends of a
use-after-free.

## 2. The measurement that says the mechanism is fixed

Each case measured on its OWN beside its bare-spelling twin, same source, arm64:

| program | bare spelling | specialized, before | specialized, after |
|---|---|---|---|
| `ask` returns `origin_of(r)`, `main` returns that | REFUSED | **built, exit 112** (a stack address read as an int) | REFUSED, **byte-identical message to the twin** |
| `stash` returns its `r` parameter, `main` reads `.a` | built | built, exit 0 (source says 7) | built — **the twin builds too** |
| `Box.run[1](0, r)`, `Box` a type name | — | refused (read-before-store, a symptom) | refused (read-before-store, a symptom) |

The `ask` row is the fix: the two architectures and the two spellings now agree,
which is the anti-rot the filing wanted. The `stash` row is why that is not the
whole story — see §3.

## 3. Why two reds remain, and they are not specialization defects

**`refuse_a_value_only_callee_through_a_specialization` expects the WRONG
refusal for this tree, and did before this change too.** Its needle is
`"which is lowered as an operation on a VALUE"` (the `origin_of` value-only-callee
refusal). Measured on both spellings of the same source on this tree:

```
build: main returns a frame address, and the returned-frame convention needs a
caller to reserve a block and pass its address — and main is this image's
ENTRY, so its caller is the C runtime, which passes no such word. …
```

Identical for `ask(0, r)` and `ask[1](0, r)`. So the entry-return refusal now runs
BEFORE the value-only-callee one, and it fires first for both spellings. Nothing
about the specialization is wrong any more; the expectation names a construct the
order of the checks no longer reaches. The check ORDER inside
`check_module_symbols` is `bugs/FORMAL_frame_receiver_handoff.md`'s subject and is
claimed (`bug:FORMAL_frame_receiver_handoff`, formal3-4-r2), so it is not moved
here. **The needle should not simply be rewritten to the entry-return message:
that would stop the case exercising the `origin_of` check at all, which is the
thing the case exists for. Whichever way it is settled, the fix is in the ORDER.**

**`refuse_a_specialized_parameter_returned` was never going to be fixed by these
two guards, and the filing says so.** Its needle is `"returned from a function
that did not create it"`, and the refusal for a RECEIVED holder that is returned
is deliberately still parked — `FORMAL_frame_receiver_handoff.md` §D4 records the
decision and names the two channels that have to become refusals first. Measured
here: `stash(0, r).a` and `stash[1](0, r).a` BOTH build, on both spellings, so the
specialization is not what distinguishes them and the case cannot be closed by a
recogniser. That is a use-after-free still open on this path, and it is the
handoff doc's, not this one's.

**`refuse_a_dotted_specialized_callee_names_it` was red before this change and is
red for a reason the filing did not name.** `Box.run[1](0, r)`, where `Box` is a
type name, is lifted by `formal/build.py::_rewrite_method_calls` to
`Box_run[1](Box, 0, r)` — the TYPE NAME prepended as the receiver argument — and
the read-before-store analysis then reports `Box`. So the construct the case wants
refused (a dotted specialization, which `call_callee_name` deliberately answers
`None` for) never reaches the check that would refuse it: the lift removes the
dotted spelling first. That is the fifth shape in
`bugs/FORMAL_method_call_on_a_subscripted_receiver.md` §"The NEXT blocker for
three of these files", which is filed, measured, and claimed
(`bug:FORMAL_method_call_on_a_subscripted_receiver`, formal3-5). Not moved here.

## 4. The wider list: a THIRD representation guard, and the two diagnostic
## spellers (all three fixed 2026-10-02)

Every `isinstance(..., F.IdentExpr)` guard on a call's callee is a candidate.
The two that decided a REPRESENTATION were the pair in §1. **A third was found,
and it was in the permissive direction — the expensive one for this document's
subject**, so it is worth more than a diagnostic:

`formal/model.py::_construction_arg_is_dead_blob` asked "is this construction
argument a container belonging to a CALLEE" and read the callee with its own
`isinstance(arg.func, F.IdentExpr)`. A subscript callee fell out, so:

```python
struct Bag2:
    var items: Int
    var n: Int

def mklist() -> List[Int]:
    var xs = [1, 2, 3]
    return xs

def main(n: Int) -> Int:
    var b = Bag2(mklist(), 5)      # REFUSED (constr_refuse_container_returned_by_a_callee)
    return b.n

def mklist[a: Int]() -> List[Int]: …
    var b = Bag2(mklist[1](), 5)  # BUILT, on both architectures
```

Same callee, same declared `-> List[Int]`, same bump-allocated region of the
callee's own reserved scratch — the only difference is the brackets, and the word
left in the slot points into reclaimed memory. That is premise (B1)'s hazard
reached by a spelling, which is this document's whole subject one function over.
It now reads `call_callee_name`, and `rets` is keyed by the function's name, so
the specialized spelling was always in the table under the bare one.

**The two diagnostic spellers are the same edit and they were as the docstring
said: cosmetic.** `_construction_arg_spelling` and the refusal beside it spelled
the callee `arg.func.name if isinstance(arg.func, F.IdentExpr) else "?"`, so
`Bag2(mklist[1](), 5)` was refused with a message saying `?()` — a callee that is
not in the reader's source. Both read `call_callee_name` now, and the message
says `mklist`. `call_callee_name`'s own `None` (a dotted name, a computed callee)
still becomes `?`, which is the honest answer for a callee this path cannot name —
so the two cases the `?` was FOR keep it.

Pinned by `test_formal_run.py`'s
`constr_refuse_a_container_returned_by_a_specialized_callee`, whose needle is the
**callee's name** and not the refusal's presence, so a fix that made the row
refuse for some other reason would not pass it.

**Still true after this:** the guards at what are now `formal/model.py` 11305
(the type-constructor arm of `kind_of`, deliberately a bare-name check),
17985 and 18770 (`struct_framed_construction_candidates`, where a specialized
CONSTRUCTOR `A[1]()` would also be missed) are unexamined for a representation
consequence. They are recorded here rather than fixed because no program in the
tree or the corpus reaches them, and a fix for a shape nothing writes is a
refusal waiting to be wrong.

## 5. Coverage cost of the fix, which is not zero and is not mine to measure

Both guards make the analysis strictly MORE refusing, which is the right direction
and is also the expensive one: a specialized call of a frame-returning function
now reserves a block it did not, and a specialized `return f[T](r)` is now
classified as a frame return. No corpus count is claimed here, because measuring
it is `tools/formal_sweep.py` and that is the integrator's job over this and every
other branch. The suites that cover the machinery are green:
`test_formal_returned_frame.py` 35/35, `test_formal_frame_return_overloads.py`
5/5, `test_formal_recursion_contract.py` OK, `test_formal_value_model.py` 19/19,
and `test_formal_run.py`'s five `ret_frame_*` rows.

## 6. What still has to happen

1. **Move the entry-return refusal after the value-only-callee refusal**, or
   decide that a frame address reaching `origin_of` is better reported as the
   entry problem it also is. Either way the needle in
   `refuse_a_value_only_callee_through_a_specialization` becomes true rather than
   edited. Handoff doc's write set.
2. **`_method_call_target` must not lift `Type.m[T](...)` with the type name as
   the receiver.** Either the dotted specialization is left for
   `multi_index_refusal_for` (which is what the case expects, and what
   `call_callee_name`'s `None` already implies), or `_receiverless_methods`
   learns to answer for a static method. `FORMAL_method_call_on_a_subscripted_receiver.md`'s.
3. **The received-holder return refusal** stays parked until the two channels it
   waits on are refusals. `FORMAL_frame_receiver_handoff.md`'s.
4. **`tools/suite.py`'s `expect=` reason** should be reworded to the 3-of-14 with
   the three causes. Integrator's file.
