# FORMAL_wide_receiver_by_reference: the one-word value model, and the by-reference receiver that fits inside it

Split out of the wave-2 sweep work. This is the document the 53 refusals in
`tools/formal_sweep.py`'s arm64 run all name, and it says what the wall is, what
it costs to close, and — the part that matters — **the wall does not have to be
widened at all**.

**Status: the receiver is lowered BY REFERENCE, on both machines, and the
switch is ON.** Steps 1–6 below have all landed. Steps 1–3 were landed by wave
2; steps 4–6 by wave 3 (agent C2). The 53 repo findings and the 100 stdlib
findings that named this diagnostic now name **zero**; what they name instead is
a specific refusal (a field of a field, a receiver that escapes, a member this
path cannot place) or a host import that was previously masked. See
"What landed" at the end for the measured numbers and, more usefully, for the
five things that are still open.

Current arm64 baseline: 284 files, `PASS=80`, `codegen=54`,
`codegen coverage 80/134 = 59.7%`, and **0** of those name this diagnostic.

## Is the one-word value a true invariant?

**Yes, and the proof side's own account of it is correct.** Verified, not taken
on trust:

| claim | where | status |
|---|---|---|
| every arm64 register is one `UInt64`; there is no vector-of-words value | `lib/ProofLib.lean:1113` (`Arm64State`), all 31 `x<n> : UInt64` | confirmed |
| the same for x86-64 | `lib/X86.lean:14` (`X86State`), 16 `UInt64` GPRs | confirmed |
| `MojoExpr` is `int \| bool \| var \| unop \| binop \| call` — **no aggregate node exists at all** | `lib/ProofLib.lean:711` | confirmed |
| `MojoFunc.mk` has exactly one parameter | `lib/ProofLib.lean:727` | confirmed |
| `evalFunc … (arg : UInt64) : UInt64` | `lib/ProofLib.lean:808` | confirmed |
| `evalBodyEnv … (env : String → UInt64)` | `lib/ProofLib.lean:780` | confirmed |

So "a two-field struct has nothing to *be* as a value" is structural, not an
accident of the code generator, and a **by-value** widening really would have to
change the value model. Wave 1's further claim — *"a by-reference receiver means
`MojoFunc` grows a parameter and the environment stops being `UInt64`-valued"* —
is **false**, and it is false in the specific way that matters: `MojoFunc.mk`'s
one parameter is *already* `self`, and a by-reference receiver's word **is**
that parameter. Nothing grows. See "the flattened-receiver question" below for
why that matters more than it looks.

## The flattened-receiver question: can the ABI change be avoided?

**Yes. And the by-reference receiver *is* that answer — it is not an ABI change
at all.** This is the headline result, and it is the opposite of what wave 1
concluded.

A pointer is one word. Lowering `S.m(self, …)` so that the receiver word is the
*address* of an out-of-line frame of 8-byte slots, and `self.<f>` is
`LDR Xt, [Xself, #8k]` / `STR Xt, [Xself, #8k]`, changes:

| | by-value widening | flatten the fields into parameters | **by-reference receiver** |
|---|---|---|---|
| a value becomes two words | **yes** | no | **no** |
| `Arm64State` | **must change** | no | **no** |
| `MojoExpr` | **new aggregate node** | no | new *field-read* node, or none (§ below) |
| `MojoFunc` arity | no | **1 → n** | **no** |
| `evalFunc`'s type | no | **`UInt64 → UInt64` → `List UInt64 → UInt64`** | **no** |
| `evalBodyEnv`'s env type | no | **`String → UInt64` → `String → UInt64 → UInt64`** | **no** |
| the ~40 per-node lemmas under `evalFunc_eq_mojo_all` (`:961`) | no | **all re-instantiated at a new env type** | **untouched** |
| the `arm64_step` / `X86` certificate layer | **must change** | no | **no** |
| `Refine.Post` / `contract_sound` / `runProg` | no | no | **no** — already `UInt64 → UInt64`, and the receiver word *is* the argument |

The by-reference design is the only one of the three that leaves the value
model, `MojoFunc`, `evalFunc`, `evalBodyEnv` and the machine model **completely
untouched**. Its cost lands in two other places, both additive (§ "what it
costs").

### Why flattening does *not* work, with the counterexample

Flattening looks free because the *machine* can obviously pass three words in
`x0..x2`. It is free on the machine and it does not survive contact with the
proof layer, for a reason that has nothing to do with struct width:

**The formal proof layer is a one-argument proof layer, and it already is one
for ordinary multi-argument functions.** `formal/arm64_proof_gen.py`'s
`_gen_go` (`:878`) builds the source model from `fn.params[0][0]` and nothing
else; `_expr_go` (`:369`) maps *any* other variable to the literal `(0 :
UInt64)`. A two-argument function therefore already produces a model that
silently drops its second parameter. Measured, not assumed:

```python
# /tmp/b2/two_arg.mojo
def two_arg(n, k):
    return n + k
```

```
$ python3 fire.py /tmp/b2/two_arg.mojo build --formal
```

generates, and `lean` accepts:

```lean
def two_arg_go (n : UInt64) : UInt64 :=
  (n + (0 : UInt64))                       -- `k` is 0

def ast : MojoFunc := MojoFunc.mk "two_arg" "n"
  ([MojoStmt.return ((MojoExpr.binop "+" (MojoExpr.var "n") (MojoExpr.var "k")))])

theorem two_arg_compiles_correctly_universal (n : UInt64) … :
  (match runProg two_arg_prog n with | some s => s.x0 = mojo n | none => False)
```

`eval_eq_mojo` typechecks because both sides drop `k`, and the end-to-end
theorem typechecks because `Arm64State.init` zeroes `x1`. The statement is true
and it is about the wrong program: it is the theorem for `two_arg(n, 0)`.

So a flattened receiver does not avoid the source-model change — it *is* the
source-model change, and it is the more expensive direction:

* `MojoFunc.mk` gains a parameter list, so `evalFunc` becomes
  `(args : List UInt64) → UInt64` and `evalBodyEnv`'s env becomes
  `String → UInt64 → UInt64`; every one of the ~40 per-node lemmas under
  `evalFunc_eq_mojo_all` is re-instantiated at the new env type, and the
  `X86`/`arm64_step` certificate layer is untouched only by luck.
* A method `S.m(self, name)` flattened to `S_m(self, _set, _list, name)` is a
  **four**-argument function, and `_gen_go` would bind `_set` to `0` — the
  receiver's fields read as zero, silently, in a proof that typechecks.

By contrast a by-reference receiver is **one** argument on the machine and one
argument in the model, so it lands inside the regime the proof layer already
handles, and its fields live in `mem`, which `Arm64State` already has
(`lib/ProofLib.lean:1149`, `mem : Nat → UInt8`).

### Is the banding right?

Wave 1's three bands (`formal/model.py`'s `struct_width_cost`, `:1051`) are
right, and the by-reference design collapses two of the three into one:

| band | example | by-reference verdict |
|---|---|---|
| **2 fields** | `_OrderedNames` (`_set, _list`) | **cheapest possible case.** A 2-slot frame, 16 bytes. One `slotOf` table, one frame, no special case anywhere: `SLOT` is a parameter, so 3, 4, 5, 6 fields are the same code with a bigger `n`. |
| **3–6** | `Resolver._find` (4), `ModuleLoader` (3), `InvariantChecker` (4), `_GenexpDesugarer.walk_list` (5), `_Parser.parse` (5), `_FuncFacts.disqualify` (3) | **not a separate project.** A 6-slot frame is 48 bytes, still one `STP`/`LDP` pair's worth of stack. Wave 1's own diagnostic calls this "that same ABI change with a layout to invent"; the layout is `base + 8k` and needs inventing exactly once. |
| **dozens** | `GimpleGen` (263) | **genuinely different, and for a different reason than wave 1 gave.** Not "a register allocator that can spill an aggregate" — a 263-slot frame is 2104 bytes of *stack*, which the existing frame machinery already handles, and it is still one pointer in a register. What is genuinely different is that `FrameBelow` (the frame must sit below `sp`) starts to constrain the *caller's* frame size, and `envToFrame` (below) is a fold over 263 names, so the write-back is no longer free. Still not an ABI problem. |

**The banding is right about the conclusion and wrong about the reason for the
third band.** Worth correcting in `struct_width_cost` when its owner is free.

## The design, concretely

### Frame layout

Slot `k` at `base + 8*k`. No padding, no alignment games, no field reordering.
The entire per-struct cost is a `Nat` — the slot index of each field — which is
the list `formal/model.py`'s `struct_field_names` already returns, paired with
indices. Landed as `Frame.SLOT`, `Frame.frameOffset`, `Frame.frameBytes`,
`Frame.frameAddr`, `Frame.frameRead`, `Frame.frameWrite` in
`lib/ProofLib.lean`.

**The layout is not free of address wraparound**, and this is the one real
constraint: `base + 8*k` is a `UInt64`, so two different slots can share an
address if a frame runs off the top of the address space. Every lemma therefore
carries a `FrameFits` premise rather than assuming the arithmetic cannot wrap —
the same discipline `mem_read_after_write_u64_high_nw` and `u64_slot_nowrap`
already follow for the stack.

### Calling convention

`self` arrives in the argument register(s) as a **pointer to the frame**, not as
the struct's contents. `S()` becomes: reserve `8*slots` bytes in the frame,
store the literal defaults, and leave the frame's address as the value. A field
read is `LDR Xt, [Xn, #8k]`; a field write is `STR Xt, [Xn, #8k]`. Nothing
about the value model changes, because nothing is passed *by value* that was not
one word before.

The frame goes **below** the callee's own `sp` — carved out of the frame the
*caller* builds — and not into the red zone above `sp`. That is forced, not
stylistic: `FrameOk`'s window is indexed by `sp + j` for `j ≥ 0`, so a frame
above `sp` would sit inside the region a method is *required* to write. Below
`sp` is provably outside the window, which is exactly
`Frame.frameWrite_read_above_sp`.

### Recursion

Nothing changes. `Refine.Post`, `contract_sound` and `contract_sound_tree` are
already stated over `mojo : UInt64 → UInt64` with `st.x0 = arg`, and a receiver
word *is* the argument. The recursion still descends on whatever the method
recurs on.

What does change is the callee's postcondition: a mutating method violates
`FrameOk`'s "the caller's slots are preserved" clause by construction. The
repair is additive — keep `FrameOk` for the 40 proofs that use it, add
`FrameOk_except`, which carves the receiver frame out of the window — and
`FrameOk_except_zero` proves the old predicate is *recovered* (not replaced)
when the frame is empty or above `sp`.

## What it costs, and exactly which Lean definitions change, in order

Every step below is additive and the tree typechecks at each one. This is the
order; steps 1–3 are **landed**, 4–6 are not.

### Step 0 — LANDED, and it gates everything else

`lib/ProofLib.lean`'s `arm64_step` did not model the two
single-register-memory instruction forms the emitter actually emits:

| opcode | architecture | what `arm64_step` did |
|---|---|---|
| `0xF9400000` | `LDR Xt, [Xn, #imm]` (unsigned-offset 64-bit **load**) | labelled `STR Xt, [SP, #-imm]!`; implemented as a pre-index **store**: `sp := sp - imm*8`, **one byte** written at `[sp - imm*8]`, `Xt` untouched |
| `0xF9000000` | `STR Xt, [Xn, #imm]` | base register hardwired to `s.sp`, whatever `Rn` said |

`formal/arm64.py`'s `encode_ldr_xt_xn_imm` (`:37`) emits `0xF9400000` and
`encode_str_xt_xn_imm` (`:336`) emits `0xF9000000`, and the codegen uses both
with non-`SP` bases for every heap access (`formal/arm64_codegen.py:811, 1307,
1344, 1555, 1571, 1627, 1664, 2186` and the `str` sites at `834, 1710, 1716,
2226`). `LDR` and `STR` are separated by bit 22 (`opc`), so the two cases are
different instructions and the model had them the wrong way round.

Machine-checked in `ProofLib` itself (`decide` over a concrete state whose
`x5 ≠ sp`):

```
LDR X0, [X5, #8]  modelled as  sp := sp - 8      -- a load never moves sp
LDR X0, [X5, #8]  modelled as  x0 := x0         -- …and never writes a register
STR X0, [X5, #8]  modelled as  mem[sp+8] := x0  -- …at SP, not at X5
```

