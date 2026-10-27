# FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open: the theorem
# for `a // b` with a symbolic `b` is ADMITTED **and false**, so no `simp` closes it

**Area:** FORMAL, arm64 — `lib/ProofLib.lean`'s `fdiv64` zero-divisor guard
against `formal/arm64_codegen.py`'s div0 arm (`movz x0, #1; movz x16, #1;
svc #0x80`), reached through `formal/arm64_proof_gen.py`'s terminal value flow.
**Status: NOT FIXED, and §0 is the measurement that says the fix this doc
proposed CANNOT work.** The next step below has been applied verbatim and
traced; the residual goals are byte-identical with and without it, and the
residual is the false goal `1 = 0`. The root cause is one level below the one
filed: **`fdiv64`'s divisor-is-zero arm says `0` and the machine leaves `1`**,
and it does not settle the argument either — arm64 passes the exit status in
`x0` and x86-64 passes it in `rdi`, so the word the run observes at the exit is
1 on one backend and 0 on the other, and a shared `fdiv64` cannot state both.
Predates the floor correction; found 2026-10-04 on `work/formal16-4`,
re-measured 2026-10-04 on `work/formal27-1`. **§0 is no longer REACHABLE
through `a // b` on the current tree, and the defect is not fixed — the route
is gone.** `_emit_exit` opens with `fflush(NULL)` (`e77131d5`), the div0 arm is
its one exit, and ONE unfollowable call silently restates the universal theorem
as `q_reaches_call_at_…` with `prop := True` instead of raising — so the walk
emits no terminal value flow and there is no residual to read. The three rows of
`test_formal_call_proof_gen.py::TestTheZeroDivisorGuardAgainstLean` that measured
this are red for exactly that reason, and
`bugs/FORMAL_one_opaque_flush_silently_replaces_the_universal_theorem.md` has the
measurement, the three-way taxonomy of what the generator does with 0 / 1 / ≥2
opaque calls, and the next step. Read that one first; the three options in "The
exact next step" below are still the right three, but option 1 is now a claim
about a block the walk does not walk at all, which moves option 2 from third to
first.

## Status 2026-10-27 (this tree): the state re-verified — the route is still gone,
## and the class is still blind by name

Re-ran the classes this doc names as its measurement, in one run:

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 -m unittest \
    test_formal_call_proof_gen.TestTheZeroDivisorGuardIsAFalseGoal \
    test_formal_call_proof_gen.TestTheZeroDivisorGuardAgainstLean \
    test_formal_call_proof_gen.TestTheDiv0FixtureHaltsAtTheCompilerTrap -v
Ran 8 tests in 146.519s
FAILED (failures=5)
```

All five failures are the three rows of
`TestTheZeroDivisorGuardAgainstLean` (its two-spelling subTests counted
separately), and every one fails with the class's own named blindness rather
than with a diagnosis: `the generator SUBSTITUTED q_compiles_correctly_universal
with the announced reachability theorem (q_reaches_call_at_…) … there is no
all_goals (first | done | sorry) in the tail for tail.replace(_ADMIT, _TRACE) to
patch, so this class cannot trace the div0 residual until the walk can discharge
a call on a conditional path`. That is the Status above — "the three rows … are
red for exactly that reason" — re-measured, and it is the same count the
sibling's 2026-10-12 re-measurement recorded (3 tests, 5 subTest failures).
The five Lean-free rows pass: `TestTheZeroDivisorGuardIsAFalseGoal` keeps the
defect itself pinned (fdiv64's div0 arm is the literal `0`; `10 // 0` leaves the
image with status 1 and prints nothing, both backends; the fixture's outcome is
the announced substitution rather than a silent empty tail; and the `// 4`
literal-divisor image still carries both `q_compiles_correctly_universal` and
the walk terminal's admission), and `TestTheDiv0FixtureHaltsAtTheCompilerTrap`
keeps the substitution pinned (no universal theorem,
`theorem q_reaches_call_at_0x100000504`, zero `_ADMIT`). Nothing in "The exact
next step" moves: item 1 of the sibling's step list — this doc's option 2, the
divergence treatment, a change to the theorem's shape — is still the step, and
it is still held by
`FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`
through `FORMAL_one_opaque_flush_silently_replaces_the_universal_theorem.md`.
The three rows stay red and unmarked on purpose.

## Status 2026-10-13 (`work/formal295-docs`): the unreached-residual doc is absorbed here

