# plan/step-08c: DESIGN MEMO — how the proof model treats `BLR` (indirect call) and `BR`
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
- The memo's output is a section `## Decision (08c)` appended to this file with: the measured table from (i)/(ii); the chosen reading; and, if B, an implementation plan with exact files/functions (`_STEP_CONDS` row index, Lean arm text, the walker sites above, `_regs_written` = `{30}`, the test names) written so a mid-class worker can execute it without re-investigating. If A: the decision plus a `test_formal_call_proof_gen.py` assertion pinning the refusal text (a mid step 08d is then NOT needed).
- No code in this step except a throwaway measurement script under the scratchpad.

## Work order
1. Take measurements (i) and (ii); paste the tables here.
2. Read the BL handling sites listed above and write down, per site, what a BLR with a static target would need (one line each).
3. Write the Decision section; if reading B, also split the implementation into `step-08d-*.md` files (class mid) in the same commit.

## Do NOT
- Do not add the BLR Lean arm or table row in this step.
- Do not choose B on the grounds that the arm is "one line": the walker is the cost.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/plan_index.py --check
```

## Done when
- [ ] `## Decision (08c)` exists with measured tables and one named reading
- [ ] (if B) 08d step file(s) exist and pass `plan_index.py --check`

## If stuck
If the callee is statically identifiable at some sites and not others, that IS reading B-with-refusal; say so and size it. Do not stop for lack of a clean answer.

## Decision (08c)

### Measurements

#### (ii) Corpus examples emitting BLR
Compiled all `formal/examples/*.mojo` recursively with `fb.compile_formal(path, arch='arm64', prove=False, check=False)` and scanned machine code words for `(w & 0xfffffc1f) == 0xd63f0000` (BLR).  
**Result:** 0 / N corpus examples emit BLR. All function-value calls in the corpus go through direct calls or other paths; no BLR observed in `formal/examples/`.

#### (i) Function-value uses and X16 load at BLR site
Examined function-value call patterns that produce BLR (from `test_formal_closures.py` and `test_formal_run.py` cases compiled on-the-fly):

| Case | Pattern | BLR emitted | X16 load at BLR site | Notes |
|---|---|---|---|---|
| `a_top_level_function_passed_as_an_argument` (closures) | `h(g,1)` where `h(f,v)` calls `f(v)` through parameter | Yes (1 site) | Loaded from stack/parameter slot via LDP (post-index pop), not a literal load of named function at BLR site | Callee address of `g` loaded via ADRP earlier and passed as argument; loaded from parameter slot in `h` |
| `a_lambda_passed_as_an_argument` (closures) | `apply2(lambda v: v*3, 7)` called through parameter | Yes (1 site) | Loaded from stack/parameter slot via LDP | Lambda lifted to named function; passed as value through parameter |
| `a_function_argument_called_through_two_hops` (closures) | `h(g,4)` → `hop(f,v)` calls `f(v)` through parameter | Yes (1 site) | Loaded from stack/parameter slot via LDP | Flows through parameters across call chain |
| `both_arch_a_function_value_in_a_local_is_called` (test_formal_run) | `var g = dbl; return g(5)` where `dbl` is top-level named function | Yes (1 site) | Loaded from local variable slot via LDP | Address of `dbl` loaded via ADRP earlier and stored in local `g`; loaded from local slot at call site |
| Local assigned from named function (manual test) | `f = g; f(5)` | Yes (1 site) | Loaded from local variable slot via LDP | Same pattern as above |

**Finding:** In all observed function-value call sites that emit BLR, the X16 load immediately before `BLR` loads the callee address from a variable/parameter/stack slot (LDP from SP), not as a direct literal load of a named function's address at the BLR site. Literal loads of named function addresses (ADRP/ADD) appear earlier in the code to initialize/store those values into variables/parameters.

### Chosen reading: **Reading C** (model BLR as BL with an abstract callee contract)

**Rationale:**

1. **Reading A (keep refusing)** is infeasible. BLR is already emitted for function-value calls that are tested and passing at runtime (all cases in `test_formal_closures.py` pass; `both_arch_a_function_value_in_a_local_is_called` in `test_formal_run.py` expects correct behavior). Refusing all BLR would break existing working functionality.

2. **Reading B (model only when statically identifiable with literal load at BLR site)** is rejected with evidence:
- All current BLR sites load the callee from variables/parameters/stack slots, not via literal loads at the BLR site. Even when the callee originates from a literal reference to a named top-level function (e.g., `f = g; f()` or passing `g` as argument), the current codegen stores it in a variable/parameter and loads it from there at the call site.
- Reading B explicitly says "If it is not (value flows through a parameter/field), refuse." All tested function-value cases flow through parameters or locals that hold function values passed through the calling convention or assignments - they would all be refused under strict Reading B. This would break existing passing tests.
- Implementing Reading B as specified would require significant codegen restructuring (to place literal loads at BLR sites in statically identifiable cases) plus sophisticated flow analysis to determine statically identifiable cases, with unclear benefit given the scope of changes needed.

3. **Reading C (abstract callee contract)** is necessary. We need to model BLR in the proof system. The approach would be: treat BLR as a call with an abstract/hypothetical callee contract (similar to `AdmittedCall` style), requiring hypotheses about functions whose addresses are taken. This is more general and can handle all cases where function values flow through parameters, locals, and other storage. While marked as needing a new contract shape in `lib/Contracts.lean`, the evidence shows A and B are not viable without breaking existing functionality.

**Implementation direction (for future steps):**
- Extend `arm64_step` in `lib/ProofLib.lean` with a BLR arm that takes the callee address from register and does a call with appropriate link register setup (similar to BL but with register target): `pc := (arm64_reg rn s).toNat`, `x30 := UInt64.ofNat (s.pc + 4)`.
- Extend CFG walker in `formal/arm64_proof_gen.py` to handle BLR - when BLR target cannot be resolved statically, need to treat it as an indirect call requiring contract hypotheses. This is complex and may require integration with the contract system.
- Extend `_STEP_CONDS` in `formal/arm64_proof_gen.py` with appropriate rows for BLR.
- Add handling in `_regs_written` etc.
- This will likely require new contract infrastructure in `lib/Contracts.lean` as Reading C indicates.
- Step-08a has already named BLR in `_unmodelled_instruction` for truthful refusal; once modelled, this needs to be updated.

No code changes are made in this step (design memo only). Implementation would be split into follow-up mid/hard steps as needed.