All three are now false and their negations are proved (`by decide`, in the
landing commit's verification). `work_step_ldr_uoff` and `work_step_str_uoff`
are the corrected statements; `work_step_ldr_pre` and `work_step_str_off` are
kept as aliases because `formal/arm64_proof_gen.py`'s `_WORK_STEP` table
(`:1578`, `:1589`) dispatches on those names. **Renaming the generator's two
table entries and deleting the aliases is a one-line follow-up that owns
`formal/arm64_proof_gen.py`; it is not in my lane and is not done.**

**Blast radius measured, not assumed:** `0xF9400000` and `0xF9000000` appear in
**zero** of the 43 `formal/examples/*_proof.lean` images, so no existing proof
was asserting anything about the mis-modelled form. That is *why* the 40-example
suite was green throughout: the form is reachable only from a program that
touches memory through a non-`SP` base, and the examples are register-only. The
x86-64 model was never affected — `X86.x86_mem_addr` (`lib/X86.lean:227`)
computes a real effective address including base + index + displacement, and
`x86_rm_read`/`x86_rm_write` use it, so `[reg+disp]` was already right there.
That asymmetry is why this was an arm64-only hole and why it is the one wall
rather than two.

**The proof generator has the identical bug, and that is how the hole stayed
hidden.** `formal/arm64_proof_gen.py`'s `_step_rhs_generic` writes the
per-instruction statement *itself*, from its own model of the emitter, and for
these three cases it hardwires `s.sp` exactly as `arm64_step` did:

| idx | opcode | `_step_rhs_generic` emits | correct |
|---|---|---|---|
| 18 | `0xF9400000` | `sp := sp - I12*8`, one **byte** at `[sp - I12*8]`, `Xt` untouched | `Xt := mem64[Xn + I12*8]`, nothing else moves |
| 19 | `0xB9000000` | `mem_read_u64 s.mem s.sp.toNat`, then `sp := sp + I12*8` | base is `Rn`; and `0xB9000000` is a **W**-register post-index load (4 bytes), not `Xt` (8) |
| 31 | `0xF9000000` | `mem_write_u64 s.mem (s.sp + I12*8)` | base is `Rn` |

The giveaway that this is a plain bug and not a convention: **three cases in the
same function get it right.** `_BASE` at `formal/arm64_proof_gen.py:1419` is
`if Rn = 31 then s.sp else arm64_reg Rn s` — the encoded base, correctly — and
`_ADDR7` (`:1428`) builds on it, so the STP (idx 21) and LDP (idx 32) cases
honour `Rn` while the three above do not.

So generator and model agreed with each other and both disagreed with the
hardware. That is the worst combination this project has: a proof that
typechecks and asserts something false about the machine.

**Measured, both ways.** A list-indexing program (`lst2.mojo`: `items[1] + n`,
which forces `LDR X0, [X9, #8]`) is provable in neither library, and the
per-instruction statements are where the two diverge. Against the pre-change
library (`git show HEAD:lib/ProofLib.lean`, built into a scratch root) the
proof has 11 errors, all of them downstream `unsolved goals` /
`maxRecDepth` — the per-instruction `Type mismatch`es are *absent*, because
`lst2_sr_13`'s statement

```lean
arm64_step s lst2_code = some
  { s with mem := mem_write_u64 s.mem (s.sp + UInt64.ofNat 0).toNat (arm64_reg 10 s) }
```

matched the old `work_step_str_off` exactly. Against the corrected library the
same proof has 19 errors, the extra 8 being `Type mismatch` at exactly those
statements (`:4275` … `:4419`).

**This is the intended trade and it needs saying out loud: the fix converts a
silently-wrong green into a loudly-wrong red on any program that touches memory
through a non-`SP` base.** The 43-example suite does not, so it is unaffected
(measured: `PASS=40 KNOWN-GAP=3 FAIL=0` before and after, byte-identical
outputs). The mirror fix in the generator is small and belongs to whoever owns
`formal/arm64_proof_gen.py`:

* `_step_rhs_generic` idx 18 → `some (arm64_set_reg RD s (mem_read_u64 s.mem ((arm64_reg RN s + UInt64.ofNat (I12*8)).toNat)))`
* idx 31 → `some { s with mem := mem_write_u64 s.mem ((arm64_reg RN s + UInt64.ofNat (I12*8)).toNat) (arm64_reg RD s) }`
* idx 19 → the encoded base, and a 4-byte read (it is the `W`-form post-index load)
* `_WORK_STEP` (`:1578`, `:1589`) → `work_step_ldr_uoff` / `work_step_str_uoff`, then delete the two aliases from `lib/ProofLib.lean`
* `_STEP_CONDS` comments (`:1151` says "18 STR" for a load opcode; `:1164` says "31 STR unsigned offset") — cosmetic but they are how the next reader finds this

**This step is not optional.** The by-reference receiver's central instruction
is `LDR/STR [Xself, #8k]`, which is precisely the mis-modelled form. Landing
the frame layer on top of the old model would have been proving a fiction.

### Step 1 — LANDED: the frame, as data plus the algebra a proof needs

`namespace Frame` in `lib/ProofLib.lean`, 24 declarations, all proved, no
`sorry`:

* `SLOT`, `Frame`, `frameOffset`, `frameBytes`, `frameAddr`, `frameRead`,
  `frameWrite`, `FrameFits`, `FrameBelow`
* `FrameFits.mono`, `frameOffset_le_bytes`, `frameOffset_mono`,
  `frameBytes_mono`, `frameOffset_step`, `frameAddr_eq`, `frameAddr_mono`,
  `frameAddr_step`, `frameAddr_disjoint`
* `frameRead_frameWrite_same` — a write to slot `k` is seen by a read of slot
  `k`. This is what makes a receiver frame mutable at all without a second
  value shape appearing anywhere.
* `frameRead_frameWrite_ne` — a write to slot `k` is invisible to a read of a
  different slot. This is what makes the slots independent, and therefore what
  makes a per-field source environment a sound model of the frame.
* `frameWrite_byte_untouched`, `frameWrite_read_outside`
* **`frameWrite_read_above_sp`** — the callee-contract lemma: a write into a
  frame lying entirely below `sp` leaves the caller's window above `sp` exactly
  as it was. `frameWrites_read_above_sp` is the fold version, in the shape the
  generator's write-back produces.
* `frameToEnv` / `envToFrame` — the bridges between memory and the
  `String → UInt64` field environment. `envToFrame` is a fold over a *finite*
  name list, because `mem` is a function and the names a method does not
  mention have to be left alone explicitly; the generator knows which those are.
* `SlotOf`, `envToFrame_frameToEnv_single`, `envToFrame_frameToEnv_cases`,
  `envToFrame_frameToEnv` — the write-back round-trips. Proved as a **two-clause**
  induction (in `names` → the assigned value; not in `names` → the value that
  was already there) because either clause alone is not inductive: the head case
  of "in `names`" is not a base case, since the fold continues into `rest` and
  has to be shown not to disturb the head's own slot.

### Step 2 — LANDED: the callee contract that lets a method write its receiver

`lib/Refine.lean`, section 4b, 4 declarations, all proved:

* `FrameOk_except` — `FrameOk`'s thirteen conjuncts verbatim, with the memory
  clause weakened only by `¬ Frame.FrameBelow base st.sp n`.
* `not_below_of_above` — a frame that is empty, or above `sp`, is not below
  `sp`.
* **`FrameOk_except_zero`** — `FrameOk_except st st' base 0 ↔ FrameOk st st'`.
  The lemma that makes step 2 safe rather than a second, weaker version of the
  same claim: the old predicate is *recovered*, not replaced.
* `frameWrites_window_preserved` — the generic per-block step, threading `mem`
  in the same left-fold shape the emitter's stores have, so it composes with the
  existing per-block value flow rather than needing a new reasoning mode.

`FrameOk` itself is **not** touched, and `Post` / `contract_sound` /
`contract_sound_tree` are not touched.

### Step 3 — LANDED: the source semantics of a by-reference method

`namespace MF` in `lib/ProofLib.lean`, all proved, no `sorry`. The design point
is that it costs almost nothing:

`MojoExpr.var` already reads a *name* out of a *name environment*. A field is a
name that lives in a *different* environment. So a method is `evalExpr` over
**one** environment that merges locals and fields, with `self.<f>` lowered to a
`var` whose name is tagged — and every per-node lemma `evalExpr_*` applies
verbatim.

* `fieldTag`, `MFExpr` (the ordinary forms plus one `field`), `MFStmt` (plus
  one `assignField`), `liftMF`, `liftMFStmt`/`liftMFStmts` (mutual).
* `mfEnv` — the merge. It is a **scan over the frame's field-name list**, not a
  prefix test on the name, and that is deliberate: a prefix test needs
  `("self." ++ n).drop 5 = n`, which is neither `rfl` nor cheap in this
  toolchain, whereas injectivity of the tag — the only `String` fact the scan
  needs — is `simp [h]`. The field list is one the generator already has.
* `fieldTag_inj`, `mfEnv_fieldTag`, `mfEnv_not_fieldTag`
* `evalMFExpr_field` — `self.<n>` in a method means the receiver's current field
  `n`, and nothing else.
* `evalMFBody`, `mfFieldsOut`, `evalMethod`
* `mfEnvAfterLocal`, `mfEnvAfter`, `mfEnvAfter_at`, `mfEnvAfter_at_local`,
  `evalMFBody_assignField_env`, `evalMFBody_assignLocal_env` — a field
  assignment *is* the environment update `fun z => if z == fieldTag n then v
  else mfEnv …`, and this is the bridge to `Frame.envToFrame`.

Plus one additive lemma next to the existing `evalBody_assign`:
`evalBodyEnv_assign` (`:934`) — the `.2` projection of the assignment clause,
which is what a method's semantics needs, since a method's whole point is the
fields it leaves behind.

`MojoExpr`, `MojoStmt`, `MojoFunc`, `evalExpr`, `evalBodyEnv` and `evalFunc` are
**all untouched.**

### Step 4 — LANDED: `evalExpr_congr` and `evalBodyEnv_congr`

Both are in `lib/ProofLib.lean`'s closing section, "Congruence under a merged
environment", and both are proved. `MojoExpr`, `MojoStmt`, `MojoFunc`,
`evalExpr`, `evalBodyEnv` and `evalFunc` are still untouched.

`evalExpr_congr` is one structural induction over `MojoExpr`. The twenty-odd
`binop` patterns are the whole of the work and the reason it is written the way
it is: `evalExpr`'s operator dispatch is a 21-way literal `match` on a
`String`, and **neither `rw` nor `simp` descends into a stuck `match`** — both
treat it as opaque — so the only way to get at it is the same `by_cases` chain
`evalExpr_binop` already uses. (`rw [evalExpr]` does not help: it unfolds the
*definition* and stops there, still one `match` too many.) `evalExpr_congr` is
the reason this section is worth having: a field read and a local read share
one environment, and without congruence nothing can be said about what a method
computes from the two.

`evalBodyEnv_congr` cannot be a plain structural induction on the statement
list, and the reason is worth recording because it is not obvious: **an `if`'s
branch body is not shorter than the list that contains it**, so `List.length`
does not descend and a proof about nested bodies has nothing to recurse on.
It is a well-founded recursion on a mutual `stmtBodySize`/`stmtsSize`
instead — two new `private def`s, present only to give that recursion a
measure. The two places `evalBodyEnv` threads an environment forward are the
`if` and the assignment clause, and each reduces to "recurse under an
environment that agrees with the original where the original was unchanged":
`ifUpdate_congr` for the first, the recursion on a strict sublist for the
second.

`MF.fieldTag_inj'`, `MF.evalMFExpr_other_field` and `MF.evalMFBody_congr` sit
on top: the source-level statement that a field assignment leaves every other
field alone, and that a method's result and the fields it left behind depend
only on the merged environment.

### Step 5 — LANDED: the codegen

The four items below, as specified. The layout and the per-struct decision are
in `formal/model.py` (`wide_receiver_by_reference`, `struct_is_framed`,
`struct_frame_slots`, `struct_frame_slot`, `struct_frame_bytes`,
`struct_frame_defaults`, `struct_constructor_sites`), the frame-holder analysis
and the escape refusals in `formal/build.py` (`_frame_receivers` and its
helpers), and the emission in both backends.

1. `S()` for a receiver of *n* fields (`_emit_struct_constructor`, currently
   `formal/arm64_codegen.py:3321`, which refuses `struct_field_count > 1`):
   reserve `8*n` bytes, store each literal default, and yield the frame address.
   The literal-default rule (`struct_default_word`) carries over unchanged.
2. `self.<f>` read/write: `MemberExpr` on a receiver whose base is the `self`
   register, with `f`'s slot from a `slotOf` table. Both instruction forms
   already have encoders (`encode_ldr_xt_xn_imm`, `encode_str_xt_xn_imm`) and,
   as of step 0, a correct model.
3. `formal/build.py`'s `_rewrite_method_calls` (`:1085`), which already rewrites
   `recv.m(a)` → `Struct_m(recv, a)`: **this needs no change at all** under the
   by-reference design. The receiver is passed as the address it already is.
   That is the design's main practical dividend and it is worth stating
   explicitly, because it is the function the refusal currently lives in.
4. `formal/model.py`: the refusal at `struct_field_count > 1` became a switch,
   `MOJO_FORMAL_WIDE_RECEIVER`, **on by default**. The two settings differ ONLY
   for a struct of more than one derived field, and for such a struct "off" is
   a refusal — so turning it on can only turn a refusal into a build and never
   change the meaning of a program that already built. The full formal suite is
   byte-identical with it off, and `test_formal_run.py`'s `WIDE_OFF_CASES` are
   the same sources with it off, because "the switch is off" is a claim about
   behaviour and a claim with no test behind it is a claim nobody has checked.

**Where the design's prediction held, and where it did not.** `_rewrite_method_calls`
needed nothing, exactly as predicted — it passes the receiver as the address it
already was, and `MojoFunc`'s one parameter is still that address. What the
design got wrong is the PLACEMENT, and it is worth being precise about because
the argument for it is elegant and the conclusion does not follow:

> the frame goes below the callee's own `sp`, because a frame above `sp` would
> sit inside the region a method is *required* to write

A caller-allocated frame cannot be below the callee's `sp`. The callee's `sp`
IS the caller's `sp` (the frame is restored on return), so a region the caller
owns below its own `sp` is a region the callee also sees below its own `sp` —
and two frames allocated by the same function would then be at the same
addresses, which is the aliasing this whole design exists to prevent. There is
no placement that is both caller-allocated and below the callee's `sp`.

So the frames go at the **bottom of the same reserved scratch the list/dict
blobs use**, and the blob cursor starts above them
(`_emit_function`, both backends). That placement is correct for the reason the
design actually needed, which the doc states as a side effect rather than as
the argument: a callee's whole frame begins below the caller's `sp`, so a
callee's frames *and* a callee's blobs are both below every frame the CALLER
owns, and a blob made in the same function cannot land on a frame. So a method
cannot overwrite the receiver it was handed, and `self.items.append(1)` inside
a method cannot scribble on the receiver it is appending to.

The consequence for the proof is the one `Refine.FrameOk_except` already
anticipates: a frame at `sp + k` is INSIDE `FrameOk`'s window (`sp + j` for
`j >= 0`), so a method that writes its receiver does **not** satisfy `FrameOk`,
and the callee contract for a method is `FrameOk_except` — which is the
predicate step 2 landed for exactly this. `FrameOk_except_zero` recovers
`FrameOk` at zero slots, and `Frame.frameWrite_read_above_sp`/`FrameBelow`
remain the tool for a frame that IS below `sp`; they are simply not what the
emitter produces today.

