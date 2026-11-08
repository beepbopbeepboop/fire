# plan/step-08c: DESIGN MEMO — how the proof model treats `BLR` (indirect call) and `BR`
**Status: DONE 2026-11-07 (measured).** Memo corrected: Reading A (keep refusing, pin it); 0 of 94 corpus examples emit a BLR and a function-value program is already refused at the source model (`dbl` bound to nothing) before the instruction matters. The earlier Reading C rested on an unmeasured count and on confusing a prover refusal with a build failure.
Class: hard      Size: M      Depends: 08a      Blocks: none
Source: `bugs/FORMAL_arm64_instruction_coverage.md` (`blr`/`br`); `doc/finish-formal.md` step 08.

## Current state (measured; verified 2026-11-05)
- Emission: `formal/arm64_codegen.py:12360` emits `blr x16` for a call through a function VALUE (`through_value`, ~11793-11806). The callee address is loaded into X16 by the code just before.
- `arm64_step` (lib/ProofLib.lean:2097) has a BR arm (`pc := (arm64_reg rn s).toNat`) and no BLR arm. `BL` is `{ s with x30 := UInt64.ofNat (s.pc + 4), pc := ... }` (line 2297). The obvious BLR arm is `{ s with x30 := UInt64.ofNat (s.pc + 4), pc := (arm64_reg rn s).toNat }` — a one-line, true model.
- The CFG walker (`formal/arm64_proof_gen.py` ~5786-5830, 6277, 11512) splits blocks and finds successors only for indices `(14, 15, 16, 17, 51, 52, 53)` (B, BL, CBZ, CBNZ, B.cond, TBZ, TBNZ) with static targets. For BL the call is discharged by the callee's contract / a recursive certificate keyed by the static target (`_gen_universal_e2e_cfg`, `no_change`, `go_lemmas`). Nothing handles a target known only as a register value. A modelled-but-unwalked BLR would be treated as a straight-line instruction whose successor is pc+4: **a certificate about a different control flow**, which typechecks.
- Step-08a names BLR as unmodelled so the refusal is at least truthful.

## The decision needed (deliverable of this step: a committed "Decision" section below, nothing else)
Answer, with the evidence for each reading:
1. **Reading A — keep refusing.** BLR stays unmodelled; the refusal text (08a) is the permanent answer for programs that call a function value. Cost: zero code; every function-value program stays unprovable.
2. **Reading B — model + walk with a known target set.** The generator knows the possible callees of a function value when the value is a literal reference to a top-level function (`through_value` is decided at compile time from a name; read `arm64_codegen.py:11793-11830` to see whether the callee is statically identifiable at the BLR site). If it is, BLR is a BL whose target is that name, and the walker can reuse the BL machinery with the static target (the `ldr x16, =callee` load before it is the evidence). If it is not (value flows through a parameter/field), refuse.
3. **Reading C — model BLR as BL with an abstract callee contract** (an `AdmittedCall` style hypothesis over every function whose address is taken). Needs a new contract shape in `lib/Contracts.lean`; out of scope unless A and B are both rejected with evidence.
Measurements to take (all pure Python, no Lean): (i) for each `formal/examples/*.mojo` and `formal/examples` function-value uses (grep `through_value` tests in `test_arm64_emission.py`/`test_formal_run.py`), is the X16 load a literal address of a named function? print yes/no per site; (ii) how many corpus examples emit a BLR at all (compile with `fb.compile_formal(path, arch='arm64', prove=False, check=False)` and scan the code words for `(w & 0xfffffc1f) == 0xd63f0000`).

## Decisions already made
- The memo's output is a section `## Decision (08c)

*(Rewritten 2026-11-07. The first draft chose Reading C on two errors: it reported "0 / N" without measuring N, and it argued Reading A "would break existing working functionality" -- but a refusal in the PROVER (`prove=True`) does not touch the build, the runtime, or any `--no-prove` image; only the proof is withheld.)*

### Measurements (pure Python, no Lean; script inlined in the commit message of this change)

| question | result |
|---|---|
| corpus examples whose arm64 image contains a BLR word (`(w & 0xfffffc1f) == 0xd63f0000`), `compile_formal(..., prove=False)` over all of `formal/examples/*.mojo` | **0 of 94** |
| `def dbl(x): return x*2; def main(n): var g = dbl; return g(n)` with `prove=False` | builds; **1** BLR word in the image |
| the same program with `prove=True` | **refused before BLR matters**: "the semantic model has no value for something in this program ... `dbl` is read here and this generator binds it to nothing (the model's environment ...)" |
| the callee-address load before each BLR (from the first draft's survey of the closure tests) | loaded from a local/parameter slot, not a literal named address at the BLR site, so the target is NOT statically identifiable at the instruction |

### Chosen reading: **A -- keep refusing, and pin it**

1. The refusal already happens, one layer earlier than the instruction: the SOURCE model has no value for a function value (`dbl` bound to nothing), so no program that reaches a BLR gets a proof today. Modelling the BLR arm would change nothing a user can prove, and would add the danger 08a named: a modelled-but-unwalked BLR is a straight-line instruction with successor `pc + 4`, a certificate about a different control flow that typechecks.
2. Reading B is not available as specified: the target is not a literal at the BLR site (table row 4), so it needs data-flow from the function value to the call, which is a source-model feature (give function values a denotation), not a BLR feature. That is the real prerequisite, and it is larger than this step.
3. Reading C (abstract callee contract over every address-taken function) needs a new contract shape in `lib/Contracts.lean` and a source-model denotation for function values as well; with zero corpus examples it has no consumer to test against.

**So the order of work is: function values get a denotation in the source model first; BLR is modelled and walked only after that, as Reading B or C, with a corpus example that needs it.** Until then BLR stays named-unmodelled by 08a.

### What to do now (one mid-class step, 08d; nothing else is needed)
Pin the refusal so it cannot silently become a wrong certificate: in `test_formal_call_proof_gen.py` add a test that compiles the `dbl`/`g(n)` program above with `prove=True`, requires a refusal, and requires its text to contain "binds it to nothing" (the layer that refuses today), plus one assertion that a `prove=False` build of the same program contains exactly one BLR word and that `_unmodelled_instruction` (08a) names it. If the SOURCE-model denotation lands later and the first assertion starts failing, the failure is the signal to revisit this memo, not to delete the test.
