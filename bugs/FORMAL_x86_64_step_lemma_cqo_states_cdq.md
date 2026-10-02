# `lib/X86.lean` does not elaborate, so EVERY `--formal` build with a proof fails on BOTH architectures

**Area:** FORMAL (the x86-64 machine model). **Status: OPEN — one line, and the
fix is measured below.** Found 2026-10-02 while implementing the SysV
stack-argument convention, which needed a working x86-64 proof path to be
verifiable end to end and does not have one.

This is a REGRESSION on `master`, and it is not mine: `lib/` is byte-identical to
`master` on the branch that found it (`git diff master -- lib/` is empty), and
the failure is in the LIBRARY build, before any program is involved.

## What I ran

```console
$ printf 'def main(n: Int) -> Int:\n    return n + 1\n' > .tmp/one.mojo
$ python3 tools/memslot.py --gb 8 --label prove-one -- \
      python3 fire.py build --formal --backend=x86_64 -o .tmp/p0 .tmp/one.mojo
build: proof check failed: proof library build failed:
  lib/X86.lean:749:59: warning: This simp argument is unused: …
  lib/X86.lean:1348:86: error: unsolved goals
```

The same command with `--backend=arm64` fails at the same line, and so does every
other `--formal` build on this tree. `lib/ProofLib.olean` exists; `lib/X86.olean`
does not, and cannot be made.

The goal, from a bare `lean lib/X86.lean -o …` with `LEAN_PATH=lib`:

```
⊢ (if 9223372036854775808 ≤ s.rax then 18446744073709551615 else 0) =
    if 9223372036854775808 ≤ UInt64.ofNat (s.rax.toNat % 4294967296)
    then s.rax ||| 18446744069414584320 else s.rax
```

## What is wrong: the step lemma states `cdq`, the model computes `cqo`

`x86_step_cqo` (`lib/X86.lean:1345`) claims

```lean
x86_step s code = some { s with rdx := x86_sign_extend32 s.rax, rip := m + 2 }
```

while the arm it is a lemma about (`x86_step_rex`'s `cqo` case) computes

```lean
some { s with rdx := x86_cqo s.rax, rip := rip + 2 }
```

`x86_sign_extend32` is `movsxd`/`cdq` — it returns `v` unchanged for every value
whose bit 31 is clear. `x86_cqo` is the sign extension of the whole 64-bit RAX,
which is what `cqo` is. The lemma states a DIFFERENT INSTRUCTION from the one the
model decodes, so the goal above is not closing and cannot be made to close by
proving harder: the two sides differ for every `rax` with bit 63 set.

**Where the divergence came from.** `da151f0c` ("`cqo` was `cdq` in the x86-64
model", 2026-10-02, merged with `work/formal3-3-r2`) added `x86_cqo` and
corrected the model's arm — that half was right, and it is the fix for
`FORMAL_default_int_type_typed_flag_collapse`'s `udivmod` half — but it left
`x86_step_cqo`'s STATEMENT naming `x86_sign_extend32`. Before that commit the
lemma matched the model and was true. Nothing else in the tree references
`x86_sign_extend32` in this position, so the statement is the whole of it.

## What it costs, measured

**Every `--formal` build with a proof fails, on both backends**, and the failure
is reported as `build: proof check failed: proof library build failed:` with the
real diagnostic buried under a page of "This simp argument is unused" warnings.
That is why `--no-prove` is in every formal build command in this repository and
why the x86-64 end-to-end job is `expect=`ed: `bugs/FORMAL_x86_64_end_to_end_proof.md`
was last re-measured on 2026-10-01, when `lib/X86.lean` still elaborated.

## The exact next step

Two lines, and MEASURED — this is not a suggestion, it is what I ran:

1. `lib/X86.lean:1348`, in `x86_step_cqo`'s statement: `x86_sign_extend32 s.rax`
   → `x86_cqo s.rax`. The model already computes that; the lemma has to say it.
2. The same theorem's `simp` set needs `x86_cqo` (and, if it does not close,
   `x86_msb` / `x86_trunc32`) added alongside `x86_sign_extend32`, because the
   new left-hand side is a definition the set does not unfold.

Verified on a scratch copy under `.tmp/` (this branch does NOT carry the change —
`lib/` belongs to another live worker):

```console
$ LEAN_PATH=lib lean .tmp/try/X86.lean -o .tmp/try/X86.olean   # both edits applied
$ echo $?
0                       # zero errors — the library elaborates
```

Without step 1 the goal above is what `simp` leaves, so step 2 alone is not a
fix; the order matters and the measurement is what establishes it.

Then re-run the two suites that name this lemma, because both assert things
about it and neither could have run while the library was red:

* `formal/x86_64_model_coverage_test.py` — `step_lemmas()` checks every step
  lemma's hypotheses are SATISFIABLE at a real encoding. That check passes on a
  lemma whose goal is false, which is why this went unnoticed: it was never run
  against a buildable library.
* `formal/x86_64_endtoend_test.py` — its table maps `cqo` to `x86_step_cqo`
  (`"cqo": ("x86_step_cqo", False, ["rip", "b0", "b1", "rex", "w"])`), so the
  lemma is load-bearing for the end-to-end theorem and a wrong statement there is
  a wrong ANSWER, not a missing proof.

**And then `FORMAL_x86_64_end_to_end_proof.md` needs re-measuring**, because its
status table (31 examples proved, 2 sorries) predates the model change that
broke the library, and `formal-x86-64-end-to-end-proof` is registered
`expect=` against it. Whether that marker is still honest is a question this fix
answers and nothing else does.