The second thing the design did not have: **a frame belongs to the function
that created it, and a receiver that escapes is a wrong answer waiting to
happen.** Returned, stored in a container, or handed to a callee this module
does not compile, the address outlives the bytes. Every one of those is a
refusal naming the construct (`formal/build.py`'s `_check_frame_escapes`),
because the alternative is a program that builds, runs, and returns a number
the source never wrote. The same discipline is why a `MemberExpr` whose root is
a receiver of unknown struct, whose field is not in that struct's field list,
or which reads a field of a field, is refused by name rather than read as a
word: the frame layout is `base + 8*k` and `k` comes from the struct's own
field list, and a field this path cannot place has no `k`.

### Step 6 — NOT DONE, and it is NOT the codegen's file

`formal/arm64_proof_gen.py` would need to emit a method's `MFStmt`/`MFExpr`
instead of `MojoStmt`/`MojoExpr`, plus the per-block value flow for frame
accesses, plus `FrameOk_except` in place of `FrameOk` in the method's contract.
Its `_gen_go` (`:878`) is the place where the one-argument model is assumed.

**Measured, so the next person does not have to rediscover it:** a two-field
struct with methods does not reach the generator's *frame* problem at all. It
stops two steps earlier, in `_stmts_go_t` (`formal/arm64_proof_gen.py:608`),
which handles `Return`, `Pass`, `ExprStmt`, `Assign`, `AugAssign` and `IfStmt`
and raises on everything else — so `var p = Point()` (a `VarDecl`) fails, and
without the `var` a zero-argument constructor fails one line lower, in
`_expr_go_t`, which reads `e.args[0]` unconditionally. Both are one-line fixes
in that file and neither is about the receiver. What is genuinely open after
them is the receiver's own per-block value flow, which is this step.

## The 14 remaining receivers, by band

| receiver | fields | file |
|---|---|---|
| `_OrderedNames` | 2 | `mojo/middle/boundnames.py` |
| `_FuncFacts.disqualify` | 3 | `formal/types.py` |
| `ModuleLoader.can_resolve_module_path` | 3 | `module_loader.py` |
| `ModuleSpecGenerator.generate` | 3 | `module_spec_gen.py` |
| `Resolver._find` | 4 | `imports.py` |
| `InvariantChecker.*` | 4 | `detect_real_type_errors.py` |
| `_GenexpDesugarer.walk_list` | 5 | `fire_compiler.py` |
| `_Parser.parse` | 5 | `regex_compile.py` |
| `TypeLattice.join` | 3 (all class constants) | `mojo/middle/types.py` |
| `Point(x, y)` / `StringRef` | 2 / opaque | `test_struct.mojo`, `bootstrap_test_classes.mojo`, `stdlib_core.mojo` |

`TypeLattice.join` is listed by wave 1 as having "instance state" but its three
fields are `_SIGNED`, `_UNSIGNED`, `_FLOAT` — class-level constants, which is
the *other* agent's discrimination, not this one's. Under the by-reference
design it would be a 3-slot frame anyway, so the question does not have to be
settled to make progress on it.

## Wave 3 (C5): the frame's next two limits

Step 5 landed and the receiver-width wall went from 100 findings to 0, and what
replaced it was a set of refusals that did not agree with each other about what
was wrong. This section is the census of those, what was closed, and — the part
that matters more than the counts — **three programs that built, ran, and
returned numbers the source never wrote**, all of them in the code step 5
landed.

### The taxonomy of "a field of a field"

The refusal said one thing and the corpus had six things in it, so the shape has
to be sorted before anything can be designed. Measured over the 132 files the
old diagnostic named (61 of them have a construct of their own; the other 71
are refused only because an import failed), by what decides the case:

| sub-shape | sites | files | decided by |
|---|---|---|---|
| `h.f.m(…)`, `m` a method of no struct in this file | 1803 | 38 | `model.value_method_refusal` — **not the frame** |
| `h.m(…)`, `m` a method of no struct here (depth 1) | 399→154 | 18 | same |
| `h.f.g` in a **value** position | 147 | 20 | the frame layout — the only true field-of-a-field |
| receiver handed to a **builtin** (`len`, `origin_of`, `isinstance`, `String`) | 97 | 22 | the callee wants a value |
| receiver handed to a function **this module does not compile** | 82 | 16 | the call cannot bind at all |
| receiver in a non-first argument position | 81 | 14 | the position's meaning |
| `h.f.m(…)`, `m` a method of a framed struct declared here | 268 | 9 | the slot would have to hold a frame address |
| `h.f.append/get/…` (a builtin on the value) | 48 | 16 | the capacity bargain, or the value kind |
| receiver **returned** | 30 | 9 | the frame dies with its creator |
| `h.f.g` value position, `g` not a field | 8 | 3 | the field set |
| receiver in a **container** | 6 | 2 | no layout for an address |
| receiver **stored in a frame's field** | 2 | 2 | the frame outlives its creator |

The headline is the first row: **the largest group in the entire sweep was not
a frame problem at all.** `self.asm.emit(…)` is a method call on a value — the
word in slot `k` is the value, the callee gets that word, and what the backend
can lower is the whole question. The frame pass was refusing it as a layout
problem, which is not merely imprecise: with the refusal lifted and nothing
downstream taught about frame slots, the chain reaches `_emit_expr` as a value,
misses every slot table, and reads a scratch register on arm64 / `0` on x86-64.
A wrong answer, and a *divergent* one.

So the shape that was closed is not a new lowering. It is **POSITION**: a
MemberExpr that is a call's callee object is a method call on a value, and a
MemberExpr anywhere else is a field read. `_call_receivers` in
`formal/build.py` is that distinction, and `_is_value_receiver` in both backends
now answers True for a frame slot, so the diagnostic that finally fires is
`model.value_method_refusal`'s — which names the method and what the backend
lowers, and which is the correct owner of those findings.

### What closed, and what it is worth

* **Two positions, not two lowerings.** 2200 sites moved from a frame-layout
  refusal to the diagnostic that describes them. No file changed verdict; the
  point is that the next reader of a finding is now sent to the right place.
* **One shape now genuinely builds and runs**: a value method on a value read
  out of a frame, where the value's kind is established in the same function.
  `byref_value_method_on_a_frame_slot` — a string method on a frame slot — went
  from refused to `7` on both architectures. It needed one thing beyond the
  position split, and the thing is in the docstring of x86-64's
  `_is_value_receiver`'s caller: **x86-64 did not record a frame slot's value
  kind on a store, and arm64 did.** So arm64 built the program and x86-64
  refused it — the two backends disagreeing about one source file, which is the
  one thing the pair is not allowed to do. Fixed in x86-64's MemberExpr store
  path (`_note_binding` on the slot key).
* **The strings the old messages dropped.** The field-of-a-field refusal
  printed `base.member`, so `self.asm.emit` read as though the source said
  `self.emit` and the reader went looking for a field of the wrong name.
  `_member_chain` spells the chain; `byref_refuse_field_of_field_names_the_chain`
  pins it.

### Three silently-wrong programs, all in step 5's own code

These are the reason the section exists. Each one built, ran, and printed a
number the source never wrote; none of them crashed.

**1. One name, two frame layouts.** `_constructor_bindings` returned
`{name: struct}` and the last binding won. `x = A()` on one path and `x = B()`
on another is ordinary Python; on this path both are frame addresses, of
different frames, with different layouts.

```python
# /tmp/c5t/ambig5.mojo — A: v@0, pad@1   B: pad@0, v@1
def pick(c: int) -> int:
    var x = A()
    x.v = 5
    if c > 0:
        x = B()
    return x.v * 10 + x.pad
```

```
$ python3 fire.py build --formal --no-prove -o ambig5.out ambig5.mojo
Built: ambig5.out  [arm64/macho]
$ ./ambig5.out
61 99            # the source says 50 99
```

Both `FrameFits`/`frameRead_frameWrite_ne` and the non-aliasing theorems are
about *addresses*; none of them can see this, because the bug is that one name
was given one struct's slot table and then used for two. The fix is
`model.struct_frame_slot_candidates` and the rule is **agree or refuse**: if
every candidate layout puts the field at the same index, one index serves both
and the access is emitted once; if they disagree, or one candidate has no such
field, there is no `k` and the refusal names which candidate wanted which slot.
The candidate set is a *set* for the whole pipeline — constructor bindings,
copies, and the first-parameter fixpoint all union rather than overwrite.

The Lean side of it is `Frame.frame_frames_no_alias_neqn` /
`frame_instances_no_alias_neqn`: two objects whose structs have **different
field counts** still do not alias, which is what makes "the layouts agree on
this field's slot" sufficient rather than a coincidence. `frame_frames_no_alias`
states the same-slot-count case, which a program gets for free.

Note what the agree-or-refuse rule is *not* allowed to do: read the agreed
index anyway when the candidate that lacks the field is the one on the path. The
second disagreement shape — "some candidate has the field and some do not" — is
not visible to a `len(slots) > 1` test, and it is the common one. That was
caught by running a program, not by reading the rule: an early version of the
predicate fired on the *agreeing* case too, because two candidates that agree
on slot 0 also produce a one-element slot set.

**2. A method dispatched by name onto the wrong receiver.**
`_rewrite_method_calls` turns `recv.m(x)` into `S_m(recv, x)` from the method
name alone, because `recv.m(x)` carries no type. That is fine while the
receiver's type is not used for anything. It stops being fine the moment the
receiver is a frame, because the callee writes `self.<field>` at `base + 8k`
for **its own** struct's layout.

```python
struct Helper:  a, b     |  fn go(self, v): self.a = v; return self.a
struct Owner:   h, t     |  fn run(self):   return self.go(5)
o.run(); o.h   ->  5, 5        # the source says 5, 0
```

`self.a = v` inside `Helper_go` writes slot 0 of the frame it was handed, which
is `Owner`'s `h`. Python leaves `h` alone. Nothing crashes, because both
structs' first fields are integers and the write lands somewhere perfectly
legal — which is what makes it worth a refusal rather than a note.
`_check_method_receiver_types` reads the REWRITTEN call (`S_m` whose first
argument is a holder of a struct that is not `S`), because the holder set is
only known after the fixpoint, which is after the rewrite. `byref_refuse_method_on_another_struct`.

**3. A frame address parked in a field.** `o.inner = i` looks like an ordinary
assignment. It is the one channel out of a function the escape check did not
cover: the slot belongs to the frame of whatever function built `o`, the value
written names a frame belonging to whatever function built `i`, and the two
lifetimes are independent. Return and container were already refused; this is
the same hole one level down, which is the direction the whole design leaks in.
`byref_refuse_frame_address_in_field`.

### The receiver-passed-to-an-uncompiled-callee question: a sound refusal

**The answer is no, it is not fixable, and the reason the old message gave was
not the one operating.** The single diagnostic said *"which this module does not
compile, so the callee cannot know the frame's layout"*, and that sentence is
wrong for the larger of the two groups it covered. It splits:

| callee | sites | files | what is actually wrong |
|---|---|---|---|
| a builtin (`len`, `origin_of`, `isinstance`, `String`, `Pointer`) | 97 | 22 | It **is** compiled, as an operation on a VALUE. `len(x)` reads a length out of the object; a frame address is a pointer to a frame of slots. A wrong *category* of argument, not a missing layout — and wrong even if the callee were handed the whole struct. |
| a C library entry point (`fcntl`, `ioctl`, `write`, …) | (in the 97) | | Takes the struct's BYTES by value. The frame holds fields at `base + 8k`, which is not the struct's own layout, so the callee reads the wrong words. |
| a function this unit does not compile | 82 | 16 | The call has **nowhere to go at all**: the image contains one file's functions, so the symbol is unbound before the receiver's type is a question. Even with the callee's body in hand, a frame address is only meaningful to code compiled against the same field list. |

`formal/model.py`'s `frame_receiver_escape_refusal` is the one place the three
answers live, so both architectures say the same thing. The uncompiled-callee
branch keeps the old wording — it is accurate for that branch, and
`byref_refuse_invisible_callee` still matches on it.

"Is a frame address enough?" — the question the brief poses — is worth its own
answer, because it is the tempting one. **A frame address IS enough for a
callee compiled against the same field list.** The address is absolute, a
callee's `sp` is below its caller's, and `Frame.frame_frames_no_alias` says the
callee's own frames and blobs are below every frame the caller owns, so a
method can be handed the address of an object its caller made and neither can
scribble on the other. That is the whole by-reference design, and it is why
passing a receiver to a *compiled* method needs nothing special. What does not
follow is that a frame address can be handed to something that did not compile
against that layout: the word is meaningful only to code that agrees what slot 3
is, and an extern has no such agreement to give. The one thing that would make
it work — making the callee's field list available — is a *binding* problem
(this image has one file's symbols), not a representation one, and it is
`formal/imports.py`'s and the dylib export rule's, not this file's.

### The aliasing evidence for the new shapes

`byref_two_instances_no_alias` is C2's and it is still green, unchanged. Added
for the shapes this section introduces:

* `byref_two_widths_no_alias` — two objects of **different widths** (`A` 2
  fields, `B` 3), the shared field names at the same slots, each of the four
  reads checked by name so a regression says *which* object moved. This is
  `Frame.frame_instances_no_alias_neqn` written as a program.
* `byref_one_name_two_widths_agree` — the same property reached through one
  name rebound to two widths, which is the path the candidate-set rule has to
  keep working, and which returns 502 on the `A` path and 0 on the `B` path so
  a program that read one object as the other returns the wrong one of the two.
* `Frame.frameRead_in_range` — the byte-range fact the first of those consumes:
  a value read out of a frame consults exactly one slot's 8 bytes, and that
  range lies inside the frame it belongs to. A pure read obviously leaves its
  own frame alone; what is new, and what a value used as a receiver relies on,
  is that a value read out of `b1` provably did not come from `b2` and a write
  to `b2` provably cannot change it. The callee is handed a `UInt64` and no
  other reference, so the only way it could write a frame is by being handed
  one — and the range fact says the word it was handed is not a frame base.

Six of the eight new cases fail on the pre-change tree (`PASS=93 FAIL=6` in a
tree carrying only the new tests and the old backend). The two that do not are
`byref_two_widths_no_alias` and `byref_one_name_two_widths_agree`, and they
cannot: they are the *positive* guard for the agree-or-refuse rule, which the
old tree also got right — it got right by picking one layout and being lucky
that the two agreed. They are here so that the rule has a test on the side
where it must keep working, and they are reported as passing pre-change rather
than dressed up as demonstrations.

## What landed, and what is still not done

**Landed, and reachable from a program:**

* the frame layout and its algebra (`Frame`, step 1), the callee contract
  (`Refine.FrameOk_except`, step 2), the source semantics (`MF`, step 3), the
  congruence lemmas (step 4), the codegen on both machines and the switch
  (step 5);
* `Frame.frame_frames_no_alias` and `Frame.frame_instances_no_alias` — **two
  instances of one struct do not alias**, proved, no `sorry`, machine-checked
  by every `make check-formal*` because they live in `lib/ProofLib.lean` and
  `formal/lean.py`'s `ensure_library` builds it. Together with
  `Frame.SlotOf` (distinct field names, distinct slots) and the allocator's
  disjointness, that is the whole of the property at the level where it is a
  theorem rather than a hope;
* `MF.evalMFExpr_other_field` — a field assignment leaves every other field
  alone, stated about the evaluator's result and not only about the environment;
* `test_formal_run.py`: 7 positive cases (the cheapest width, the two-instance
  case, a copy, a twelve-field dispatch, a field that is a local/constant/value,
  an augmented field assignment, a receiver through a plain function) and 4
  `refuse:` cases (returned, stored in a container, field of a field, invisible
  callee) — 15 of them fail on the pre-change tree, which is how they were
  chosen.

**Not done:**

* **No method is proved END TO END by the generator.** Steps 1–5 are landed and
  a method builds, runs and computes the right answer on both machines, and
  the frame and source-semantics halves are proved — but the two are joined by
  `formal/arm64_proof_gen.py`, which is not this change's file, and which stops
  before the receiver is even reached (see step 6 above for the measured
  reason). `make check-formal` is `PASS=40 KNOWN-GAP=3 FAIL=0` and
  `make check-formal-x86` is `43/0`, unchanged, because no example in
  `formal/examples/` exercises a wide receiver.
* **No loop contract for a method.** `while` is in `MFStmt` and lowers, but a
  method whose loop writes its receiver needs the loop contract re-derived
  against `FrameOk_except`, and the existing `while_dec_exit_contract` /
  `while_lt_exit_contract` are written against `FrameOk`'s window. The emitted
  code is correct without it (the frame is below the callee's own blobs, and
  the per-block value flow for a frame access is a load or a store to a fixed
  `sp + 8k`), which is a fact about the emitter and not a proof.
* **The `work_step_*` aliases are still misnamed** pending the `_WORK_STEP`
  rename.
* **The x86-64 side of the model was not re-audited** for the same class of
  mis-modelled memory form. `X86.x86_mem_addr` looks correct on inspection and
  the 43-example model test passes against the hardware, but arm64 is the proof
  that "the examples don't emit it" is not the same as "it is right", and the
  x86-64 examples are the weaker evidence of the two.
* **A receiver that is recognised by its BINDING, not inferred.** Which local
  holds a frame address comes from the constructor it was bound from, a copy,
  a method receiver, or a visible callee's first parameter — enumerated, not
  inferred, and run to a fixpoint across the module. The hole that leaves is
  the one `_one_word_field_map` has always had on the one-word path: a name
  that receives a frame address through a channel this walk does not model. The
  channels it does NOT model are the ones a frame cannot survive anyway
  (return, container, invisible callee), and each of those is a refusal, so the
  residual is a hole in the *recognition*, not a way for a frame to dangle.
* **The `dozens` band is not designed**, only landed. A 263-field frame is
  2104 bytes of the same reserved scratch, allocated and addressed identically
  to a 2-field one, and `GimpleGen` is refused for a named reason rather than
  for its width. What is unresolved is the caller's frame budget: the scratch is
  a fixed `_SCRATCH`, and a function that both recurses and creates wide frames
  has no stated bound relating the two.

## Verification

All commands from the repo root. Wave 3 (C2) is the row that changed; the
earlier rows are what was already true when it started.

| command | before (wave 2) | after (wave 3) |
|---|---|---|
| `LEAN_PATH=lib python3 -c "… ensure_library(…)"` | `RESULT OK` | `RESULT OK`; `sorry` in `lib/` still 2 + 1, all pre-existing `DylibExport` stubs |
| `make check-formal` | `PASS=40 KNOWN-GAP=3 FAIL=0` | **unchanged** |
| `make check-formal-x86` | `PASS=43 KNOWN-GAP=0 FAIL=0` | **unchanged** |
| `make check-formal-run` | `PASS=77 FAIL=0` | `PASS=91 FAIL=0` (14 new cases) |
| `make check-formal-imports` | `PASS=17 FAIL=0` | `PASS=18 FAIL=0` |
| `make check-formal-dylib` | `PASS=9 FAIL=0` | `PASS=9 FAIL=0` |
| `python3 formal/x86_64_model_test.py` | `agree 43 WRONG 0` | `agree 43 WRONG 0 NO-RUN 0 build-fail 0` |
| `python3 test_suite.py` | `43 passed, 0 failed` | `43 passed, 0 failed` |
| `python3 tools/formal_sweep.py --no-stdlib -j 12 -t 60` | 284 files, `PASS=79`, 55 findings naming this diagnostic, coverage 79/141 | 284 files, `PASS=80`, **0** naming it, coverage 80/134 |
| `python3 tools/formal_sweep.py --no-stdlib --arch x86-64 -j 12 -t 60` | 284 files, `PASS=78`, 0 differing | 284 files, `PASS=79`, **0** naming it, and **0 of 204 shared files differ from arm64 in their detail text** |
| `python3 tools/formal_sweep.py -t 300 -j 12` | 578 files, `PASS=106`, 100 findings naming this diagnostic, coverage 106/221 | 578 files, `PASS=105`, **0** naming it, coverage 105/416 |
| `python3 tools/formal_sweep.py --arch x86-64 -t 300 -j 12` | — | 578 files, `PASS=103`, **0** naming it, 6 of 473 shared files differ from arm64 (all pre-existing x86 gaps: `ComptimeForStmt`, multi-index subscript, `EllipsisLiteral`, `SubscriptExpr` call target — none of them a frame) |

**The coverage DENOMINATOR moved (141 → 134, 221 → 416) and the file-level
class labels moved with it, and neither is this change.** `tools/formal_sweep.py`
is being reworked concurrently to split `codegen` from `codegen/dependency` and
to replace the `unknown` class with named ones; the old baseline had 204
`unknown` in the stdlib run and the new one has none. Compare by `detail` text,
which is what the table above does: **55 → 0** repo findings and **100 → 0**
stdlib findings name this diagnostic, and no file that was `PASS` is not.

**The stdlib's largest real group was never this wall.** The ~95 files refused
on `ptr.value()` / `self.write_to()` are refused by a DIFFERENT diagnostic —
`ptr.value() is a method call on a value, and this backend lowers only append,
close, write and the string methods …` — which is about a method on a plain
*value* receiver (`Pointer`), not about a multi-field struct. 49 of them moved
only in the sense that the import CHAIN now names a different failing link
(`builtin_slice.mojo`, whose receiver WAS a wide one); the `env.mojo: ptr.value()`
refusal is unchanged and still the first thing wrong with `env.mojo`. That
group is `model.BUILTIN_VALUE_METHODS`, and closing it is a different piece of
work.

### Wave 3 (C5) verification

Judged by the `detail` text and not the class, because the class labels are C1's
and are moving underneath this. The per-file table is in the agent report; the
numbers that matter are here.

| command | before this change | after |
|---|---|---|
| `LEAN_PATH=lib python3 -c "… ensure_library(…)"` | `RESULT OK` | `RESULT OK`; `sorry` in `lib/` still 2 + 1, all pre-existing `DylibExport` stubs |
| `make check-formal` | `PASS=40 KNOWN-GAP=3 FAIL=0` | **unchanged** |
| `make check-formal-x86` | `PASS=43 KNOWN-GAP=0 FAIL=0` | **unchanged** |
| `make check-formal-run` | `PASS=91 FAIL=0` | `PASS=111 FAIL=0` (8 added by C5, the rest by the other wave-3 agents) |
| `make check-formal-dylib` | `PASS=9 FAIL=0` | `PASS=11 FAIL=0` (C3's cases) |
| `make check-formal-imports` | `PASS=18 FAIL=0` | `PASS=24 FAIL=0` (C3's cases) |
| `python3 test_suite.py` | `43 passed, 0 failed` | `43 passed, 0 failed` |
| `python3 test_formal_sweep.py` | `55 tests, OK` | `55 tests, OK` |
| `python3 formal/x86_64_model_test.py` | `agree 43 WRONG 0` | `agree 43 WRONG 0 NO-RUN 0 build-fail 0` |
| `tools/formal_sweep.py --no-stdlib -j 12 -t 300` | 284 files, `PASS=80`, coverage 80/134 = 59.7% | 284 files, `PASS=80`, coverage 80/131 = 61.1% |
| `tools/formal_sweep.py --no-stdlib --arch x86-64` | 284 files, `PASS=79`, 0 of 204 differing | 284 files, `PASS=79`, **0 of 204 shared files differ from arm64** |
| `tools/formal_sweep.py -j 12 -t 300` | 578 files, `PASS=105`, coverage 105/416 = 25.2% | 578 files, `PASS=105`, coverage 105/414 = 25.4% |
| `tools/formal_sweep.py --arch x86-64 -j 12 -t 300` | 578 files, `PASS=103`, 6 of 473 differing | 578 files, `PASS=103`, 92 of 473 differing — **all 92 are the same two pre-existing x86 gaps** (`ComptimeIfStmt` 34, `SubscriptExpr` call target 56, plus one `ComptimeForStmt` and one `EllipsisLiteral`), none a frame finding |

**No file newly passes and no file that passed stops passing**, in either scope
and on either architecture: 0 newly `PASS`, 0 lost `PASS`. That is the honest
headline for this group, and it is worth being blunt about why: **nothing in
these ~130 files became compilable, because almost none of them was ever
blocked by the frame layout.** 63 of them were blocked by a value method the
backend does not lower, 37 by a hand-off the callee cannot accept, 42 by a slot
that would have to hold a frame address whose lifetime nothing here can
establish, and the rest by an import. The work moved the *diagnosis*, and it
removed three programs that were answering wrongly.

**The coverage denominator moved 134 → 131 and 416 → 414, and that is not this
change making anything answerable.** 12 files moved `codegen` →
`not-answerable/host-import` because a frame refusal that used to fire FIRST was
masking a CPython host import further down the pipeline, and the import check is
the accurate diagnosis: a file that imports `ast` is out of this backend's reach
whatever its codegen says. It moves those files out of the measured denominator
without making them answerable, which is the one direction of denominator drift
that flatters a number, so it is called out here rather than left in the table.

**Two fixes outside the frame code, both forced, both reported rather than
hidden.** `ValueKinds.kind_of` read `TernaryExpr.body`/`.orelse`, and
`F.TernaryExpr` (`fire_compiler.py:309`) has `then_val`/`else_val` and neither of
those — so the line raised `AttributeError` on every ternary it was ever handed.
It was unreachable until the frame pass stopped refusing a handful of files
ahead of the codegen, and then 48 of them landed in `backend-crash`, which is a
worse verdict than the refusal that had been hiding it. One line, in a region
that belongs to the value-method agent. And x86-64's frame-slot STORE path did
not record the slot's value kind while arm64's did, so arm64 built a program
x86-64 refused — fixed in x86-64, and the asymmetry is the reason the check is
written down rather than assumed.

## Still open after wave 3 (C5)

* **No file in this group compiles, and the next concrete step is not in the
  frame layer.** The largest bucket (42 files, `self._data.clear()`,
  `self._data.unsafe_get(i)`, `self._rng.step()`) is a method on a value read
  out of a slot, and it needs the *value's kind* — is slot 3 a `List`? a
  pointer? a `Deque`? — which is `model.ValueKinds` and the field
  annotations, and which is the value-method agent's work, not this file's. What
  this change guarantees is that the question is now asked in the right place
  and that the frame layer is not what stands in the way.
* **A field's declared type is still not used.** `struct B: var _rng: SomeStruct`
  would let `self._rng.step()` resolve to a nested frame, and `var p: Pointer`
  would let `self.p.value` be a load at a computed offset. Both are one lookup
  away and neither is a change to the frame algebra — but reading a type off a
  declaration is inference this path deliberately does not do, and doing it
  halfway (a declared type that the value does not honour) is the silently-wrong
  direction. It wants the same agree-or-refuse discipline as
  `struct_frame_slot_candidates`: a type is used only when every binding of the
  name agrees with it.
* **`S()` does not run `__init__`.** Measured while building the census: a
  two-field struct with a list field, `__init__` assigning it, and a method
  reading `len(self.items)` — segfaults, because the slot holds 0 and `__init__`
  never ran. Every slot's value is the class-level *default*, not what the
  constructor of the language would assign. That is C2's documented design and
  it is the single largest reason the stdlib's container-shaped structs cannot
  work here, and it is a separate piece of work from the frame layout.
* **A blob stored in a field has the frame's lifetime problem one level down.**
  Safe today only because no field can be given a non-literal default and
  `__init__` does not run, so a slot can never hold a list built by another
  function. The moment either of those changes, `self.items.append(x)` in a
  method appends into a blob in reclaimed stack. The refusal is in place for the
  append; the *reason* it cannot be lifted is not yet written down as a premise
  anywhere.
* **The `byref_one_name_two_widths_agree` case passes on the pre-change tree**,
  and cannot do otherwise — it is the guard for the rule, not a demonstration of
  it. Six of C5's eight new cases fail pre-change; the two that do not are named
  here so the ratio is not read as eight.

## Wave 4 (D2): a field's DECLARED type, used only when every binding agrees

The entry above named this as the next step and named it precisely: *"A field's
declared type is still not used … use a declared type only when every binding of
the name agrees with it — the same agree-or-refuse discipline as
`struct_frame_slot_candidates`."* This section is that step, and the first
thing worth saying about it is that **the rule has four answers, not two**,
which is the whole content of C5's "doing it halfway is the silently-wrong
direction".

### The rule, and where it lives

`formal/model.py`, a new section headed "A field's DECLARED type: agree, or
refuse", next to the slot-agreement check it copies:

| what | where |
|---|---|
| `_strip_type_args`, `annotation_base_name` | reduce `List[Self.T]` → `List`, `unsafe Pointer[Int32]` → `Pointer`, `ref[Inner]` → `Inner`, and `ref[self.items]` → **None** |
| `struct_field_declared_type` | one reading of one field's declaration; `(None, why)` when there is no single answer |
| `field_type_rows` | the evidence table a refusal quotes, computed once and shared with the decision |
| **`frame_field_type_candidates`** | **the agree-or-refuse check**, the exact analogue of `struct_frame_slot_candidates` one level in |
| `field_type_is_value` | the other answer, as its own accessor so no caller re-derives it |
| **`field_type_disagreement`** | **its own diagnostic** — every candidate spelled, agreeing ones included |
| `struct_fields_written_outside_init` | the third condition on placement, and the one a first version left out |
| `struct_nested_frame_fields` | the PLACEMENT list: `[(field, slot, struct)]` |
| `struct_frame_block_bytes` | a block is the object's frame PLUS its nested frames' |
| `struct_constructor_sites` | extended to `(struct, offset, nested)`, `nested` carrying each child's own absolute offset |

`formal/build.py` consumes it in `_frame_receivers` through one function,
**`_typed_nested_frame`**, which is where the four answers live:

| answer | meaning | what happens |
|---|---|---|
| `_NOT_TYPED` | the candidates do not agree | refused, and the refusal now spells WHICH candidate wanted what |
| `None` | they agree, and the type is **not** a framed struct of this module | the word is a plain VALUE: no frame diagnostic, the value path owns it |
| `_REASSIGNED` | they agree, it **is** a framed struct, and an executed method WRITES the field | refused, naming the type and saying whose frame the slot holds is unknown |
| a `StructDef` | they agree, it is a framed struct, and **nothing writes the field** | a NESTED FRAME, placed in the outer object's own block |

**The tie-break that keeps it in the safe direction** is the shape of the
function, not a line inside it: `frame_field_type_candidates` returns `None` for
*every* doubtful case — no annotation, two declarations that disagree, two
candidates naming different types, a base that is not one of this module's
framed structs — and returns a `StructDef` only on unanimity. **An absent
answer is the answer.** There is no path by which a doubtful annotation reaches
the emitter, and `struct_nested_frame_fields` re-checks unanimity from scratch
rather than trusting the caller's verdict, so the two decisions cannot drift.

The `_REASSIGNED` answer is the one that took a measurement. Without it, a
written field was treated as the constructor's frame and every write to it was
refused — sound about the frame, useless about the program. Measured on the
stdlib sweep: **164 files changed verdict**, every one because ordinary code
(`self._bytes = remaining` in `_utf8.mojo`, `self.functions = ...` in
`module_gen.py`) was being refused for a frame the program had just replaced.
Excluding written fields from the placement list is the fix; the prohibition
was the band-aid.

### What it lowers, on both machines

* `h.a.b` in a value position, `a` a placed nested field: two loads. Both
  backends intercept it in `_load_var`/`_store_var`, keyed on a **separate**
  table `_frame_nested_slots` — a `_frame_slots` entry is one load, and a null in
  it is indistinguishable from "this field has no slot", which is the
  disagreement this pass exists to keep apart from "this field is nested".
* `h.a.m(x)`: `_rewrite_nested_method_calls` turns it into `A_m(h.a, x)`, so the
  ordinary call path applies. It is a *second* method-call rewrite because
  `_rewrite_method_calls` runs before any frame analysis exists and only
  rewrites a receiver that is a plain `IdentExpr` — a `MemberExpr` receiver was
  never rewritten at all, and the chain reached the backend as a call to a
  symbol spelled `self.inner.sum`.
* `S()`: one BLOCK per constructor site — the object's own frame, then the
  frames of its typed-nested fields immediately above it, each brought up at its
  own slot defaults and its address stored into the slot. Recursive through
  `struct_nested_frame_fields` and bounded by `MAX_NESTED_FRAME_DEPTH = 4`, so
  a cyclic declaration graph (`A.b: B` / `B.a: A`) truncates identically on both
  machines rather than hanging on one.

**The nested frames go ABOVE the object's own slots, not below, and the reason
is the one C5 flagged as the point of the shape.** A value read out of a frame
consults exactly one slot, and a nested frame's address is a frame address — so
if a nested frame sat inside the outer frame's own byte range, a value read
could *be* a frame base and the two would stop being distinguishable.
`Frame.nested_above_own_slots` is that: every slot of the object ends below the
nested frame's base. `Frame.nested_write_no_outer_slot` and
`Frame.outer_write_no_nested_slot` are the two directions of "so a method
reached through a nested field and a method of the outer struct are
independent", and `Frame.block_sep_nested_sep` is the one arithmetic step
`frame_frames_no_alias_neqn` does not supply: the bound the emitter actually
produces is about **blocks**, and it has to be turned into a bound about the two
nested frames before that theorem applies.

### The blob-in-a-field premise, stated and checked

C5's fourth open item: *"A blob stored in a field has the frame's lifetime
problem one level down … the reason it cannot be lifted is not yet written down
as a premise anywhere."* It is now a premise with a name, a check and a test.

`formal/model.py`: `FRAME_FIELD_BLOB_PREMISE_B1` / `_B2`,
`struct_field_container_writes`, `frame_field_premise`,
`frame_field_premise_note`, `frame_field_premise_refusal`.
`formal/build.py`: `check_frame_field_blob_premises`, called from the two entry
points.

The premise has two halves with **different standing**, and saying so is the
point:

* **(B1) is a real constraint, enforced.** No method body that actually EXECUTES
  writes a container into a field. A list or a dict on this path is a
  bump-allocated region of the function's own reserved scratch, so a slot
  holding one hands a method a blob whose bytes belong to whichever function
  built it.
* **(B2) is an enabling premise, asserted by the emitter and reported by
  name.** `S()` emits no call and refuses `S(x)`, so `__init__` does not run and
  the `self.items = List[Self.T]()` in every container-shaped `__init__` in the
  corpus never executes. That is *why* nearly every container-shaped struct
  passes (B1) — `frame_field_premise_note` prints the sentence for the ones that
  would not, e.g. *"Parser.__init__ assigns a container literal to
  self._pending_decs … this is safe only because S() does not run __init__"*.

**D1 can rely on (B1).** It is a refusal, not a comment, and it is
`byref_refuse_container_written_into_a_field` in `test_formal_run.py`. What it
buys concretely: with the check in place, `self.<container>.append(x)` in a
method cannot append into reclaimed stack, because no slot can hold a container
in the first place. The residual, stated: a write of a **bare name** whose value
kind is unknown is not caught — `_is_container_value` names that gap and says
what closes it (the value kind of a name, which is `ValueKinds`' question and
D1's table, not a re-derivation to be smuggled in here). One hop of propagation
IS caught (`tmp = [1, 2, 3]; self.x = tmp`).

**And the check found a real wrong program, not just a missing comment.** A
two-field struct whose `reset()` assigns `[1, 2, 3]` into a field:

```
$ cd /tmp/d2base && python3 fire.py build --formal --no-prove -o b1b.out b1b.mojo
Built: b1b.base.out  [arm64/macho]
$ ./b1b.base.out ; echo $?
128            # the source says 42
```

The pre-change tree built it, ran it, and returned a **blob address** read out
of a frame slot. Now it is refused by name. `byref_refuse_container_written_
into_a_field` fails on the pre-change tree for exactly this reason: the harness
reports *"BUILT a construct that has no representation … the binary is the real
answer here."*

**Where the check is called from is a measurement, not a style choice.** With it
inside `_prepare_functions` it fires before imports resolve, and it fires on
**106 of this repository's 284 files** — 67 of which import a CPython host
module, for which the import is the more fundamental fact. Measured: **67 files
moved `not-answerable/host-import` → `codegen`**, putting 67 unbuildable files
into the measured denominator and reporting coverage as 40.4% when the accurate
figure is 61.1%. That is the mirror image of the drift C5 called out, so the
check moved LATER, to the two entry points where both facts are known
(`formal/build.py`'s `build_module`, after `_resolve_imports`, and
`_formal_module_functions` for the dylib path). **Zero class moves after the
move**, and both `stdlib-dylib`'s skip count (0) and `stdlib-syntax`'s
unexpected-failure count (0) are unchanged.

### What it did to the 42

**No file in the group became compilable, and the honest reason is the
annotation, not the analysis.** Of the group's 15 direct findings, the field
whose declared type is read is a type this module does not declare in **every**
one:

| field | declared | declared in the same file? | what the analysis now says |
|---|---|---|---|
| `BinaryHeap._data` | `List[Self.T]` | no | a value, not a frame — so `self._data.clear()` goes to the value path |
| `Semaphore._state` | `Int32` | no | a value; the frame diagnostic is GONE |
| `_PhiloxWrapper._rng` | `PhiloxRandom[10]` | **an import ALIAS** for `Random`, in `philox.mojo` | untyped here |
| `NormalRandom._rng` | `Random[Self.rounds]` | **yes** | **a placed nested frame**, slot 1, block 48 bytes |
| `Interpreter.scope` | (assigned in `__init__`) | — | untyped, and the refusal says so |
| `ARM64Codegen.asm` / `X86_64Codegen.asm` | (assigned in `__init__`) | — | untyped |
| `Tail._chunks` | (a list) | — | untyped |

Two rows are worth reading twice. `NormalRandom._rng` is a **real stdlib nested
frame that this path now places** — measured: `nested [('_rng', 1, 'Random')]`,
`block 48` (16 own + 32 for `Random`) — and `philox.mojo`'s refusal moved from
"the slot would have to hold a frame address" to its import chain, i.e. the
shape no longer refuses at all. It emits nothing, because `NormalRandom()` is
constructed only in `__init__` and there is therefore no site; the honest
statement is that the ANALYSIS accepts the real stdlib shape, not that a stdlib
file now compiles. And `Semaphore._state: Int32` is the negative use doing its
job: `self._state.eq()` no longer produces a frame diagnostic at all, because
the annotation proves the word is a value and `model.value_method_refusal` is
the diagnostic that describes it.

**The one thing this change is really worth is a diagnostic bug it fixed.** C5's
message printed the METHOD's own name where the FIELD's belonged, so
`interpreter.scope.define()` read as *"the word in the slot `interpreter.define`"* —
a field the source never mentions. Eleven repo files and most of the group now
say `interpreter.scope`, and the disagreement that stopped them is spelled.

### The pointer half, deliberately not done

`var p: Pointer` → `self.p.value` as a load at a computed offset is the other
half of C5's sentence and it is **not** attempted, for the reason C5 gave: the
pointee's width, signedness and address space are not in this value model, so
the only instruction available is an 8-byte load, which over-reads a `UInt8`
pointee by seven bytes and can fault on a page boundary, and for a struct pointee
there is nothing at the address to load. D3's concurrent `ptr.value()` refusal
now says exactly that, and it is the same conclusion from the value-model side.

### The `S()` / `__init__` question: REPORTED, not changed

C2's documented design, measured again while building the census, and left
alone. `S()` takes no arguments, emits no call, and brings every field up at its
class-level default; `__init__` never runs, so a two-field struct with a list
field, `__init__` assigning it, and a method reading `len(self.items)` reads 0
where the language's constructor would have put a list. It is the single largest
reason the stdlib's container-shaped structs cannot work here, and changing it
is a change to what a struct *is* on this path (`MojoExpr` has no aggregate
node, `MojoFunc` has one parameter, `evalFunc` is `UInt64 → UInt64`) — not a
small, safe improvement, and not one to make unilaterally while four other
agents hold the tree. The premise that makes it survivable is now written down
and checked (above), which is the part of it that was missing.

### Still open after wave 4

* **An import ALIAS is not a declared type this path can use.**
  `from .philox import Random as PhiloxRandom` and `var _rng: PhiloxRandom[10]`
  is a nested frame by every rule except that the name in the annotation is not
  the name the struct is declared under. Resolving it is a BINDING problem
  (`formal/imports.py`), not a frame one, and it is the single change that would
  put the stdlib's other nested-frame shapes in reach.
* **The untyped majority of the group.** 13 of the group's 15 direct findings
  are classes that assign their fields in `__init__` and declare none. No
  annotation means no type, and the rule says so rather than guessing; the way
  to change that is to make `S()` run `__init__` (above) or to require an
  annotation, neither of which is a decision this change can make.
* **A nested frame deeper than `MAX_NESTED_FRAME_DEPTH = 4` is dropped from the
  layout, not refused.** The block size truncates with it, so it is safe, but a
  program that needs the fifth level gets a nested frame the emitter did not
  place and a field-of-a-field refusal on the use. The bound is a hang-avoider,
  not a design.
  **MEASURED 2026-10-01, so the corpus claim above is a number rather than an
  impression — and the headroom is two levels, not one.** Walking
  `model.struct_nested_frame_fields` to its own fixed point over every `.mojo`
  in this repository and in the new-modular stdlib — **505 structs** (5 here,
  500 in 190 stdlib files) — the histogram of
  `max(depth(struct_nested_frame_fields(...)))` is:

  ```
  depth 0: 478      depth 1: 24      depth 2: 3      depth 3: 0   depth >=4: 0
  ```

  (walked with a cycle guard on `(child.name, id(child))`, and `depth=None` at
  every level so the walk is not bounded by the constant it is measuring). The
  three deepest are `std/python/_cpython.mojo`'s `PyModuleDef`,
  `std/memory/alloc.mojo`'s `ManagedAllocation` and
  `std/collections/dict.mojo`'s `_DictKeyIterOwned`, all at 2.
  **What this buys the next worker:** turning the truncation into a refusal is
  safe for the corpus — nothing is near the bound — so the change is a pure
  diagnostic improvement and does not need a sweep to price. **And what it does
  NOT license:** refusing the whole struct is over-strict, because the bound only
  truncates the *deepest* struct's own nested fields, so a five-deep chain whose
  innermost fields are plain integers works today and would stop. The honest
  shape is to report the CUT (`struct_nested_frame_fields` at depth 0 returning
  `[]` while the struct has a nested field to place) at the construction site
  that would have placed it, not to refuse the declaration.
* **`Refine.lean` needed no change and that is worth saying.** A method's callee
  contract is `FrameOk_except st st' base n`, and `n` is a slot count — a block
  is contiguous from `base`, so carving the whole block out is the same
  predicate with a larger `n`. There is nothing to add and adding something
  would be a second spelling of one fact.
* **No method is proved end to end**, and a nested frame is not either. The
  generator half (`formal/arm64_proof_gen.py`, step 6) is untouched, so
  `Frame.nested_*` is proved and unused by any generated proof — the same
  standing as C5's `frame_frames_no_alias`.

### Wave 4 (D2) verification

Judged by the `detail` text; the class labels are C1's and moved under this
change twice before settling. All four sweeps re-run after the change.

| command | before (wave 3, `/tmp/s5_*.txt`) | after |
|---|---|---|
| `LEAN_PATH=lib … ensure_library(…)` | `RESULT OK`, 3 pre-existing `DylibExport` `sorry` | `RESULT OK`; `sorry` in `lib/` still **2 + 1**, all pre-existing |
| `python3 test_formal.py -j 18` | `PASS=40 KNOWN-GAP=3 FAIL=0` | **unchanged** |
| `python3 test_formal.py --backend x86_64 -j 18` | `PASS=43 KNOWN-GAP=0 FAIL=0` | **unchanged** |
| `python3 test_formal_run.py` | `PASS=111 FAIL=0` | **`PASS=146 FAIL=0`** (8 added, all fail pre-change) |
| `python3 test_formal_dylib.py` | `PASS=11 FAIL=0` | **unchanged** |
| `python3 test_formal_imports.py` | `PASS=24 FAIL=0` | **unchanged** |
| `python3 test_suite.py` | `43 passed, 0 failed` | **unchanged** |
| `python3 test_formal_sweep.py` | `55 tests, OK` | **unchanged** |
| `python3 formal/x86_64_model_test.py` | `agree 43 WRONG 0` | **unchanged** |
| `tools/suite.py check` | `7/7` | **`7 passed, 0 failed`** (7 replayed) |
| `tools/suite.py gate` | `15 passed, 3 expected-failure` | **`15 passed, 0 failed, 5 skipped, 3 expected-failure`** (155 jobs, 474.7 s, peak 10.5 GB) |
| `tools/formal_sweep.py --no-stdlib -j 12 -t 300` | 284 files, `PASS=80`, coverage 80/131 = 61.1% | **284 files, `PASS=80`, coverage 80/131 = 61.1%**; **0 class moves**, 11 detail changes, all D2's |
| `tools/formal_sweep.py --no-stdlib --arch x86_64` | 284 files, `PASS=79`, 0 of 204 differing | **`PASS=79`, coverage 79/130 = 60.8%, 0 of 204 shared files differ** |
| `tools/formal_sweep.py -j 12 -t 300` | 578 files, `PASS=105`, coverage 105/414 = 25.4% | **`PASS=105`, coverage 105/414 = 25.4%**; 0 gained, 0 lost, 7 moves all `CODEGEN` → `CODEGEN/DEPENDENCY` |
| `tools/formal_sweep.py --arch x86_64 -j 12 -t 300` | 578 files, `PASS=103`, 92 of 473 differing | **`PASS=103`, 96 of 473 differing — 0 of them D2-marked**; all are the concurrent `ptr.value()` divergence |

`stdlib-dylib`: skip count **0** before and after. `stdlib-syntax`: `FAILED: 0
(0 expected, 0 unexpected)` — `U` did not increase, it is zero.

**No file newly passes and no file that passed stops passing, in either scope
and on either architecture.** That is the same honest headline C5 reported, and
for a sharper reason: the group's block was the ANNOTATION, and an annotation is
either present and names a struct of the same file (one stdlib case, which now
lowers) or is absent. The work moved the diagnosis, fixed the slot name the
message printed, and removed a program that was answering 128 where the source
says 42.

## Wave 4 (D4): the hand-off, split by what the callee actually is

`test_formal_run.py`'s `byref_*` cases are the account, and the
measurements and the per-file table. What belongs here is the one-line summary
and the thing that changes this document's own conclusions.

**"A function this module does not compile" was, for 23 of this repository's 25
sites, false.** Every one of them was a method of the receiver's **own** struct
reached across a module boundary, and the callee *is* compiled — into the
dylib that `formal/imports.py` builds for the imported module. It was not
*advertised*: `_method_exports` carried a filter whose own comment read "refused
at lift time, never compiled", which was true before this design and stopped
being true when it landed. So the sentence "a frame address is only meaningful
to code compiled against the same field list" was answering a question that did
not arise: the code is compiled against the same field list, because the
importer read that field list out of the file the dylib was built from. Both
halves are fixed; a two-field struct's method now crosses the boundary, reads
and writes the caller's frame correctly, and the program computes the right
answer on both machines.

**"Is a frame address enough?" — the answer this document gives is now measured
rather than argued, and it is yes in one more place than it said.** `Pointer`
was in the value-only set on the reasoning that the callee wants the object and
would dereference the address instead. `Pointer` is an *identity* conversion, so
the address is the answer. And the frame's bytes **are** the struct's C layout
for a struct of 8-byte fields: `memset(Pointer(to=s), 65, 16)` writes both slots
and both read back, on both machines. What is still refused is a C entry point
that takes the struct's bytes, and the reason is now the accurate one — the C
library's declaration of the struct comes from the C headers, not from the Mojo
declaration here, and nothing on this path compares them.

The net effect on this file's own census: the case-(c) family falls from 25
sites to 3 in the repo scope, one of which is a struct constructor (a copy
construction, `S(x)`, which has no lowering on this path) and two of which are
genuinely cross-module free functions. **No file newly compiles**: eleven repo
files moved `codegen → not-answerable/host-import`, because the hand-off is now
accepted and the next fact is a CPython host import they were always also
blocked by. That flatters the coverage denominator, so the baseline 80/131 =
61.1% is the honest figure and 80/120 = 66.7% is not.

## Wave 5 (E5): the loop closed — a method's frame contract, proved

Steps 1–5 landed the frame; step 6 was `formal/arm64_proof_gen.py`, which every
wave has deferred to, and which stopped before the receiver was even reached.
This wave is step 6, and the headline is that **a wide-receiver method is now
proved end to end, with no `sorry` in the way and with the premises shown to be
load-bearing.**

### What the generator could not do, and why (the three blockers, in order)

1. **A `LDR`/`STR` through a non-`SP` base had no correct step RESULT.** The
   generator's `_step_rhs`/`_step_rhs_generic` still carried the pre-fix model
   of `0xF9400000` — a pre-index store of ONE BYTE at `sp - imm` — because the
   generator and `arm64_step` had been fixed together and then one of the two
   was edited. A generated `..._sr_N` lemma therefore asserted
   `arm64_step s code = some <a store>` where the library's `work_step_ldr_pre`
   said `some <a load>`, and `exact` rejected it: **no program that touches
   memory through a non-`SP` base could generate a proof at all.** `idx 18` and
   `idx 31` are now the model the library has (`work_step_ldr_uoff`,
   `work_step_str_uoff`, and the `_WORK_STEP` table dispatches on those names
   rather than on the historical ones). `idx 19` was a THIRD mis-modelled form
   and is now fixed on both sides: `0xB9000000` is `STR Wt, [Xn, #imm]`, and both
   `arm64_step` and the generator had it as a post-index LOAD from `SP`.
   `lib/ProofLib.lean`'s `work_step_ldr_post` became `work_step_str_uoff32`
   (with the old name kept as an alias, as for the other two). Measured first:
   **zero of the 43 examples emitted any of the three**, which is exactly why
   the suite was green throughout.

   One subtlety that is worth the two lines it took to find: the generator's
   RHS has to be the *syntactic* mirror of the library lemma's statement, so
   `arm64_reg 31 s` must be emitted as `arm64_reg 31 s` and **not** as the
   equal `s.sp`. A hand-simplified base is a different term, and `exact` cares.

2. **A method's own stack traffic is in the way of reading its receiver.** A
   method's prologue stores four words at `sp - 8 … sp - 32` before the `LDR`,
   so the value the source says is in the receiver's slot `k` is read out of
   the memory *after* those stores, and the terminal value flow has to peel
   them. There was no lemma for it — the existing ones are all stated over
   `sp + j` (a caller slot) or over two frame slots. `Frame.frameRead_write_below`
   (in `lib/ProofLib.lean`, proved, no `sorry`) is that lemma: a store at
   `sp - j` leaves the frame slot `k` alone, given `FrameFits base (k+1)` and
   `FrameBelow (sp - j) base 1`. `u64_sub_pair` is the second new lemma, and it
   exists because `u64_sub_add` leaves `UInt64.ofNat 16 - 8` in a shape
   `u64_ofNat_sub` does not match, so a pair's second word never reached the
   canonical form the frame premises are stated in.

3. **The contract is about MEMORY, so the proposition is about memory.** A
   method's `x0` is not a source-level value, and the entry function's `mojo`
   does not exist at all for a program that constructs a frame — so the ordinary
   `s.x0 = mojo n` is not a statement anyone can make. What is true, and proved,
   is the frame relation.

### The proposition

For `formal/examples/wide_recv.mojo`'s `set_x(self, v)` on a two-field struct,
the emitted theorem is (addresses elided, the rest verbatim):

```lean
theorem main_Point_set_x_frame_contract (n v : UInt64) (hmem : Nat → UInt8)
    (hn : 131168 * (n.toNat + 1) + 131168 ≤ 18446744073709551600)
    (hfit : Frame.FrameFits n 2)
    (hsep8  : Frame.FrameBelow (UInt64.ofNat 70368744177664 - UInt64.ofNat 8)  n 1)
    (hsep16 : Frame.FrameBelow (UInt64.ofNat 70368744177664 - UInt64.ofNat 16) n 1)
    (hsep24 : Frame.FrameBelow (UInt64.ofNat 70368744177664 - UInt64.ofNat 24) n 1)
    (hsep32 : Frame.FrameBelow (UInt64.ofNat 70368744177664 - UInt64.ofNat 32) n 1)
    (hbnd : FrameBound 131168 { … } n) :
    (match arm64_exec_go_exit { Arm64State.init n 4294967808 with
                                pc := 4294968024, x30 := UInt64.ofNat 4294968168,
                                sp := UInt64.ofNat 70368744177664,
                                mem := hmem, x1 := v }
                              main_code 4294968168 ((200000 + 14 * n.toNat)) with
     | some s => Frame.frameRead s.mem n 0 = v ∧
                 Frame.frameRead s.mem n 1 =
                 Frame.frameRead ({ … }).mem n 1
     | none => False)
```

Read: **for any receiver word `n` whose frame fits, and for ANY memory
`hmem`**, entering the method with that receiver in `x0` and `v` in `x1` leaves
the receiver's slot 0 holding `v` and its slot 1 exactly as it was. The
premises are the calling convention in the frame layout's own vocabulary:
`FrameFits` (the frame does not run off the top of the address space, so its
slots have distinct addresses) and, per stack word the method touches,
`FrameBelow` (the receiver frame's base is at or above the top of that word).

Three things about it are deliberate and are the reason it is worth anything:

* **`hmem` is a parameter, not `Arm64State.init`'s all-zero memory.** With a
  zero memory every slot of every receiver reads `0`, so the theorem would be
  `0 = 0` and would pass whether the method wrote slot 0, slot 1, or the wrong
  register. Quantifying the memory is what makes the proposition testable, and
  it is the change that turned a green file into a checkable one.
* **The entry `sp` is a literal with room above and below**, not
  `0xfffffffffffffff0`. The receiver frame sits AT the callee's entry `sp` and
  grows upward, so with `sp` at the top of the address space the frame's second
  slot wraps and `FrameFits` is false for EVERY receiver — the contract would be
  true and vacuous, with no `n` satisfying its premises. (The premises are
  jointly satisfiable at `n = sp`; that is what a real caller does.)
* **No `sorry`, no `grind`, no `+decide`, no evaluator tactic.** A frame
  contract is emitted with `all_goals done` where the ordinary path emits
  `all_goals (first | done | sorry)`, and with the terminal value flow's `simp`
  as `simp only`. That is not a style choice: `grind` closed a *false* version
  of the getter's claim during development, and `bv_decide`/`+decide`/
  `exact u64_div_msub` each cost 20 million heartbeats on a goal with a `String`
  -keyed `Decidable` instance in it. A gap here is now a hard error.

For a getter, the machine half's claim (`s.x0 = Frame.frameRead s.mem n k`) is
emitted **as a separate source-semantics theorem** rather than inside the
contract: `<m>_source_semantics` says the `MF.evalMethod` of the method body,
with the field environment `Frame.frameToEnv` reads out of the receiver's frame,
IS `Frame.frameRead mem n k`, and the contract says the machine returns the
same term. The two compose at one shared term, and putting the `MF` term in the
contract's own statement cost a 20M-heartbeat `whnf` timeout (see below).

### It is not vacuous — three checks, each of which fails

| check | what was changed | result |
|---|---|---|
| a premise is load-bearing | `have hlow24 : 70368744177640 + 8 ≤ n.toNat` weakened to `+ 1` | **`Type mismatch`** at the derivation |
| the claim is about the right slot | `Frame.frameRead s.mem n 0 = v` → `n 1` | **does not typecheck** (heartbeat timeout on the unpeelable goal) |
| the frame work is what closes it | every `hfb*` peel equation and every `rw [hfb*]` deleted | **`Unknown identifier` / `unsolved goals`** |

And a fourth, at the source level, as two `test_formal_run.py` cases: the
generator READS each field's slot off the emitted `STR`'s offset, so two
programs differing in one character of a method body (`self.x` vs `self.y`) get
41 and 40 (`byref_slot_follows_the_field_written`,
`byref_second_field_write_leaves_first`).

### What is still open, with the measurement

* **A getter's UNIVERSAL contract is generated and typechecks, and costs ~20
  million heartbeats per method** (a 41-minute `lean` on one three-method
  example, measured, with `maxHeartbeats 400000000`). The claim is about `s.x0`,
  so the value flow goes through the method's whole register chain, and
  re-deriving it with the terminal `simp only` over every block definition is
  what costs. The fix is the one the ordinary path already has — a per-block
  `have` for the result register instead of a `simp only` that re-derives it —
  and until then the getter's end-to-end claim is its `native_decide` run test,
  which is a real evaluation of the model over the real instruction bytes.
* **The entry function's own result is not proved.** Its blocks contain `BL`s,
  and the CFG walk discharges a call with the RECURSION contract, which is only
  valid when the callee is the entry function. A call to a different function
  needs an interprocedural contract; `Point_get_x`'s contract above is the
  callee half of one.
* **`Frame.SlotOf` is still used by no generated proof.** The contract's field
  table is an inline `if`-chain, and a `SlotOf` for it needs a `String` case
  analysis the generator has no source for. The concrete slot literals are what
  it actually knows, and `Frame.frameRead_frameWrite_ne` (disjointness of two
  slots of one frame) is what the non-interference conjunct is about.
* **A runtime-indexed subscript is proved on the machine half and not on the
  source half** (`formal/examples/subscript_var.mojo`, an `EXPECTED_FAILURES`
  entry with the reason). Every `LDR`/`STR` through a non-`SP` base now gets a
  correct step lemma and the block certificates build; what is missing is the
  SOURCE side, and it is not a dataflow question — `mojo : UInt64 → UInt64` has
  no domain for a list, so `a[i]` has no value in it, and the list's storage (a
  blob whose first word is its count) is never related to the source literal.
  Two facts close it: a list domain in the model, and a memory image for the
  blob. A dict lookup still crashes the generator
  (`unsupported edge … loop back-edge`), unchanged and recorded.

---

## Round 2 (agent [4]): the returned frame — the decision, and where it is blocked

The last bullet above ("what is still open") is a list of Lean-side items. This
section is the OTHER half: the `return <frame>` case, which is 18 findings and
one design decision, and which is blocked on **ownership**, not on difficulty.

### What the sweep says, measured on this tree

`tools/formal_sweep.py` arm64, 596 files: `PASS=108`, `codegen=128`,
`codegen/dependency=181`, coverage `108/417 = 25.9%`. The 128 in-file codegen
findings by family, and the frame-address ones marked:

```
  receiver passed as an argument                    23   *
  frame address passed where a value is wanted      19   *
  frame address escapes: returned by its creator    18   *  <- this section
  MLIR construct                                    14
  callee has no definition on this path             12
  field slot holds a frame address                  10   *
  frame address escapes: aliased out of a method     9   *
  nested frame field read                            7   *
  name has two disagreeing shapes                    4   *
  comptime does not fold                             2
  method call on a value                             2
  self has two kinds of value across call sites      2
  construction with arguments needs __init__         1
  module-global name has no storage                  1
  receiver stored in a container                     1   *
  unimplemented intrinsic                            1
  value with no representation                       1
  variadic call has no ABI                           1
```

The 12 `callee has no definition on this path` are **not** this design defect
and the taxonomy is right to separate them: the callee is a bare name with no
body in the image, so whether the address means anything is a question about
the dylib, not about frames. Counting them would be the specific way a
taxonomy gets worse than none — a number in the wrong column.

The 18 are not 18 problems. They are one `raise` at `formal/build.py:2423`, and
`frame_return_refusal`'s own docstring says the 18 messages are **verbatim
identical** apart from the struct name, across 18 files and 12 struct types
(`String` x6, `Interpreter` x2, and ten singletons).

### The decision, made

The copy has to land somewhere the CALLER owns. The candidate regions in one
scratch, and why a fourth cannot overlap any of them:

| region | where | why it is there |
|---|---|---|
| receiver frames | bottom | a callee's frames/blobs are below every frame the CALLER owns (`Frame.frameWrite_read_above_sp`) |
| list/dict blobs | growing up from above the frames | a blob must not land on a frame |
| spill slots | top, below the saved-pair area | already spoken for |
| **returned frames** | **between the blobs and the spill slots** | above the blobs, so a blob growing upward cannot run into one; below the spill slots |

That ordering is the whole of the placement argument, and it is why the layout
is a function in the shared model (`struct_returned_frame_sites`) rather than an
offset written in each backend: a scratch laid out one way by arm64 and another
by x86-64 is a returned frame that is correct on one machine and a
use-after-free on the other. Per CALL SITE, in walk order, reserved in the
prologue — the same discipline as `struct_constructor_sites`, so a call inside
a loop reuses its site and the stack cannot grow without bound.

**Getting the caller's block address to the callee** is the whole of the
remaining question. Three candidates, costed:

1. **A ninth argument register.** No. AAPCS has X0..X7 and X16/X17 are
   IP0/IP1, which `BL` destroys. This path already drops arguments past eight
   for compile-only fidelity (`arm64_codegen.py`, `_emit_call`), so a ninth word
   is not a register to find.
2. **The callee computes the caller's block itself.** Arithmetically possible
   and this is the one that looks like it should work: the prologue's
   `SUB SP, SP, #_SCRATCH` and the epilogue's matching `ADD` are symmetric, so
   a callee's scratch begins exactly `_SCRATCH` below the caller's and the
   callee can address the caller's **whole scratch** from its own `SP` with
   nothing but a compile-time constant. What it cannot do is know **which** of
   the caller's blocks to copy into — the offsets are assigned per call site in
   the *caller's* walk order, and the callee has not read the caller's body. A
   single fixed slot works for `a = f(); b = f()` (same block, reused) and
   collides for the one shape that matters, `f(g())`, where the inner and outer
   results must be live at once.
3. **A hidden trailing argument on the returning function. CHOSEN.** The
   returning function gains one hidden word, and `return <frame>` becomes "copy
   `8 * block_bytes` from my own site into that word, and return that word".

   (3) reuses the by-reference receiver convention that already exists — a
   frame address is one word, and the receiver is already passed as one — so it
   needs no new register, no new calling-convention section, and it leaves
   `MojoFunc`, `evalFunc`, `evalBodyEnv` and the value model untouched. That is
   the same property the by-reference design was chosen for in the first place,
   and it is the reason this is a codegen change rather than an ABI change.

   Its cost is a limit that has to be REFUSED rather than approximated: the
   hidden word is a ninth argument, so a callee that already takes eight
   arguments cannot be given it. `returned_frame_convention_refusal` says so
   by name rather than handing back a dropped argument and a frame copied into
   scratch nobody reserved.

### Why this is blocked, and it is not on the Lean side

Two boundaries, and the first one is a gap in the round's partitioning:

* **`formal/build.py` is in nobody's write set** and is not in §11.2's
  "Deliberately unowned" list. It is also the file that raises the refusal
  (`:2423`), so all 18 findings are gated on a line nobody may edit.
  `bugs/INTERFACE_REQUEST_4_to_formal_build.md` asks the integrator to assign
  it and states the exact removal.
* **The proof-side obligation** is a `lib/Refine.lean` predicate — a callee
  contract variant that carves out the passed-in block rather than the receiver
  frame, the same additive move as `FrameOk_except`. That is [3]'s file;
  `bugs/INTERFACE_REQUEST_4_to_3_contracts.md` states the shape the codegen
  will be written against, so the emitters and the theorem cannot disagree.

### What is landed, and what it is worth

`formal/model.py`: `struct_returned_frame_sites` (the caller's layout),
`returned_frame_convention_refusal` (the decision above, as a refusal that
names its own reason), and `RET_FRAME_REGION_ABOVE_BLOBS`. Pinned by
`test_returned_frame_layout.py` (10 cases).

**It is worth: nothing observable, and that is stated here rather than implied.**
The sweep is byte-identical before and after — 18 `returned by its creator`
findings, `108/417 = 25.9%` — and `test_formal_run.py` is 340/340. What landed
is the piece every later piece needs and that did not exist: the caller's
destination blocks are computed, by one function both machines read, and the
convention that moves the address across the call boundary is decided and
written down instead of being the thing the next session re-derives.

Making the refusals louder was available and was NOT done. The 18 refusals
already name their cause precisely, and §11.2's trap for this item is exactly
that: "making the refusals *louder* without changing what is computed. That
converts a wrong answer into a red test, which is worth something but is not
this item." These are not wrong answers — they are refusals — and renaming or
elaborating them would have moved the headline without a line of behaviour
changing. **The 18 findings are gone when the copy is emitted, and not before.**

---

# Wave 8 (formal-string-return): the returned-frame convention LANDED

The last sentence of wave 3 said what the 18 findings were waiting for, and it
was right about the mechanism and wrong about the order: the copy is emitted
now, and the two halves that were designed around it — the caller's block
(`model.struct_returned_frame_sites`) and the convention decision
(`model.returned_frame_convention_refusal`) — are no longer a design, they are
what the emitters call.

## The convention, in three sentences

A function that returns a multi-field struct's receiver **takes one hidden
trailing argument**: the address of a block the CALLER reserved, in the
caller's own scratch, per call site, in the prologue. `return <frame>` becomes
"copy the block to that word and return that word". Nothing else changes: the
value model, `MojoFunc`, `evalFunc`, `evalBodyEnv` and the machine model are
untouched, because a frame address was already one word and the receiver is
already passed as one.

Three properties of that shape are what make it work, and each is a place a
naive version of it goes wrong:

* **The block is per CALL SITE, not per function.** One fixed slot works for
  `a = f(); b = f()` — the same block, reused — and collides for `f(g())`,
  where the inner and outer results must be live at once. That is the
  measurement `returned_frame_convention_refusal` records against candidate 2
  ("the callee computes the caller's block itself"), and
  `returned_frame_nested_calls_two_blocks` in `test_formal_returned_frame.py`
  is the program that says so.
* **The whole BLOCK is copied, and the nested frames are re-pointed at the
  copy.** A placed nested frame's slot holds the address of a frame inside the
  object's own block (`model.struct_nested_frame_fields`), so copying the bytes
  without re-pointing the slot leaves the caller reading a nested field out of
  the callee's reclaimed scratch — the use-after-free, one level down, with the
  outer object looking perfectly correct.
* **The budget is SIX source arguments, not eight.** arm64's X0..X7 could carry
  one more; x86-64 passes integer arguments in six registers. The shared number
  is the smaller one, because a build that says "eight is fine" on arm64 and
  "eight is not fine" on x86-64 is the two-backend disagreement this pair of
  backends is not allowed to have.

## What is still refused, and why each one is not a missing lowering

`model.frame_return_mixed_refusal` is the one that is a real limit rather than
a representation, and it is worth stating why: **one function cannot have two
return conventions in one image.** A caller has to decide, before the call,
whether to reserve a block for the result, and there is no reading of
`return r` on one path and `return 7` on another under which both are right —
treating it as frame-returning hands the caller the ADDRESS of a block the
callee never wrote, and treating it as word-returning hands it a frame address
to read fields through. The same message covers a body that returns a frame on
one path and ENDS on another, which is the uninitialised-block version of the
same question.

`model.entry_frame_return_refusal` is the entry function: its caller is the C
runtime, which passes no such word, so there is nowhere for the copy to land.
`model.dylib_frame_return_refusal` is a frame-returning function offered at a
module boundary: the hidden word is a property of ONE image's calling
convention, and an importer compiled the module's source with its own
`_frame_receivers` pass and has no table saying which exports take one.

All three are PARKED on the function and raised by `check_frame_return_shapes`
from the entry points, beside the other three late frame checks — a refusal
raised from inside `_prepare_functions` is reported in place of the import
diagnosis, and that defect has already moved 67 files in this repository once.

## The measured effect, both architectures

| sweep (repo scope, `-j 12 -t 60`) | before | after |
|---|---|---|
| arm64 `PASS` | 84 | **84** — 0 gained, 0 lost |
| arm64 codegen coverage | 84/123 = 68.3% | 84/114 = 73.7% |
| `frame address escapes: returned by its creator` | 11 files | **0** |
| `frame address escapes: aliased out of a method` | 3 files | **0** |
| x86_64 `PASS` | 82 | **82** — 0 gained, 0 lost |
| x86_64 codegen coverage | 82/118 = 69.5% | 82/112 = 73.2% |
| shared files whose class OR detail differs between the two machines | 0 of 216 | **0 of 216** |

**The coverage percentage rose and that is NOT 6.6 points of progress.** The
denominator fell by nine, and it fell because six files moved
`codegen → not-answerable/host-import`, one moved to
`not-answerable/system-module-call`, and two stopped being classified at all
because the 60-second timeout caught them on a loaded machine (both get their
pre-change `CODEGEN` verdict at `-t 180`, and their wall time is ~75s of which
7s is CPU, so the difference is machine load and not this change). Moving out
of the denominator without becoming answerable is the one direction of
denominator drift that flatters a number, and it is called out here for the
same reason wave 3 called it out.

**Zero files gained a PASS**, which is the honest headline and is not a
disappointment: almost none of them was ever blocked by the frame layout. What
changed is the DIAGNOSIS, and 18 of this repository's own files now name a
specific next construct. Two of them, measured:

| file | before | after |
|---|---|---|
| `imports.py` | "a Resolver receiver is returned from the function that created it" | `Resolver__find()` takes a `Resolver` receiver at argument 0 at one call site and not a frame at another — the holder-AGREEMENT check, which is a different defect with a different fix |
| `test_async_execution.py`, `test_generators.py` | "an Interpreter receiver is returned…" | `interp.scope.get()` hands the word in the slot to `Scope.get()`, whose receiver is a frame — the slot's declared type does not say it holds one |
| `bootstrap_test_classes.mojo` | "a Point receiver is returned…" | `Point(x, y)` is a call to a user-defined `__init__`, which this path does not run |

On the stdlib side the six files the snapshot named all moved too, and four of
them moved to `codegen/dependency` on a DIFFERENT module's construct
(`binary_heap.mojo`'s `len(self.items)`, `_assembly.mojo`'s inlined assembly,
`env.mojo`'s tuple-indexed `external_call`) — the file's own construct is no
longer what stops it, which is the progress a terminal-construct fix is supposed
to produce. None of the six passes; each has a different blocker underneath.

## A bug the convention made reachable, which is the more useful half

The hidden word is an ordinary local, so it has the same two homes every other
local has — and the SPILLED home had never been used. arm64's prologue
parameter path had a branch for it that moved `X<arg>` into X17 and then stored
X17 *through* X17, so the slot received **the address of itself** instead of the
value. It was unreachable: a function could have at most eight parameters and
ten callee-saved registers, and nothing else could make an eleventh local. The
returned-frame hidden word IS an eleventh local.

Measured, on the change before the fix: a frame-returning function with eight
locals or more **segfaulted on arm64** — the first store to the slot wrote the
frame's own address into it and the first field read dereferenced that — while
x86-64 was correct throughout, because its parameter path went through
`_store_var` and so used the one correct spill addressing. One routine
(`_load_home_from_reg`) now covers both callers, and it also extends a spilled
parameter through a register on the way, which the old `continue` skipped for
the same reason it could not be reached.
`returned_frame_with_spilled_locals` is the case.

The general lesson, which is the one worth keeping: **a convention that adds a
word to a call is also a change to the register allocator**, and the arm64
prologue's two homes for a value are two pieces of code. They had been one for
as long as only one of them was reachable.


---

## Round 3: the codegen landed, and the measured effect was ZERO files reaching `pass`

The section above is the design; this is what happened when it was built.
`bugs/FORMAL_returned_frame_caller_owned_block.md` has the diff-shaped account —
the three decisions, the two bugs the new code contained, and the per-file
landing table for the 30 sweep files this cause blocked. Three things belong
here because they correct or complete statements above rather than replace
them.

**"Why this is blocked, and it is not on the Lean side" is no longer true of
the first bullet.** `formal/build.py` had an owner by the time this landed and
the gate came down: the returned frame is now built in a block the CALLER owns,
passed as one hidden trailing argument, and the 19 `returned by its creator`
findings are **zero**.

**The block is built IN, not copied into.** Round 2 and
`bugs/INTERFACE_REQUEST_4_to_3_contracts.md` both say the copy, and both are
superseded on that one point. A construction inside the returning function
writes through the hidden word instead, which removes the one thing that made
the copy expensive — re-basing the ADDRESS of every nested frame in the block,
at every depth, into the new block. The convention is otherwise identical: same
caller-side block, same hidden word, `return <p>` still returns that word. The
Lean predicate the interface request asks for is unchanged by this, because it
is stated over the convention and not over the copy.

**A forwarder forwards.** `def twice(a): var q = make(a); return q` builds
nothing, so redirecting construction sites does not apply to it; it hands its
own caller's block down to `make` instead. A chain of forwarders therefore
builds one object in the outermost caller's scratch and no copy is ever taken,
which is why the shape most real code has needed a rule of its own.

**And the measured value is 0 files reaching `pass`, which the section above's
framing would not have predicted.** The instruction was to measure by hacking
the refusal away and re-sweeping, and that measurement reports **1** — and the
one file is refused by the finished change for a real reason: its entry function
returns the frame and the startup stub, which passes one word, has no block to
give it. Every other file in the family is behind another row of the map or
behind a documented permanent limit. The 1 is the bug the lift-without-an-
implementation would have shipped, which is the whole argument for measuring
with the fix rather than by lifting the check.