`FORMAL_the_div0_residual_goal_is_no_longer_reached_by_the_terminal_value_flow`
(named without the `bugs/` prefix because the file is not there any more — it is
deleted with this note), filed 2026-10-05 on the `work/formal28-2` merge tree,
asked whether `fdiv64`'s div0 residual had CLOSED or merely become UNREACHED,
and guessed at the merge's `bv_decide` growth as the cause. Re-measured on this
tree through the generator (no Lean needed for the shape): the fixture BUILDS —
the stack-floor `getrlimit` is a stub read now, not a second program call — and
the generated file has **no `q_compiles_correctly_universal` at all**: the walk
stops at

    /- CALL BOUNDARY.  This function calls out of the image: the `BL` at
       0x100000504 branches to 0x100000870, which is not in the code the model
       was given …

`0x100000504` is this doc's own div0 arm (`_emit_div_shift_pow`'s `fflush` on the
raise path), so the answer is **UNREACHED**: no terminal value flow is emitted,
no `⊢ 1 = …` residual exists to be read, and nothing about the false theorem has
changed. That is this doc's §0 and
`bugs/FORMAL_one_opaque_flush_silently_replaces_the_universal_theorem.md`'s
three-way taxonomy; the earlier doc's cause hypothesis was wrong, and its doc is
deleted with this note, exactly as its own step 3 (fail on UNREACHED → fold into
this doc) instructed.

## 0. What the measurement is, and what it refutes

**Half of the doc's stated blocker is gone, and which half matters.** The claim
was that the next step "cannot be made from a branch that holds 8 GB" because
`lib/ProofLib.olean` "has to be rebuilt for any proof in this tree to check".
For READING the residual that is no longer true: `formal/lean.py::ensure_library`
publishes the library out of `~/.gmojo/cas` instead of building it, so the
whole measurement below ran at **0.1 GB / 0.7 s** for the library and **3.2 GB /
61-70 s** for each proof, through `formal/lean.py::run_lean`. For CHANGING
`lib/ProofLib.lean` it is still exactly as stated, and re-measured: one comment
line added to the library changes its source digest, forces the rebuild, and
`memcap: BREACH 8.0 GB > 8.0 GB ceiling (100%), 2 procs -- killing lib` after
**1 m 48 s**. So option 1 of "The exact next step" below is not a light
worker's job even with the CAS to read from, and whoever takes it needs a
heavier budget than this one had.

**The doc's diagnosis of the MECHANISM is wrong, and the error is worth
recording because the sentence reads as though the fix were mechanical.**
"`hc_4` is exactly the fact the model's guard needs … It is simply not in the
terminal `simp only` list" — and `hc_{bi}` is indeed in scope and is indeed the
same statement. Adding it does nothing, for two reasons, and neither is visible
without reading the residual:

1. **`hc_{bi}` is stated over the REGISTER and the goal is over the PARAMETER.**
   The emitted fact is `hc_4 : arm64_reg 1 s_4 = 0`; the terminal goal is about
   `n1`. Connecting them takes `hsid_2`/`hsid_0` (which rewrite the STATE) and
   the block's own `q_b*_qS`/`q_b*_qT` definitions (which compute
   `arm64_reg 1`), and `simp only` does not compose one member of the simp set
   with the rest of the set in that direction. So the guard does not reduce even
   where reducing it is all that is missing.
