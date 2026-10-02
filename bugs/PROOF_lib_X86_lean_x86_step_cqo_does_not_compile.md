# `lib/X86.lean`'s `x86_step_cqo` does not compile, so EVERY proof path in the tree fails

**Area:** PROOF (the Lean side, `lib/`). Found 2026-10-02 on
`work/formal5-slice-env-random`, incidentally: every test that emits a proof
fails before it reads a line of its own source.
**NOT FIXED — it is one theorem in another area's file, and this worker did not
claim it.**

This is a file for a bug hit and not fixed, per the worker rules. It is here
because it is **not** the usual "a proof is missing" state and it hides itself:
every caller reports it as something else.

## What I ran

```
$ python3 -c "import formal.lean as L, os; L.ensure_library('lean', os.path.abspath('lib'))"
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

`git status --short lib/` is EMPTY on this worktree at `24068a01`, so this is
master's own state and not a local edit. `lib/ProofLib.olean` (28 MB) is present
and STALE: `ensure_library` re-checks currency inside its `flock`, decides to
rebuild, and the rebuild is what fails — so the `.olean` on disk is not a proof
of anything and the 27 MB is spent on nothing.

## What it looks like from every caller, which is the part worth knowing

Nothing says "the Lean library does not build". The three callers I hit each
surface a DIFFERENT thing, which is how I spent time on this:

| caller | what it printed |
|---|---|
| `formal/x86_64_model_test.py` | a `RuntimeError` whose text is the FIRST line of the warning stream: `…/lib/X86.lean:1984:55: warning: Variable name 'code' is not explicitly referenced.` — so the model test reports a *warning* as its failure |
| `test_formal_dylib.py`'s `default path emits a checked proof` | `default (prove) dylib build failed: target, x86_call_post, hcall, hret]` — a truncated fragment of a `simp` warning, so it reads as a linker/argv problem |
| anything else that emits a proof | the same truncated fragment |

`lib/ProofLib.olean.buildlock` and `lib/X86.olean.buildlock` exist, so a killed
run is not the story either.

## Why it is a real gap and not a stale artifact

`x86_step_cqo` is one row of `x86_step`'s decoder table, and the goal it leaves
open is **the whole content of the row**: `cqo` is defined as
`if x86_msb (x86_trunc32 rax) then rax ||| 0xFFFF_FFFF_8000_0000 else rax`, and
the theorem has to prove that the step's result field equals that. The model
side has the definition (`formal/x86_64_model.py`, `cqo` → `cqo`/`cdq` per
`da151f0c`) and the step table has the row, so this is a PROOF obligation that
was added with the row and not discharged.

The interesting half is that `x86_cqo`'s own definition and the goal look
identical, so the failure is almost certainly a missing `simp`/`rfl` step rather
than a wrong statement — but that is a guess and this worker did not check it.

## The exact next step

Open `lib/X86.lean:1348` and discharge the one goal. The two candidates, in the
order I would try them:

1. `x86_cqo` is presumably stated with the `if` on the other side of the
   equation or through a helper; `simp [x86_cqo]` / `rw [x86_cqo]` followed by
   `split <;> rfl` (or `omega`/`native_decide` if the condition is decidable
   arithmetic) is the shape the neighbouring rows in the same table use.
2. If `x86_cqo` is opaque to `simp` (a `def` with a `match` on `UInt8` bit
   tests), the neighbouring rows' own pattern is the template — read
   `x86_step_movsx_r64_r8`, whose comment two hundred lines up explains exactly
   why `x86_is_rex` and `x86_rex_w` are NOT in the simp set, because that is the
   trap this file keeps walking into.

Whichever it is, the measurable acceptance test is one command, and it is the
one that fails today:

```
$ python3 -c "import formal.lean as L, os; L.ensure_library('lean', os.path.abspath('lib'))"
```

then `python3 formal/x86_64_model_test.py` and `python3 test_formal_dylib.py`,
which are the two callers above and both of which should go green.

## What is NOT measured here

* I did not fix it, so every "should" above is a prediction.
* I did not check whether `bugs/FORMAL_x86_64_end_to_end_proof.md` (which names
  `cqo` in its coverage table, line 496, with no proof) already has the context
  this needs. **Read that doc first** — it is the area's own document, its
  status line claims `formal/x86_64_model_test.py` at "0 failing" as of
  2026-10-01, and `cqo` is one of the 57 forms in its coverage row, so this is
  most likely a row of that doc's own backlog rather than a new finding. If it
  is, delete this file rather than merging two records of one gap.
* I did not measure which suite jobs are red because of it on master. Every
  proof-emitting job is a candidate and the integrator's census is the cheap way
  to get the list.