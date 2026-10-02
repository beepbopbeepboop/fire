# FORMAL_method_call_on_a_subscripted_receiver: the largest remaining group of the receiver-position family, and the element type it needs

**Status: the DIAGNOSTIC half LANDED 2026-10-01; the CAPABILITY is OPEN and is
the whole of what is left.** A method call on a subscripted receiver
(`bs[0].get()`) no longer reaches the link audit with a message about where the
symbol should have come from — it is refused at the construct, naming the
missing fact (`formal/build.py`'s `_receiver_shape_refusal`, asked from
`_rewrite_method_calls`, the one recogniser that knows the lift did not happen).
Two cases in `test_formal_receiver_position.py` pin it on both architectures.

**What is still missing is the receiver-type predicate**, which is a larger piece
of work and NOT this file's: four sources of a receiver's type, one shared with
`model.frame_opaque_position_refusal` so the two cannot disagree about when a
receiver's type is known. The measured narrowing of what the refusal does and
does not cover is in "`Without a frame anywhere`" below — it was measured twice,
and both widenings cost working cases, so the shape of the remaining work is
narrower than the table above suggests: only row 1 and row 4 are unclaimed, and
row 1's first source (`var bs = [Box(), Box()]`) is statically obvious.

**The construct's owner is also not settled**: the original filing deferred the
fix to `construct:formal-value-model-gaps`, which is not among the active
claims; what the deferral got right is the SHAPE (one predicate, four sources,
shared with the refusal), not the assignment.

**The measurement, kept verbatim (the doc's own census, not re-run here).**
Filed by the `construct:receiver-position-family` worker, which measured the
sweep map's row 4 ("a receiver passed at argument position 0", 25 files) and
found that after the comptime-specialization case was lifted this group was the
biggest thing left in it: **17 of the 25 files are still refused by
`frame_opaque_position_refusal`'s method sentence**, and all 17 are the same
defect — the receiver's type is not established, so `_rewrite_method_calls`
cannot lift the call and there is no parameter list to read.

**The 17, grouped by what the receiver expression actually is** (measured by
instrumenting `_check_frame_escapes` and printing the callee object's node kind
at the refused site — the file list and the counts are from that run, not
inferred):

| the receiver is | files | the receiver's type is derivable from |
|---|---|---|
| a **subscript**, `messages[i].write_to(x)` | **4** — `debug_assert.mojo`, `io/file.mojo`, `logger/logger.mojo`, `tempfile/tempfile.mojo` | a `List[...]` element type; for `messages` it is a local list literal, statically obvious |
| a **call result**, `?.fields`, `?.enqueue_copy` | **2** — `complex/complex.mojo`, `gpu/host/device_context.mojo` | the callee's DECLARED return type |
| a **member of a frame**, `self.mojo_value.write_repr_to`, `Tensor.registry.append` | **2** — `python/bindings.mojo`, `test_llm/test_llm.py` | the declared type of the field `mojo_value` / of `Tensor.registry` |
| a **bare name**, `encoder.…`, `writer.…`, `w.…`, `value.…`, `Self.…`, `gfn.…`, `values.…` | **9** — `inline_array.mojo`, `collections/string/codepoint.mojo`, `ffi/cstring.mojo`, `format/tstring.mojo`, `hashlib/_ahash.mojo`, `memory/span.mojo`, `utils/static_tuple.mojo`, `gimple_codegen.py`, `io/io.mojo` | the declared or inferred type of that local/parameter. `values` is annotated only `List` and is **not** derivable at all |

Only the first two rows are the construct in this doc's title. All four rows need
the same predicate — "what struct does this expression name" — and that predicate
is the work; this doc is scoped to the first row because it is the one whose
diagnostic is measurably *wrong* rather than merely incomplete.

### The NEXT blocker for three of these files, which is a different construct again

`formal/model.py`'s `call_callee_name` (the change that resolved the bare-name
comptime specialization — see
`bugs/FORMAL_frame_receiver_handoff.md` §19) moved three files onto a
specialization of a **dotted** callee, which is a fifth shape and not this one:

| file | the callee now named in its refusal |
|---|---|
| `std/collections/bitset.mojo` | `Self._vectorize_apply[_union]` |
| `std/collections/string/format.mojo` | `Self.compile_entries_runtime[0]` |
| `std/builtin/string_literal.mojo` | `_FormatUtils.format_to_comptime[StaticString(Self())]` |

`call_callee_name` deliberately answers `None` for these: a dotted name is a
module-level function or an extern, and there is no parameter list for one here
either — which is the same answer arm64's `_specialization_of` gives by way of
`_member_slot_key`, so the two cannot drift.

