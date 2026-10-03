# FORMAL_x86_64_cqo_step_lemma_contradicts_the_model: `lib/X86.lean` does not compile, so every Lean-checking formal build fails

**Area:** FORMAL (x86-64 model), found from the `sweep5:module-state` claim while
running the narrow suites. **Status: OPEN — NOT MINE, not fixed, and not even
one-line-fixable without a decision.** Filed rather than fixed because
`lib/X86.lean` and the `FORMAL_x86_64_end_to_end_proof` doc are another
worker's area (`bug:FORMAL_x86_64_end_to_end_proof`), and because confirming
the repair needs a Lean run this worker is not permitted to spend.

**This is pre-existing, measured on `HEAD~2` as well as on the branch that found
it, so it is not a regression from anything in flight** — see "What I ran".

## What I ran

```
$ python3 test_formal_dylib.py
  ...
  FAIL  default path emits a checked proof
        default (prove) dylib build failed: target, x86_call_post, hcall,…]
$ printf 'def triple(n):\n  return n * 3\n' > /tmp/proved.mojo
$ python3 fire.py dylib --formal -o /tmp/proved.dylib /tmp/proved.mojo
exit 1
```

The test's own message is truncated to the last 400 bytes of a stream where Lean's
diagnostics interleave, so the failure looks like an `unusedSimpArgs` linter
note. It is not. The real diagnostic, from the direct run:

```
lib/X86.lean:1348:86: error: unsolved goals
s : X86State
code : Nat → UInt8
m : Nat
rex : UInt8
h_rip : s.rip = m
h_b0 : code m = rex
h_b1 : code (m + 1) = 153
h_rex : x86_is_rex rex = true
h_w : x86_rex_w rex = true
⊢ x86_cqo s.rax = if x86_msb (x86_trunc32 s.rax) = true then s.rax ||| 18446744069414584320 else s.rax
```

`153` is `0x99` in decimal, and the right-hand side is `x86_sign_extend32`'s body
(`lib/X86.lean:321`). So the goal is `x86_cqo = x86_sign_extend32`, and those two
`def`s are not the same function: `x86_cqo` (`:350`) extends **bit 63 of the
whole word**, `x86_sign_extend32` extends **bit 31 of the truncated word**.

## What I see

**The lemma is stale and the model is right, which is the opposite of the way
that reads.** `x86_step`'s `cqo` arm (`:408`) does

```lean
else if op = 0x99 && w then
  -- cqo: RDX = the sign extension of the whole 64-bit RAX.  `x86_cqo`, and
  -- NOT `x86_sign_extend32`: see its own docstring for what the difference
  -- costs on the very next instruction.
  some { s with rdx := x86_cqo s.rax, rip := rip + 2 }
```

and `x86_cqo`'s own docstring (`:336-349`) says why, with a measurement:
`cqo` is always immediately followed by `idiv`, which reads RDX:RAX as the
dividend, so a `cdq`-style bit-31 extension makes the model divide
`RAX * 2^64 + RAX`. On `formal/examples/udivmod.mojo` (`n = 10`, `n / 7 + n % 7`)
the answer is 4 and the model returned 7905747460161236410 — which is
`(10 * 2^64 + 10) / 7` truncated into 64 bits, plus the remainder.

That fix is commit `da151f0c`, "formal: `cqo` was `cdq` in the x86-64 model,
and the model generator refused nothing". **It changed the `def` and left
`x86_step_cqo`'s conclusion stating the old semantics**, so the theorem now
contradicts the definition it is about and Lean cannot prove it. (It is right
about the hardware, by the way: `cqo` sign-extends RAX's top bit into RDX, and
`cdq` is the 32-bit form — the docstring's reasoning is that `x86_cqo` is the
64-bit instruction, not that it is a different intent.)

