# A one-field struct's mutating method has no Lean contract, and the by-reference receiver changed what one would have to say

**Status: OPEN, re-measured 2026-10-05, and again 2026-10-28 (§4.2), still
not fixed.** §4.1 records what the first re-measurement added — the smallest
program that fires the exclusion, the confirmed absence of any x86-64
counterpart, and the fact that the mutator is UNREACHABLE from the corpus
because a struct construction has no model (a different document's subject).
§4.2 records the second round: every claim above re-verified with the current
line numbers, the §4.1 box reproduced, and one new fact — since the stack-floor
guard took EVERY prologue of a program image (`e11f066d`, 2026-10-03),
`_frame_methods`' RET window ends at the guard's own `<fn>_sfN_ok`
continuation, so the mechanism is inert for every method in a program image
and the taker needs a step 0 before (1)–(3). Everything here is measured on
arm64; the x86-64 backend has no analogue of the machinery at all (see §4).

**Re-read 2026-10-03 (`work/formal18-1`): §5's step 1 names a function that no
longer exists under that name, and the part that remains is step 2 — which §3
already identifies as the part with no answer.** §0 below says which is which, so
a taker does not start with the contained change and find it already done.

---

## 0. What moved since this was written, and what did not

* **`_receiver_relative_accesses` is now `_frame_slot_accesses`**
  (`formal/arm64_proof_gen.py:8503`). Same function, same `{0: 0}` seed, same
  "None if a base register cannot be traced to the receiver". §5 step 1's
  description of it is otherwise still accurate, and step 1 is still not done:
  the seed is still `{0: 0}` and `LDR Xd, [X0]` at the callee's entry is still
  read as a *receiver-relative slot 0 load* rather than as "the receiver's
  value, which is a word".
* **`_frame_store_writes` moved** (`:8734`), from the `:7947` §5 cites. Same
  shape: one entry per `mem_write_u64` with the depth of its address below the
  entry `sp`, `None` for a frame store.
* **The exclusion is landed and is where §1 says it is** — `_frame_methods`
  skips a method whose owning struct is one field (`:8683`), by
  `model.struct_is_one_field`, read off `_owner_struct`. So §1's "net effect: a
  one-field mutator gets NO contract" is still the whole of the behaviour, and
  it is now a DECISION rather than an accident of the entry sequence.
* **§5 step 2 is untouched and is the whole of what is left.** The exit store
  needs the cell pointer to be a frame base for `Frame.Fits`, and nothing in the
  model ties a pointer the CALLER passed to a frame of known depth. Either the
  caller reserves the cell (making it a real frame in the caller's scratch, which
  `model.struct_returned_frame_sites` already does for a returned frame) or the
  model's claim stays about the callee alone — and §3's three numbered items say
  why the second is not a sentence that can be written.

**A fourth thing worth knowing, because it makes step 1 pointless on its own:**
`_frame_methods` only ever classified a method whose body is a SINGLE statement
(`kind = "set"` for one store, `kind = "get"` for one `return self.<f>`), and
§2 measures that against the two shapes this is about — `def pop(out self) -> Int`
with three statements, and `struct Pair` (two fields, so not this row) — and both
answer `None`. A one-field mutator that mutates AND returns a value is a
multi-statement body, so even with the cell load modelled it would not reach the
`set`/`get` classifier. Step 1 and the single-statement restriction have to be
lifted together, and the restriction is the same lift.

---

## 1. What the convention is now, and what the generator does about it

`formal/model.py`'s `receiver_writeback_name` gives a one-field struct's mutating
method a receiver that is **the address of a one-word cell in the caller's
frame**. The callee reads the word out of that cell at its entry (`LDR X19, [X0]`,
`mov R11, [RDI]` on x86-64) and writes it back through the pointer on every exit.
The return register carries only the declared return value.

`formal/arm64_proof_gen.py`'s `_frame_methods` generates a *frame-receiver
contract* for methods of this shape, and its premise is stated in the machine's
own terms: `x0` at entry is the receiver FRAME, field `k` is at `x0 + 8k`, and
the contract reasons about `Frame.FrameBelow` / `Frame.FrameFits` / the slot
table `Frame.SlotOf` requires. **That premise is false for a one-field mutator
under the new convention**: `x0` is a pointer to the value, not a frame of slots.

The generator now excludes such methods by name (`struct_is_one_field` on the
owning struct, read off `_owner_struct`), because before the exclusion they were
being dropped by an accident: the machine-confirmation step compares the
source's list of `self.<f>` accesses with the list of receiver-relative
`LDR`/`STR` the emitter produced, and for a one-field mutator the only
receiver-relative instruction is the prologue's load out of the cell, so the
lengths disagreed and the method was dropped. **A drop that depends on the entry
sequence is not a decision** — the entry sequence is exactly what the convention
change rewrote — so the question is now asked explicitly.

**Net effect: a one-field mutator gets NO contract, which is what it had before
the change.** Nothing regressed, and nothing was proved that was not.

## 2. Measured: the shape the contract machinery *would* classify

`_frame_methods` only ever classified a method whose body is a SINGLE statement —
`kind = "set"` for one store, `kind = "get"` for one `return self.<f>`. Measured
on both new shapes:

```
$ … _frame_methods(c1)   # def pop(out self) -> Int, three statements
None
$ … _frame_methods(two_field)   # struct Pair, def pop(mut self) -> Int
None
```

so the machinery never fired for a mutate-and-return method on either
representation, before or after.

## 3. What a contract would have to say, which is why it is a project

For a framed receiver the post-condition is about MEMORY: "the receiver's slot
`k` now holds the value passed in argument 1, and every other slot of the same
receiver is unchanged" (`_generate_frame_proof`'s own statement of it). For a
one-field mutator the post-condition is about a cell the callee was HANDED, and
three things have no answer here:

1. **The cell is the caller's storage, so the claim is about the CALLER's frame.**
   `ProofLib.Frame.SLOT` / `frameOffset` describe a frame that sits at the
   callee's entry `sp` and grows upward. A one-word cell is a one-SLOT frame, so
   the layout machinery could state the slot — but the *bound* is a pointer the
   caller passed, and nothing in the model ties that pointer to a frame of known
   depth, so `Frame.FrameFits` has nothing to be true of.
2. **The value crosses the boundary in a register at entry and leaves in a
   register at every exit.** The by-reference contract's constant propagation
   (`_receiver_relative_accesses`, arm64_proof_gen.py:7731) starts from
   `{0: 0}` — "x0 arrives as the receiver" — and follows register arithmetic. The
   new lowering's first instruction is `LDR X19, [X0]`, which is a LOAD of the
   whole word through the receiver rather than an offset from it, so the
   propagation has to learn a load-before-anything rule before it can say
   anything at all.
3. **There are as many exits as the body has returns, and each one repeats the
   store.** The frame contract's proof peels `mem_write_u64` effects off a
   straight-line block (`_frame_store_writes`, arm64_proof_gen.py:7947). A body
   with a conditional return has the store on two paths, so the peel has to hold
   for both — which is a real induction/case obligation, not a longer list.

## 4. The x86-64 half is a bigger gap and is not in this doc's scope

`formal/x86_64_proof_gen.py` has NO frame-receiver contract machinery at all —
`grep -n "frame_methods\|_self_accesses\|Frame\." formal/x86_64_proof_gen.py`
returns nothing. So on x86-64 a one-field mutator has no contract for the same
reason it never had one, and this convention change is invisible to it. Whoever
picks (1)–(3) up will be writing the arm64 half first and the x86-64 half after,
and the second is not a port.

## 4.1 Re-measured 2026-10-05: every claim above still holds, and one thing
##      is now measurable that was not before

This round was given the doc and could not land items (1)–(3) — they are a
`lib/ProofLib.lean` theorem plus a model change, and the brief forbids both a
`make gate` and a Lean run beyond the one test covering a change. **So this is
the doc with its measurements refreshed, not a fix**, and the honest thing to
record is what a re-measurement adds rather than to restate §1 as if it were
new. It adds three facts.

**The exclusion fires on the smallest possible program, and the receiver really
is a cell.** Asking the pass directly (no build, no Lean — the shape §5 step 3
gives), with `_owner_struct` attached the way `formal/build.py` publishes it:

```
wide_recv (TWO fields)   one_field=False  methods=['set_x', 'get_x', 'get_y']
  set_x   params=['self', 'v']  writeback=None
Box (ONE field)          one_field=True   methods=['set_v', 'get_v']
  set_v   params=['self', 'x']  writeback='self'
  get_v   params=['self']       writeback=None
```

`receiver_writeback_name` is non-None for the one-field MUTATOR and None for
every other method — so §1's premise is exactly right, and the exclusion in
`_frame_methods` is keyed on `struct_is_one_field`, which is the question §0 says
it is.

**The x86-64 half still has NO frame-receiver machinery**, so §4 stands as
written. `rg -n "frame_methods|_self_accesses|Frame\." formal/x86_64_proof_gen.py`
returns nothing, and the only two occurrences of the word "frame" in that file
are prose in a refusal message about `X86State.init` having no frame. Whatever
answers (1)–(3) on arm64 is a port, not a second implementation.

**The mutator is UNREACHABLE from the corpus, for a reason that is not this
document's.** A one-field struct with a mutating method does not reach
`_frame_methods` at all on this tree: the program is refused earlier, by the
model's missing domain for a struct CONSTRUCTION —

```
model: call to `Box` has no model in this image (an extern, or a function this
generator emits no `_go` for); refusing rather than inventing its return value
```

which is `FORMAL_wide_recv_model_has_no_domain_for_a_struct.md` /
`FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`'s subject and not
this one's. **So (1)–(3) cannot be verified end-to-end on this tree even after
they are written**: there is no program that both constructs a one-field struct
and gets far enough to want its mutator's contract. That is worth knowing before
starting, because it means (1)'s "unit test in `test_formal_call_proof_gen.py`"
has to be a test of `_frame_slot_accesses` on a HAND-BUILT word list rather than
of a generated proof — the same shape `TestBottomTestedRangeLoop` uses to read
the emitter's own block partition when the proof is not available.

**Not attempted, and why not simplifiable**: (1) alone is what §0 already
warns about — "step 1 and the single-statement restriction have to be lifted
together", because a mutator that mutates AND returns is a multi-statement body
and `_frame_methods` only classifies single-statement bodies — and (2) has no
answer, which §3 says at length. Landing (1) alone would change a slot map for
a contract nothing consumes.

## 4.2 Re-measured 2026-10-28: the mechanism the exclusion sits in front of
##      is now inert for every method in a program image

Same position as §4.1: items (1)–(3) are a `lib/ProofLib.lean` theorem plus a
model change, and the brief forbids both a `make gate` and a Lean run beyond
the one test covering a change. **This is the doc re-measured again, not a
fix**, so the honest thing to record is what this round adds rather than
restate §1 a third time. It adds one fact that changes the order of §5, and it
confirms every measurement above against the current tree.

**Every claim above still holds; the file has grown, so the addresses moved.**
`arm64_proof_gen.py` is roughly four thousand lines longer than the 10-05
round measured: the exclusion is now at `:12522` (was `:8683`),
`_frame_slot_accesses` at `:12342` with the seed still `{0: 0}` at `:12346`
(was `:8503`), and `_frame_store_writes` at `:12573` (was `:8734`); the sole
call site is `:11620`. The §4.1 box reproduces byte-identical — the corpus
`wide_recv` as the two-field control: `one_field=False`, every writeback
`None`; the one-field `Box`: `set_v writeback='self'`, `get_v None`. The
x86-64 half is still absent: the §4 grep returns nothing and the word "frame"
still occurs exactly twice, in prose. The §2 shapes still answer `None`. And
the §4.1 unreachability stands: proving `wide_recv` still refuses at the model
— "model: a struct field read has no value in the semantic model … refusing
rather than modelling it as 0" — before `_frame_methods` is ever reached.

**The new fact: `_frame_methods` cannot classify any method in a program
image, and the corpus's own two-field control is the measurement.** Since
`e11f066d` (2026-10-03, "every prologue of an image that has an entry carries
the stack-floor guard") — two days before the 10-05 round, whose probes were
all the multi-statement shapes of §2, so the split below could not have
surfaced in them — every function of a program image carries the guard:
`model.stack_floor_guarded_names(..., every_function=emit_startup)`
(`arm64_codegen.py:1017`), and the guard (`_emit_stack_floor_guard`, `:2000`)
emits `ADRP; LDR; ADD SP, #0; CMP; B.HS <fn>_sfN_ok` plus the trap at the
function's own label, with the frame, the body, and the RET at the
continuation label. `_frame_methods`'s RET gate takes the window
`[label(f), next label in address order)`, and the next label in address order
is the guard's own continuation — so the window holds the preamble and no RET,
`if not rets: continue` (`:12530`) drops the method, and the length-match
confirmation never runs:

```
$ _frame_methods on four built images (arm64, prove=False, one build)
c1 (ONE field, mutate-and-return, three statements)    None
pair (TWO fields, mutate-and-return, three statements) None
box (ONE field, single store, mut self)                None   ← the §4.1 box's shape
wide_recv.Point_set_x (TWO fields, single store)       None   ← the control
  window 0x19c..0x1f4: rets=0 branches=1;
  body at Point_set_x_sf2_ok (0x1f4..0x218): rets=1
```

The control is the point. `Point` is two fields, so the one-field exclusion
(`:12522`) does not fire; the body is one statement, so the `set` classifier
would accept it; it has no branch, so the branch gate would accept it. It is
the shape §1 says the machinery WOULD classify, and it still answers `None` —
dropped at the RET gate by the window split, a different cause than the one §1
records: "the length disagreed" described the pre-`e11f066d` entry sequence,
where a straight-line mutator's window was unsplit. Before that commit only a
cycle's or a branch's members were guarded in a program image; after it, the
preamble is in every window.

**The consequence for the taker: a step 0, before (1)–(3).** Landing (1) —
model the cell load in `_frame_slot_accesses` — or lifting the one-field
exclusion, buys nothing the mechanism can consume: the only path into
`_frame_slot_accesses` is past the RET gate, and no method in a program image
gets past it — including the one-field mutator itself, whose exclusion fires
at `:12522` before the gate, so lifting it (as (1)–(3) imply) lands on the
same drop the two-field control shows. The step 0 is to make `_frame_methods`
reason about the body at the `<fn>_sfN_ok` continuation instead of the
preamble: the window has to run from the continuation label (so the guard's
`B.HS` — one of the branch indices the leaf-shape gate rejects — is not
counted as "a branch: not the leaf shape"), and the `{0: 0}` seed has to say
what is true AT the continuation, where `x0` has already moved to its argument
home. It is checkable Lean-free, the same shape as §5 step 3: build the four
images above and ask `_frame_methods` directly, where the pass is
`wide_recv.Point_set_x` classifying (`kind="set"`) instead of answering `None`.

**Neither blocker is this doc's to land alone.** The model refusal that keeps
`wide_recv`'s proof from ever reaching `_frame_methods` is the other
document's subject, as §4.1 records; the window split is a codegen/proof-gen
fact measured here because it fixes the order. So §5's list is now: step 0
(make the window see the body through the guard preamble), then (1), then
(2), then (3) — with (2) still the part §3 says has no answer.

## 5. What to do next, in order

1. Make `_receiver_relative_accesses` model the cell load: `{0: 0}` becomes
   "`x0` is a pointer; the first `LDR Xd, [x0]` puts the receiver's value in
   `Xd`", and the slot map is `{0: 0}` for the ONE slot a one-field struct has.
   That alone makes `pop`'s own contract expressible; it is a contained change
   with a unit test in `test_formal_call_proof_gen.py`.
2. Then the exit store: extend `_frame_store_writes`' peel to "every exit emits
   `mem_write_u64` at the cell pointer", which needs the pointer to be a known
   frame base for `Frame.Fits`. That is the part with no answer, and it is
   where the research is: either the caller reserves the cell (making it a real
   frame in the caller's scratch, which `struct_returned_frame_sites` already
   does for a returned frame) or the model's claim stays about the callee alone.
3. Verify with `python3 test_formal_call_proof_gen.py` and the `formal` bucket
   (`python3 tools/suite.py proofs`), **not** with a hand-run `lean`: the
   generator's output is the artefact, and a hand-run proof is one file.

**Reproduce the measurement above** with
`bugs/formal/FORMAL_binary_heap_mojo_after_the_len_value.md` §4's command shape:
`python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/c1.a64
.tmp/cand/c1.mojo`, then `_frame_methods(prog, code, info)` in a REPL with
`prog` the `SimpleNamespace(functions=ordered)` that `formal/build.py`:1642
builds. No lean needed — that is the point of this doc being checkable without
it.