It is a different rewrite and not a small one, because `Self` is a **type name,
not a receiver**: `Self.compile_entries_runtime[0](buf)` has no receiver
argument, so it is not `recv.m(x)` → `Recv_m(recv, x)` and `_rewrite_method_calls`
cannot be taught it by loosening its test — `_receiverless_methods` would have to
answer for a specialization of a static method. None of the three files can
pass today in any case (bitset imports `std.math` → `dtype.mojo`'s MLIR, format
imports `std.builtin.globals` → `builtin_slice.mojo`, string_literal imports
format), so the measured value of closing it is a better message on three files
and nothing else. Recorded here rather than built.

## What the construct is

`formal/build.py`'s `_rewrite_method_calls` lifts `recv.m(x)` to
`Recv_m(recv, x)` when **`recv` is an `IdentExpr`** and `m` is a bare method
name one struct in hand declares:

```python
if (isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr)
        and isinstance(node.func.obj, F.IdentExpr)):
```

A receiver that is anything but a bare name — `messages[i].write_to(x)`,
`vals[0].take(9)`, `bs[0].get()` — fails the second test, so the call is never
lifted, and the two backends then each do something different with the dotted
spelling.

## Measured, both shapes, arm64

### With a frame address in an ARGUMENT — the row-4 group

```
$ python3 fire.py build --formal --no-prove std/builtin/debug_assert.mojo
build: a _WriteBufferHeap receiver is passed to ?.write_to in argument position 0,
  and a method call on a value receiver is dispatched by NAME, …

$ grep -n write_to std/builtin/debug_assert.mojo
198:            messages[i].write_to(message)
```

`?.write_to` is `_member_chain` spelling `messages[i].write_to`: the receiver is
not a bare name, so there is no lifted callee name and
`model.frame_opaque_position_refusal` case 3 fires. **Here the refusal is sound
and the message is nearly true** — it IS a method call and it IS dispatched by
NAME — but the answer it gives ("a receiver whose type names the struct") is the
wrong next step, because the receiver here is not a frame at all: `messages` is
`List[String]` and the *argument* is the frame. The same shape reaches
`values._write_to(buffer, …)` in `std/io/io.mojo` (a **parameter** with no
element type either) and `encoder.encode_inline_array` in
`std/collections/inline_array.mojo`.

### Without a frame anywhere — and this one was worse than it looks

```
$ cat u1.mojo
struct Box:
    var k: Int
    def get(self) -> Int: return self.k
def main(n: Int) -> Int:
    var bs = [Box(), Box()]
    bs[0].k = 3
    return bs[0].get()

$ python3 fire.py build --formal --no-prove u1.mojo
build: u1.mojo: main: `bs[0].get(…)` cannot be lowered: dispatch here is BY NAME,
  so a method call is lifted to `Box_get(receiver, …)` from the name alone — and
  `bs[0]` is not a bare name, so there is no name to lift from. What is missing
  is the receiver's TYPE: this path has no inference that answers "which struct
  does `bs[0]` hold?", and dispatch is by name rather than by type, so the callee
  cannot be named. …
```

**PARTLY LANDED (2026-10-01): the LINK-ACCOUNTING half is now a construct
refusal, and the capability half below is still open.** `formal/build.py`'s
`_receiver_shape_refusal`, asked from `_rewrite_method_calls` — the one
recogniser that knows the lift did not happen — now refuses a **subscript**
receiver with this sentence instead of letting it reach the link audit, and
`model.receiver_shape_text` spells the receiver as the source spells it (it
printed `bs[IntLiteral]` before, because `member_chain_text` renders a subscript
as `…` and has no literal case). Two cases in
`test_formal_receiver_position.py` pin both, one for the refusal and one for the
spelling.

The paragraph below is kept because it is what made the change load-bearing, and
because the reason the audit caught it is still the reason this class of defect
is worse than a wrong number:

> **A LINK-ACCOUNTING diagnosis for a CODEGEN problem**, and it is caught only
> because the link audit refuses to ship an image with an unbound symbol. The
> symbol it names is the bare `get`: the dotted spelling `bs[0].get` is gone,
> and a reader is sent to the link line instead of to the receiver's type. If
> the method name had collided with an extern or a gimple runtime entry point,
> the image would have bound a real symbol and computed a wrong number.

**What did NOT change is the capability, and the narrowing of the refusal is
measured rather than chosen** — two widenings were tried and each cost working
cases:

