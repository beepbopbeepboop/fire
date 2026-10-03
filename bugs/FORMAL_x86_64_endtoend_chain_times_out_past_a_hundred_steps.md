# the x86-64 end-to-end chain cannot close past about a hundred steps, so the first program with a stack argument is unprovable

**Area:** FORMAL (the x86-64 end-to-end prover). **Status: OPEN — measured
twice, and the two boundaries it names are separate.** Found 2026-10-02 while
finishing the SysV stack-argument convention's proof half
(`bugs/FORMAL_x86_64_stack_argument_past_the_twentieth_needs_a_disp32_lemma.md`,
deleted with its fix — the lemmas it asked for are in `lib/X86.lean` and wired in
`formal/x86_64_endtoend_test.py`).

**This is a limit of the PROVER, not of the compiler.** The 24-argument call it
blocks builds, runs and answers correctly on both architectures
(`both_arch_twenty_four_arguments_arrive` in `test_formal_run.py`: `241`, on
arm64 and on x86-64). Nothing here is a wrong answer; it is a chain that will not
be closed.

## What I ran

A 24-argument program — the width that forces the callee's stack-argument loads
through a four-byte displacement, and therefore the first program in the corpus
whose path uses `mov_r64_rm64_disp32`:

```
def wide24(a0: int, ..., a23: int) -> int:
    return a23 + a20 * 10 + a6

def main() -> int:
    var x = wide24(1, 2, ..., 24)
    return 0
```

```
$ python3 formal/x86_64_endtoend_test.py .tmp/w24np.mojo
w24np   value:     -  (branches: call_rel32)
  terminates: FAIL error: (deterministic) timeout at `whnf`, maximum number of
```

Two things had to be true before that run could even be reached, and both are
now fixed on this branch:

| boundary | what it was | what it is |
|---|---|---|
| `_body`'s lower bound | `entry`, so a callee the compiler emitted BEFORE its caller was outside the decoded range and the tree stopped on the call — reported with the message a recursion gets | still `entry`; `emit` (the value theorem) chains the decoded instructions LINEARLY, so a wider range would prove the theorem about the trampoline. The fix belongs in `emit`, which needs the tree |
| `_tree`'s loop test | `depth > 64`, one frame per instruction, so a straight-line function of 65 instructions was "a loop" | a revisited address; the length limit is now the interpreter's own recursion limit, with `RecursionError` caught to keep "no tree" graceful |

What is left is the third boundary, and it is the one that actually blocks:

## The closing `simp` runs out of heartbeats at about 130 steps

The path through a 24-argument call is ~130 instructions: 24
`mov $imm; sub $16, %rsp; mov %rax, (%rsp)` triples in the caller, then the
callee's 24 `mov r11, [rbp + 16 + 8k]` loads and their spills, then the
arithmetic. The chain is fine — every step goes through, no side condition is
admitted — and the LAST step (`hrip`, one `simp` over every successor equation
on the path) is what dies:

| budget | verdict | wall time |
|---|---|---|
| `maxHeartbeats 4000000` (the constant in `_header` today) | `(deterministic) timeout at whnf` | 6m18s |
| `maxHeartbeats 13000000` (100,000 per step, scaled like `maxRecDepth`) | `(deterministic) timeout at whnf` | 27m50s |

**Tripling the budget cost 4.4x the time and bought nothing**, so the closing
step is worse than linear in the path length and scaling the constant is the
wrong lever. That is the measurement that decides the next step: it is not "raise
the budget again".

The longest example in the corpus is 44 steps (`bitops`, which is why 4,000,000
was enough when it was chosen), so the constant has been right for every program
in the tree and wrong for the first one outside it.

## The exact next step

The closing `hrip` is `simp [hs0 … hsN, …]` over N successor equations, where
each `hsN` is a full-structure update. Three things are worth trying, in this
order, and each is separately checkable against the run above:

1. **Split the `rip` fact by the memory separation instead of by `simp`.** The
   `hrax` closing fact already has a shape that works — `try (simp […]) <;>
   first | decide | omega` — and `hrip`'s problem is that `simp` has to
   normalise every field of every intermediate state before `rip` reduces.
   A `have` per step ("`rip` is not any address in `N…m`", closed by `omega`
   against the literal successor) turns one quadratic pass into N linear ones.
   The rewriting key is already in the file
   (`mem_read_bytes_write_above`, and `repeat rw [key …]` for the peel), so the
   ingredients are present.
2. **If that is not enough, index the chain.** `x86_exec_go_exit_step` is applied
   once per step with `simp [hsN]`; a single `Nat → X86State → Option X86State`
   fold over the successors would replace the chain of N rewrites with N
   applications of one function, at the cost of the state being a term rather
   than a variable (which is what `emit`'s docstring says it went away from, for
   `maxRecDepth` reasons — so this is a trade, not a free win).
3. **Make the caller's stores cheaper, not the prover.** 24 immediates become 72
   instructions because each argument gets `mov $imm; sub $16, %rsp; mov %rax,
   (%rsp)`. An emitter that reserved the whole outgoing area ONCE and then wrote
   `mov %rax, disp(%rsp)` would put a 24-argument call at ~60 steps, inside the
   budget — and it is a smaller change than either of the above. It is also the
   one that would need `lib/X86.lean`'s and the generator's opinion, because it
   changes what is emitted rather than what is proved.

**And the half that is not about the prover at all**, so it is a separate piece
of work and not a step above: the AST bridge cannot express the call, so the
VALUE of a 24-argument call cannot be proved even once the chain closes.
`MojoExpr.call` carries ONE argument and `evalExpr` computes `callFunc name
(evalExpr arg env)`, so the generated `ast` for a 24-argument call is a
one-argument call, `eval_eq_mojo` is FALSE, and the build fails with `⊢ False`
at the `simp +decide` — measured, with the generated text in
`bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md`. That doc's steps are
the right ones and it is a `lib/ProofLib.lean` change; this doc only records
that the chain is not the only thing between here and a proved 24-argument call,
so nobody closes the chain and declares the convention proved.

## What is landed for the convention, so the next reader knows what is not missing

* `lib/X86.lean`: `x86_step_mov_rm64_mem_disp32` (the callee's load),
  `x86_step_mov_mem_sib_disp8` and `x86_step_mov_mem_sib_disp32` (the caller's
  two stores into the outgoing area — they are SIB forms because `[rsp + disp]`
  has no non-SIB encoding, and every argument past the register file uses one).
* `formal/x86_64_endtoend_test.py`: the three `_FORMS`/`_SUCCS` rows and the
  `_resolve` branch for the SIB pair.
* `formal/x86_64_model_coverage_test.py`: applicability rows for the disp32
  load, at `+128` (the smallest displacement that reaches that encoding) and at
  `-0x410` (the sign), plus the `dst`/`dst < 16` hypotheses the memory loads
  need, which nothing checked before.
* `test_formal_run.py`: `both_arch_twenty_four_arguments_arrive` — built and run
  on BOTH backends, `w24=241`.
* `bugs/FORMAL_x86_64_step_lemma_cqo_states_cdq.md` (deleted): `lib/X86.lean`
  did not elaborate at all, so no `--formal` build with a proof ran on either
  backend. Fixed, and `formal/x86_64_endtoend_test.py`'s `cqo` SUCCESSOR was
  carrying the same stale `x86_sign_extend32` the lemma did.