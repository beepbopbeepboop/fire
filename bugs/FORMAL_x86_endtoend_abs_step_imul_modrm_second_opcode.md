# FORMAL: the abstract walk decodes `imul`'s ModRM from the second opcode byte, so it writes the product to the wrong register

## Symptom, measured

    python3 -m formal.x86_64_endtoend_test formal/examples/annot_params.mojo
      annot_params  terminates: FAIL lean exited 1: error: Tactic `decide` proved …

Nine examples carry an `imul r64, r64/m64` (`REX 0F AF /r`) on the proved path
and every one of them fails the same way: `annot_params`, `call_helper`,
`chain`, `localmul`, `mixed_width`, `multi_export`, `pair`, `call_both_arms`,
`elif_call` (measured 2026-11-19, full run `PASS=68 FAIL=13 of 68`; of the
thirteen, these nine are this bug, two more overlay it — see the sibling docs).
Each generated file dies on the SAME pair:

    .tmp/annot_params_proof.lean:1170:8: error: Tactic `decide` proved that the proposition
      False
    is false
    .tmp/annot_params_proof.lean:1202:8: error: Expected type must not contain free variables
      (x86_split128 (x86_signed s19.rax * x86_signed 0)).snd =
        x86_sign_extend64 (x86_split128 (x86_signed s19.rax * x86_signed 0)).fst

The first is the LIE, the second is its downstream symptom.

## The lie

`annot_params` is `n * m + 1` with `m = 0` at the entry. The step at
4294968555 is `49 0F AF C3` = `imul rax, r11`; the model's own successor names
the registers the encoding says:

    hs20 : s20 = x86_set_flag4 { x86_set_reg s19 0 (x86_get_reg s19 0 *
              x86_get_reg s19 (3 + x86_rex_b 73)) with rip := … } …

dst = reg field 0 + REX.R = 0 = rax, src = rm field 3 + REX.B = 11 = r11.
The file then asserts, as `hval20`,

    s20.rbp = 0

which is FALSE: `hval19` (proved, one step earlier) states
`s19.rbp = 18446744073709551592` — the frame pointer — and the imul writes
register 0, so `s20.rbp = s19.rbp ≠ 0`. Lean reduces the goal to
`18446744073709551592 = 0`, `decide` answers `False`, and the file dies.

## The root cause

`_abs_step` (the walk-side constant propagation in
`formal/x86_64_endtoend_test.py`) decodes the ModRM once, generically, out of
`raw[2]`:

    rex = raw[0] if raw[0] & 0xF0 == 0x40 else 0
    modrm = raw[2]
    …
    dst, src = reg + rex_r, rm + rex_b

For `49 0F AF C3` that reads `raw[2] = 0xAF` — the SECOND OPCODE, not a ModRM:
reg = 5, rm = 7, and with REX `0x49` (R and B both set) the walk computes
dst = 5+8 = 13 = **rbp**, src = 7+8 = 15 = **r15**. The walk then does what its
`imul_r64_r64` branch says — compute the product and `st.put(dst, …)` — and
writes `rbp ← rbp_old * r15_old`. With the initial register file all zeros
(except RDI/RSP) and the frame pointer alive, that is `rbp ← 0`, exactly the
emitted lie; the flags it computes (`of_ = _imul_ovf(rbp_old, 0) = False`) are
concrete constants that happen to look like no-overflow.

`_resolve`'s own `imul_r64_r64` branch reads the ModRM out of `raw[3]` and
carries a comment recording exactly this off-by-one — "the default fills in
`0xaf &&& 7 = 7` and the step lemma is applied with the wrong source
register" — and `movsx_r64_r8` in the walk got the same correction. The walk's
`imul` branch was left on the generic decode: the model side was fixed, the
walk side was not.

## Why the second error is a symptom, not a second bug

The `JNO`-guard after the imul (`x86_cond 0 s = s.of_`) is DECIDED by the walk
because the misdecode handed it concrete flags; the decided arm emits a
`hdec` fact — `x86_imul_ovf s19.rax 0 = false` — whose proof is
`simp […] <;> decide`. `s19.rax` is `n`, the theorem's quantified input, so
`decide` cannot fold `x86_split128 (x86_signed n * 0)` and reports the free
variable. With the walk corrected, the imul branch takes its own
`a is None or b is None` arm (`rax = n` is unknown there), the guard is
UNDECIDED, the tree FORKS with `by_cases`, and no `hdec` fact is emitted at
all — the emitter emits decided-arm proofs only.

## The unsound part

A decided guard is a CLAIM about the machine: the emitter's own comment says
"a decision the abstract machine gets WRONG leaves a goal that is false, and
Lean rejects the file" — the elaboration failure is the safety net doing its
job. But the misdecode also SHRINKS the tree: the overflow arm is never built,
so the theorem statement names only the normal-path halt. Measured on
`call_helper` (`helper(a) = a * 3`, entry callee, the imul is `n * 3`):

    theorem terminates (n : UInt64) :
        (x86_exec_go_exit (X86State.init n 4294968411) rc 4294968617 100000).isSome = true

ONE disjunct — the outermost `ret`. For `n ≥ 2^62` the model sets OF, takes
the overflow arm, and ends at the error `call` (4294968588, in
`info['compiler_traps']`): the statement is FALSE for those inputs. The file
never got that far (it dies at the lie), so the false statement is latent —
but it is the emitter's own output, and the fix below changes WHAT IS CLAIMED,
not just how it is proved.

## The fix, measured

In the scratch worktree at `822c88b9d` (`.tmp/prefix`), the walk's `imul`
branch re-derives the fields the way `_resolve` does:

    modrm = raw[3]
    reg, rm = (modrm >> 3) & 7, modrm & 7
    dst = reg + (8 if rex & 4 else 0)
    src = rm + (8 if rex & 1 else 0)

and the generated files then:

    call_helper  rc=0 errors=0   (statement: 4294968588 ∨ 4294968617 — both arms)
    annot_params rc=0 errors=0   (statement: 4294968598 ∨ 4294968696 ∨ 4294968729)
    chain        rc=0 errors=0
    localmul     rc=0 errors=0
    mixed_width  rc=0 errors=0

The `hval` lie is gone (the walk puts `None` in rax and touches no other
register), the guard forks, and the statements gain their overflow disjuncts.
In the four examples that overlay other bugs (`multi_export`, `pair` — the
fork-hval cite, sibling doc; `call_both_arms`, `elif_call` — the maxRecDepth
ceiling, sibling doc) this pair is the REMAINING error after those siblings
are patched (measured on the patched files: only the decide-False +
free-variable pair left).

## Next step

1. Land the walk correction above in `formal/x86_64_endtoend_test.py::_abs_step`,
   mirroring `_resolve`'s branch and comment (one source of truth: the bytes).
2. Add the five pure examples to whatever walk-side check
   `formal/x86_64_model_coverage_test.py` gains, so a form the walk decodes
   differently from `_resolve` is red there rather than a file that dies.
3. Re-run the full suite: expect the nine examples off the failure list (or
   onto the memory-ceiling list, see the sibling doc for that class) and the
   marker count to move accordingly.

## Done when

None of the nine examples reports `terminates: FAIL` for this cause; each
`imul`-guard after a multiply by a quantified input FORKS (a `by_cases` in
the generated file) rather than deciding; and a statement the walk shrank
(the single-disjunct `call_helper` above) is no longer emitted.