2. **The residual is not the unreduced `if` this doc quotes, and it is FALSE.**
   Replacing the walk terminal's `all_goals (first | done | sorry)` with
   `all_goals (first | done | (trace_state; sorry))` — which is how a residual is
   *read*, and reading it is the whole of the measurement — leaves twelve goals
   for `def q(a, b): return a // b`, two per terminal value flow:

   ```
   ⊢ 1 =
       if n1 = 0 then 0
       else
         sdiv64 n n1 -
           ((if n - sdiv64 n n1 * n1 = 0 then 0 else 1) &&&
             if n - sdiv64 n n1 * n1 ^^^ n1 ^^^ 9223372036854775808 < 9223372036854775808 then 1 else 0)
   ⊢ n1 = 0 →
       sdiv64 n n1 - (…) = 0
   ```

   The first is `1 = (fdiv64's value)`, and at `n1 = 0` the right-hand side is
   `0`. **So the admitted statement is not merely unproved — it is false**,
   which is the class of defect
   `bugs/FORMAL_a_conditional_expression_has_no_value_in_the_semantic_model.md`
   §0 item 2 is about ("`_expr_ast` refuses the construct rather than fabricating
   `MojoExpr.int 0` … refusing rather than emitting a mirror of a different
   program"), and it is why `simp` cannot close it: Lean's kernel will not accept
   a proof of `1 = 0`.

**Where the `1` comes from, and why it is not a one-character library fix.**
`formal/arm64_codegen.py::_emit_div_shift_pow`'s `div0_label` arm is

```
    self.asm.label(div0_label)
    self.asm.emit(encode_movz_xd_imm(0, 1))     # movz x0, #1
    self.asm.emit(encode_movz_xd_imm(16, 1))    # movz x16, #1
    self.asm.emit(encode_svc(0x80))
```

— the arm64 exit syscall takes its status in `x0`, so the word the walk reaches
at the exit pc is `1`. `formal/x86_64_codegen.py`'s div0 arm is
`self._emit_call_exit(1)`, which is `mov rdi, 1; mov rax, 0; call exit` — the
status goes in `rdi` and **`rax` is 0**. So the word the run observes on the div0
path is 1 on arm64 and 0 on x86-64, and `lib/ProofLib.lean`'s shared `fdiv64`
(`if b = 0 then 0 else …`) is right about one of them. Measured, both backends,
from the source: `10 // 0` builds, prints nothing and exits 1
(`test_formal_call_proof_gen.py::TestTheZeroDivisorGuardIsAFalseGoal`).

**And the concrete half of this program was already red before any of this.**
The generator pins `x1 := 0` in every concrete run test, so `q_runs_test` and
its four siblings state `run_result_exit {… x0 := 10, x1 := 0} … = mojo 10 0` —
a division by zero on purpose — and Lean's `native_decide` answers `is false`
for all of them and for `q_compiles_correctly`. That is a second, independent
symptom of the same disagreement and it is the one a reader meets first.

**What this does NOT do.** It changes no generator and no library file. The
three ways out are a project each and they are listed under "The exact next
step" below; what is landed is the measurement and the pins, so that none of the
three is built on the refuted premise.

**The transcript below is from `work/formal27-1`, where it was true.** On the
current tree the third and fourth lines are FAIL and the reason is that the
program no longer emits the walk terminal they read — the two Lean-free rows
above them still pass, because the disagreement they assert is in the text and
in the image and neither moved. Treat it as what was measured, not as what a
reader will see:

```
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_call_proof_gen.py TestTheZeroDivisorGuard
test_the_models_zero_divisor_arm_is_a_literal_zero ... ok
test_a_zero_divisor_leaves_the_image_with_status_one ... ok
test_the_false_goal_survives_the_documented_next_step ... ok
test_the_residual_is_the_same_with_and_without_the_branch_fact ... ok
```

## What I ran (when this was filed)

```console
$ cat .tmp/fd/symb.mojo
def q(a, b):
    return a // b
$ python3 .tmp/fd/genonly.py build --formal -o .tmp/fd/symb.out --backend=arm64 .tmp/fd/symb.mojo
Proof: .tmp/fd/symb_proof.lean
$ grep -n "terminal value flow" -A 2 .tmp/fd/symb_proof.lean | head -3
        -- terminal value flow: (s_7).x0 = mojo n n1
        have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
        simp +decide only [h8, mojo, q_go, hsid_6, hsid_4, hsid_2, hsid_0, q_b0_qS0, …]
```

and, in the same file, the divide-by-zero branch the walk takes:

```lean
      have hcbz_4 : arm64_step s_4 q_code = some
          (if arm64_reg 1 s_4 = 0 then ({ s_4 with pc := 4294968148 } : Arm64State)
                                 else ({ s_4 with pc := 4294968096 } : Arm64State)) := …
      by_cases hc_4 : arm64_reg 1 s_4 = 0
```

## Why the goal cannot close

`hc_4` is exactly the fact the model's guard needs — on the path the walk
follows, `arm64_reg 1 s_4 = 0` is FALSE — and it is **in scope**: it is the
`by_cases` that opened the branch the rest of the proof sits in. It is simply
not in the terminal `simp only [...]` list, which carries `h8`, the model, the
`hsid_*` chain, the `qS`/`qT` definitions and the value simp set, and nothing
that mentions a branch condition.

So the goal after that `simp` is

```lean
    … = if n1 = 0 then 0 else fdiv64_unfolded n n1
```

with `n1` a parameter, and `simp only` cannot reduce an `if` whose condition is
a variable. What is left is `all_goals (first | done | sorry)` — the walk
terminal's admission — so the theorem is stated and not proved.

**§0 supersedes the last three sentences of that section.** The `if` in the
residual is `fdiv64` unfolding, not a condition `simp` was asked to decide, and
the goal it sits in is false.

**A literal divisor is why nobody measured this.** `formal/examples/udivmod.mojo`
— the corpus's only division example, and the slowest legitimate proof in the
tree at 297.8 s — divides by `7`, and `decide` disposes of `if 7 = 0`. So the
shape has never been in the corpus, and the run suite cannot see it either:
every case in `test_formal_run.py` that divides does it by a literal or by a
value that is already in a register (`neg_div_rem`'s `a / 2`).

## The exact next step

The old one — "put the branch fact in the terminal value flow's `simp only`
list" — is **refuted by §0** and is kept above only so nobody re-derives it.
Three ways out, and they are very different amounts of work:

1. **Make the model say what the machine leaves, per backend.** arm64's div0
   arm leaves `x0 = 1`, so arm64's `q_go` wants `if b = 0 then 1 else …` and
   x86-64's wants `0`. The generators already emit a per-backend `mojo`/`_go`
   layer, so the place is `_go`'s renderer in
   `formal/arm64_proof_gen.py` / `formal/x86_64_proof_gen.py` rather than
   `lib/ProofLib.lean`'s shared definition — changing a shared library
   definition to be true of one machine is the same class of defect as this
   doc's own subject. **It is a claim about a path the SOURCE never returns
   from** — the image leaves — so it is a modelling decision and not a
   correction, and it should be argued rather than assumed.
2. **Stop claiming a value on the div0 path at all.** The source raises
   `ZeroDivisionError`; the image exits 1; a formal value is one 64-bit word
   with no way to say "no value". The honest shape is for the walk to treat a
   div0 block as a DIVERGENCE — it is `info["compiler_traps"]`'s nearest
   neighbour, and `test_formal_call_proof_gen.py::TestCompilerTrapIsNotAProgramCall`
   is where that mechanism is pinned — and for the universal theorem's
   statement to admit that the run may exit. That is a change to the theorem's
   SHAPE, not to a tactic, and it is the only one of the three that puts no
   fiction in the model.
3. **Refuse the division** when the divisor is not provably non-zero.
   **Measured and rejected**: `formal/hostmods/math.mojo` (9 sites),
   `operator.mojo` (7), `time.mojo` (1) and `struct.mojo` (1) all divide by a
   name, and `test_formal_hostmods_census.py` builds all 72 rows of them today,
   so this is a regression in the build for a defect the corpus does not
   exercise.

While there: the floor correction is the other half of the same terminal `simp`
list and is already accounted for — `//` floors and `%` takes the sign of the
divisor on both backends (`model.division_floors` is the one decision both
emitters ask), so the term in that list is the corrected one.

## Reproducing

The RESIDUAL, through `formal/lean.py::run_lean` and nothing else:

```console
$ python3 .tmp/fd/genonly.py .tmp/fd/symb.mojo .tmp/fd/symb.out arm64
Proof: .tmp/fd/symb_proof.lean
# neutralise the concrete run tests (they divide by zero by construction) and
# trace the walk terminal's residual instead of admitting it — see §0
$ python3 tools/memslot.py --gb 8 --label probe -- python3 .tmp/fd/probe3.py \
      .tmp/fd/symb_trace.lean
rc=0 wall=61.2s peak=3.24GB exceeded=None
   ⊢ 1 =
       if n1 = 0 then 0
       else
         sdiv64 n n1 - ((if n - sdiv64 n n1 * n1 = 0 then 0 else 1) &&& …)
   ⊢ n1 = 0 →
       sdiv64 n n1 - (…) = 0
```

and the same file with the doc's next step applied to all eight terminal value
flows (`.tmp/fd/patch.py`, which is the `_with_branch_facts_in_the_terminal_flow`
helper in `test_formal_call_proof_gen.py`): **the same twelve goals, byte for
byte**. That equality is the refutation, and
`test_the_residual_is_the_same_with_and_without_the_branch_fact` is what keeps
it from rotting back into a plan.

The library the proofs need comes from the CAS rather than a build:

```console
$ python3 tools/memslot.py --gb 8 --label lib -- python3 -c \
    "import sys; sys.path.insert(0,'.'); from formal import lean; \
     lean.ensure_library(lean.find_lean('.'), 'lib'); print('library ok')"
memcap: done, peak 0.0 GB across up to 1 procs (ceiling 8.0 GB), child exit 0
library ok
```