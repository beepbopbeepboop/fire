# FORMAL_wide_receiver_by_reference: the one-word value model, and the by-reference receiver that fits inside it

Split out of the wave-2 sweep work. This is the document the 53 refusals in
`tools/formal_sweep.py`'s arm64 run all name, and it says what the wall is, what
it costs to close, and — the part that matters — **the wall does not have to be
widened at all**.

Current arm64 baseline: 280 files, `PASS=78`, `codegen=56`,
`codegen coverage 78/134 = 58.2%`, and 53 of those 56 codegen findings are one
diagnostic: a method whose receiver has more than one field, refused because
*"a formal value is one 64-bit word, so `self.<field>` has no representation on
this path."*

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

### Step 4 — NOT DONE: `evalBodyEnv_congr`

The one lemma of step 3 that is missing, and it is missing for a nameable
reason worth recording rather than working around:

> "a field assignment leaves unrelated names alone"

cannot be stated as a fact about the evaluator's *result* by rewriting the
environment argument, because after a field assignment the merged environment
is **not** extensionally equal to `mfEnv fields flds locals` — at the assigned
name the one returns the assigned value and the other returns the old field. It
needs

```lean
evalBodyEnv_congr : (∀ x, env x = env' x) →
                    evalBodyEnv call stmts env = evalBodyEnv call stmts env'
```

which needs `evalExpr_congr` — one structural induction over `MojoExpr`'s
twenty-odd `binop` patterns. Real, additive work; the next step, not something
to fake.

### Step 5 — NOT DONE: the codegen

Precisely, and in `formal/arm64_codegen.py` / `formal/x86_64_codegen.py`, which
are **another agent's files this wave** — so this is a specification, not a
change:

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
4. `formal/model.py`: the refusal at `struct_field_count > 1` becomes a switch.
   **Off by default**, and the full formal suite byte-identical with it off.

**Loud warning, as instructed:** steps 5.1–5.3 are codegen and are in another
agent's lane this wave. If they are taken up, the functions to touch are
`_emit_struct_constructor` and `_emit_expr`'s `MemberExpr` case in
`formal/arm64_codegen.py`, the `MemberExpr` case in `formal/x86_64_codegen.py`,
and the width check in `formal/model.py`. `_rewrite_method_calls` should need
nothing. The switch should default **off**, and the 40-example suite must be
byte-identical with it off.

### Step 6 — NOT DONE: the proof generator

`formal/arm64_proof_gen.py` would need to emit a method's `MFStmt`/`MFExpr`
instead of `MojoStmt`/`MojoExpr`, plus the per-block value flow for frame
accesses, plus `FrameOk_except` in place of `FrameOk` in the method's contract.
Its `_gen_go` (`:878`) is the place where the one-argument model is assumed.

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

## What is not done, stated plainly

* **No method is proved end to end.** Steps 1–3 are the frame, the callee
  contract and the source semantics. What is missing is a *generator* that ties
  them together for one receiver, which is steps 5 and 6 and which is codegen
  plus proof-gen work in files this wave does not own. The formal suite is
  exactly as green as it was and not one byte different, because nothing landed
  here is reachable from a program.
* **`evalBodyEnv_congr`** (step 4) is not proved.
* **No loop contract for a method.** `while` is in `MFStmt` and lowers, but a
  method whose loop writes its receiver needs the loop contract re-derived
  against `FrameOk_except`, and the existing `while_dec_exit_contract` /
  `while_lt_exit_contract` are written against `FrameOk`'s window.
* **The `work_step_*` aliases are still misnamed** pending the `_WORK_STEP`
  rename.
* **The x86-64 side of the model was not re-audited** for the same class of
  mis-modelled memory form. `X86.x86_mem_addr` looks correct on inspection and
  the 43-example model test passes against the hardware, but arm64 is the proof
  that "the examples don't emit it" is not the same as "it is right", and the
  x86-64 examples are the weaker evidence of the two.
* **The `dozens` band is not designed**, only re-banded. The frame is still one
  pointer; what is genuinely unresolved is the caller's frame budget
  (`FrameBelow`) and the size of the `envToFrame` fold at 263 names.

## Verification

All commands run from the repo root. The library itself is known to typecheck
(`formal/lean.py`'s `ensure_library` builds all four modules; a non-zero Lean
exit raises and is reported).

| command | result |
|---|---|
| `LEAN_PATH=lib python3 -c "import formal.lean as l; l.ensure_library(l.find_lean('.'),'lib')"` | `RESULT OK` — `ProofLib`, `X86`, `work`, `Refine` all build |
| `make check-formal` | `Results for arm64 formal proofs: PASS=40 KNOWN-GAP=3 FAIL=0` — **unchanged** |
| `make check-formal-x86` | `Results for x86_64 formal proofs: PASS=43 KNOWN-GAP=0 FAIL=0` — **unchanged** |
| `make check-formal-run` | `formal run: PASS=59 FAIL=0` |
| `make check-formal-dylib` | `formal dylib: PASS=9 FAIL=0` |
| `make check-formal-x86-model` | `x86-64 model coverage: 151 samples over 57 forms — all steppable` |
| `python3 tools/formal_sweep.py --no-stdlib -j 4 -t 60` | `[arm64] 280 files: PASS=79 not-pass=201`, `codegen coverage 79/139 = 56.8%`; file-level set **unchanged: 280** |
| `python3 tools/formal_sweep.py --no-stdlib --arch x86-64 -j 4 -t 60` | `[x86_64] 280 files: PASS=78 not-pass=202`, `codegen coverage 78/138 = 56.5%`; file-level set **unchanged: 280** |

**The sweep cannot be affected by this change, and that is a structural
argument rather than a lucky observation.** `tools/formal_sweep.py`'s
`build_flags` (`:173`) is `("--formal", "--no-prove", f"--backend={arch}")`, and
`--no-prove` means no Lean runs and `formal/lean.py` is never reached; the
sweep's own source contains no reference to `lib/`, `.olean` or
`ensure_library` (checked by inspection of the module). This change is
confined to `lib/ProofLib.lean` and `lib/Refine.lean`
(`git diff --name-only -- lib/`). The movement from the wave-2 baseline
(`PASS 78`, `codegen 56`, coverage `78/134`) to `PASS 79`, `codegen 60`,
coverage `79/139` on arm64 — and the corresponding x86-64 figures — is other
agents' in-flight work in `formal/`, not this change. The swept file set is
identical at 280 on both arches, which is the part that has to hold.

**`sorry` count in `lib/` is unchanged: 2 in `ProofLib.lean` and 1 in
`Refine.lean`, all three pre-existing** (`DylibExport.in_image_stub`,
`DylibExport.semantics_stub`, `dylib_export_contract_stub`). Every declaration
this change adds is proved; `grep -c sorry` over the added text is 0.
