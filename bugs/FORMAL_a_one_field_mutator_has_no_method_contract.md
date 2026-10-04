# A one-field struct's mutating method has no Lean contract, and the by-reference receiver changed what one would have to say

**Status: OPEN, and deliberately not fixed here.** The receiver convention it
depends on landed on `work/formal15-mutator-return-abi` (commit `11558f0d`); this
doc is the part of that work which is a project rather than a patch, written down
so the next reader does not have to re-derive it. Everything here is measured on
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
`bugs/FORMAL_binary_heap_mojo_after_the_len_value.md` §4's command shape:
`python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/c1.a64
.tmp/cand/c1.mojo`, then `_frame_methods(prog, code, info)` in a REPL with
`prog` the `SimpleNamespace(functions=ordered)` that `formal/build.py`:1642
builds. No lean needed — that is the point of this doc being checkable without
it.