**So the defect is one stale line in a lemma, and its blast radius is the whole
Lean layer.** `lib/X86.lean` is imported by the proof library
(`formal/lean.py`'s `ensure_library`, the `prooflib` step), so a library that
does not compile fails **every** build that typechecks a proof, not just the
x86-64 `cqo` path. Measured, on this tree, the suites that go red for exactly
this reason and nothing else:

```
$ python3 test_formal_dylib.py
  FAIL  default path emits a checked proof          (one case of 13)
$ python3 test_formal_short_circuit_cond.py
  FAIL  test_generated_proofs_typecheck_with_no_sorries (program='both')
  FAIL  test_generated_proofs_typecheck_with_no_sorries (program='either')
  FAIL  test_generated_proofs_typecheck_with_no_sorries (program='short_and')
  FAIL  test_generated_proofs_typecheck_with_no_sorries (program='short_or')
Ran 12 tests ... FAILED (failures=4)
```

Every one of those five failures carries `proof library build failed:
lib/X86.lean:…` in its message, and the case that names the *actual* error is
the direct run under "What I ran" — the suite messages are truncated to a
diagnostic tail, and which LINE they name varies with the output ordering, so
`lib/X86.lean:749` and `lib/X86.lean:1984` are the same single error seen
through two different tails.

`formal-dylib` is registered in `tools/suite.py` with **no** `expect=` marker, so
it is an undeclared red in the gate.
`test_formal_short_circuit_cond.py` is not registered at all (nothing in
`tools/suite.py` mentions it, and `python3 tools/suite.py --list | grep -i
short` is empty), so its four failures are a coverage hole rather than a gate
red — the same class
`bugs/TEST_registered_tests_in_no_bucket_never_run.md` is about. Worth knowing
when the fix lands: it is a suite that has been silently rotting for the whole
time this has been broken, and it is the one whose SUBJECT (short-circuit `and`/
`or` in a condition) is furthest from `cqo`.

## Why it was not noticed

`bugs/FORMAL_x86_64_end_to_end_proof.md`'s "forms wired since the last pass"
table lists `cqo | — (one half of udivmod's pair) | —` under forms that now
**have** a lemma — which is true (`x86_step_cqo` exists, and both
`formal/x86_64_model_coverage_test.py:395` and
`formal/x86_64_endtoend_test.py:300` name it as the lemma for the `cqo` form).
That row reads as "wired and proved"; the wiring is there and the proving is
not. The same doc records the `udivmod` WRONG answer as pre-existing and
written down twice, and does not say that fixing it left the library
uncompilable — which is the only fact that would have shown up here.

## The exact next step

In `lib/X86.lean:1345-1355`, `theorem x86_step_cqo`: state what the model does.

* the conclusion's `rdx := x86_sign_extend32 s.rax` becomes
  `rdx := x86_cqo s.rax`;
* the proof's simp set drops `x86_sign_extend32` (nothing is left to unfold
  once both sides are `x86_cqo`) — `simp [x86_step, x86_step_rex, h_rip, h_b0,
  h_b1, h_rex, h_w]` is the shape of it;
* the comment above the lemma, which currently says "`cqo` sign-extends bit 31
  of RAX, not bit 7 or bit 15, so the two-byte and one-byte helpers above are
  the wrong ones and this is the one that applies", is describing the OLD
  semantics and has to be rewritten with the `:408` arm's reasoning: for the
  64-bit `cqo` the extension is of bit 63, and the reason is the `idiv` that
  follows rather than a choice among the three sign-extend helpers.

Then re-run `python3 test_formal_dylib.py` and `make gate`'s proof steps. Two
things to check while in there, because they are the same class of staleness and
the same commit is the likely place for both:

* `formal/x86_64_model_coverage_test.py:395` passes
  `("x86_step_cqo", "cqo", cqo, …)` — the coverage test asks whether the lemma
  EXISTS and is NAMED by the generator, which it still is, so it is green while
  the library does not compile. Anything structural in that pair of tests should
  also ask whether the library typechecks.
* the `unusedSimpArgs` / `unusedVariables` linter notes in the same log
  (`lib/X86.lean:1984` names an unreferenced `code` in
  `x86_call_return_slot_separated`) are warnings today. They are noise in a
  failing build and will need deciding separately once the error is gone.

## Scope

Not fixed here, deliberately: the file is another worker's claim area, the fix
needs a Lean run to confirm, and `lib/X86.lean` is not on the
`sweep5:module-state` claim's path. Nothing in `formal/model.py`,
`formal/arm64_codegen.py`, `formal/x86_64_codegen.py` or any `test_formal_*`
causes it — the same failure reproduces from a `git archive HEAD~2` extraction
with none of this branch's changes in it.