* "any receiver that is not a bare name" refused **24 working cases** in
  `test_formal_run.py`. A `MemberExpr` receiver (`self.in1.total()`,
  `h.mojo_value.write_to(…)`) is a **field**, and the field's DECLARED type names
  the struct, so that case is answerable and is answered — several times over,
  by `_check_frame_escapes`, `frame_opaque_position_refusal` and the
  nested-frame refusals. That is row 3 of the table above, and it is NOT this
  construct.
* "a subscript or a call result" still pre-empted
  `frame_opaque_position_refusal`'s own sentence for `mk().take(r)` — the same
  fact (a receiver whose type is not established) reached through a path that
  already says so. That is row 2, and it too already has an answer.

So the refusal asks about a **SUBSCRIPT** and nothing else, which is this
document's title case and row 1. `?.fields` (row 2) is answered and
`self.mojo_value.write_repr_to` (row 3) is answered; `values._write_to(...)`
with a `vals: List` parameter and no element type (row 4) is the one shape that
still has nothing, and it is a `MemberExpr`-free bare name rather than a
subscript — `values` is a parameter, so `values._write_to` is not lifted and
reaches `frame_opaque_position_refusal` instead.

## Why this is not small, and what is needed

`_rewrite_method_calls` needs, for the receiver expression, **the struct whose
method `m` is**. It has `_method_owners`, which is keyed by bare method name
and is deliberately ambiguous when two structs declare it. The missing fact is
the receiver's type, and in this corpus it comes from three places that this path
does not connect:

1. a list literal of structs — `var bs = [Box(), Box()]`: the element type is
   the constructor's own declaration and is statically obvious;
2. a parameter annotated `List[Box]` — a declared parameter type, the same fact
   `FORMAL_method_param_field_access.md` wants;
3. a parameter annotated only `List` (`def drain(vals: List, …)` in the
   reproducer above) — **not derivable at all**, and the correct answer there is
   the one `FORMAL_wide_receiver_by_reference.md` reaches for a frame: the
   program is refused, and the refusal has to say "the receiver's element type is
   not declared" rather than "a method call is dispatched by NAME".

So the fix is one shared "what struct is this expression" predicate with the
same agree-or-refuse discipline as `model.struct_frame_slot_candidates`, read by
`_rewrite_method_calls`, with the four sources in the table above attached to it.
The first three rows are a line each once the predicate exists; the fourth row's
`values: List` is a genuine limit and needs its own message, the same way
`FORMAL_wide_receiver_by_reference.md` handles a frame whose struct is not
declared. The predicate must ALSO be the one `model.frame_opaque_position_refusal`
consults, or the two will disagree about when a receiver's type is known — which
is the same two-copies-of-one-decision defect this family keeps finding.

## Verification when it lands

**The refusal half is DONE and pinned** — the two cases
`refuse_a_method_call_on_a_subscripted_receiver` and
`refuse_a_subscripted_receiver_is_spelled_as_written` in
`test_formal_receiver_position.py`, on both architectures. What is left is the
capability, and its verification is the list below unchanged:

* the 4 subscript-receiver files: `std/builtin/debug_assert.mojo`,
  `std/io/file.mojo`, `std/logger/logger.mojo`, `std/tempfile/tempfile.mojo`.
  Re-sweep exactly those and report where each lands; the honest expectation is
  "moves to the next blocker", not "passes" (their imports fail too — see
  `FORMAL_sweep_work_map_2026-09-30.md` §3, where rows 2 and 3 both measured a
  ceiling of 0). **NOT DONE — a four-file sweep is the integrator's, not a light
  worker's.**
* `u1.mojo` above must **build and run**, not merely stop naming the link line:
  `bs[0].get()` has to return 3 on both architectures. This is the case the
  whole predicate exists for — `bs` is a list literal of `Box()`, so the element
  type is the constructor's own declaration and is statically obvious — and it
  is the FIRST thing to attempt, because if it works the predicate has one
  source and the other three rows are then a question of attaching it.
* a differential case next to the others in `test_formal_receiver_position.py`,
  comparing against CPython, plus a case for the undeclared-`List` parameter
  that must be refused with the new message. **The refusal half of the second
  is now covered** (a bare-name parameter reaches
  `frame_opaque_position_refusal`, which is already what row 4 needs and needs
  no new message); the differential case is the capability and is not done.

## Where the measurement lives

`bugs/FORMAL_frame_receiver_handoff.md` §18 (the grouped table of all 25) and
§20 (the sweep re-run). `construct:formal-value-model-gaps` is the neighbouring
claim this depends on.
