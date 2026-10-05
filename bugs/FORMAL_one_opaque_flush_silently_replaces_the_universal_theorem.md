# ONE opaque `fflush` SILENTLY replaces the universal theorem with `prop := True`, and three rows of `test_formal_call_proof_gen.py` are red because the div0 false goal can no longer be reached

**Area:** FORMAL, arm64 proof layer — `formal/arm64_proof_gen.py`'s
`_unfollowable_calls` / `_opaque` arm, reached from
`formal/arm64_codegen.py::_emit_exit`'s `fflush(NULL)`. **Status: OPEN, measured
2026-10-05 on `work/merge-formal27a-r2`, and it is the interaction the merge of
the five branches surfaced.** NOT fixed here: the capability gap is
`bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`,
whose claim another worker holds, and its next step is a `lib/ProofLib.lean`
change that cannot be landed without the Lean gate. **What this doc adds is the
half of that gap which is silent** — where the other doc's fixtures all raise
`NotImplementedError`, one opaque call does not raise at all, and a theorem that
used to be about a program's answer becomes a theorem about reaching a call.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
FAIL: test_the_false_goal_survives_the_documented_next_step
     (TestTheZeroDivisorGuardAgainstLean) (spelling='as_emitted')
FAIL: test_the_false_goal_survives_the_documented_next_step
     (TestTheZeroDivisorGuardAgainstLean) (spelling='doc_next_step')
FAIL: test_the_residual_is_the_same_with_and_without_the_branch_fact
     (TestTheZeroDivisorGuardAgainstLean)
     AssertionError: None is not true : no residual goal was traced at all, so
     the measurement this class exists for did not happen
Ran 109 tests in 52.503s
FAILED (failures=3)
```

and the isolation, which is the whole of the finding — the same class on
`work/formal27-1`'s own tree, where the flush does not exist:

```console
$ mkdir -p .tmp/f271 && git archive work/formal27-1 | tar -x -C .tmp/f271 \
    && cp lib/*.olean .tmp/f271/lib/
$ cd .tmp/f271 && python3 tools/memslot.py --gb 8 --label f271-div0 -- \
      python3 test_formal_call_proof_gen.py TestTheZeroDivisorGuardAgainstLean
Ran 2 tests in 120.900s
OK
```

## What I saw

**The generated proof for `def q(a, b): return a // b` no longer contains the
theorem the class measures.** Both trees, same source, same
`compile_formal(..., prove=True, check=False)`:

| | `work/formal27-1` | this tree |
|---|---|---|
| proof lines | 6100 | 3461 |
| `theorem` count | 214 | 232 |
| `all_goals (first \| done \| sorry)` — the walk terminal's admission | **8** | **0** |
| `sorry` anywhere | 8 | 0 |
| `q_compiles_correctly_universal` | present | **absent** |
| what replaced it | — | `q_reaches_call_at_0x100000474`, whose proposition is `\| some s => True \| none => False` |

The reason is one instruction of difference in the IMAGE, and it is not a
difference in the div0 lowering:

```console
$ python3 .tmp/gen_img2.py "$PWD" "$PWD/.tmp"     # and again with $PWD/.tmp/f271
# 271:  external_syms = []          extern_calls = []
# HEAD: external_syms = ["fflush"]  extern_calls = [{'sym': 'fflush', 'addr': 4294968436}]
```

`4294968436` is the instruction after `q_dv2_z` (`4294968424`), so the call is ON
the divide-by-zero path: `_emit_exit(1)` opens with `fflush(NULL)` since
`e77131d5` ("formal/arm64: one `_emit_exit`, and every exit flushes what the
program printed"), and `e77131d5` is on `master` and was never on
`work/formal27-1` (`ccb157ed` is not an ancestor of it). Every label in the two
images is identical; the flush is the only difference.

## Why one call is silent and two are not — the part the other doc does not cover

`bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`
establishes the mechanism and, in "What changed on 2026-10-05", that its fixtures
now raise:

```
NotImplementedError: universal theorem: 2 calls this walk cannot follow
(0x100000448 -> 0x1000004d4 (opaque), 0x1000004a8 -> 0x1000004d4 (opaque)), and
ONE halt address cannot discharge them.
```

**That refusal is the `len(_calls) > 1` arm.** With exactly ONE unfollowable call
the arm above it runs instead, and it is not a refusal:

```python
    _calls = _unfollowable_calls(code, base_addr, func_entry_addr, None)
    _opaque = _calls[0] if _calls else None
    …
    _ukw = {"exit_at": _opaque["pc"], "thm": f"{func_name}_reaches_call_at_…",
            "prop": "True", "no_change": True, "halt_only": True}
```

so the universal theorem is RENAMED and restated as `True`, the concrete run test
is replaced by a `/- NO CONCRETE RUN TEST … -/` comment, and the walk never emits
a terminal value flow at all. `a // b` is the smallest program in that shape: it
has one exit and it is the div0 arm. The three shapes, as measured:

| opaque calls in the proved function | what the generator does | is it announced? |
|---|---|---|
| 0 | `f_compiles_correctly_universal` about `s.x0 = mojo …` | — |
| 1 | `f_reaches_call_at_…` with `prop := True` | only inside the emitted proof, in a comment that says "the universal theorem above", and there is none above |
| ≥2 | `NotImplementedError`, both addresses named | yes, loudly |

The emitted comment is also wrong in the one-call case, which is worth knowing
before anyone greps a proof for it:

```
/- NO CONCRETE RUN TEST for q: the function calls out of
   the image at 0x100000474, so the model cannot execute the
   call and `arm64_exec_go` stops there. … The
   universal theorem above proves the part that IS decidable: the
   run reaches the call, for every input. -/
```

There is no theorem above it; it is the sentence the `_opaque is None` path
wanted.

**This is not a wrong theorem, which is the one thing it must not be.** `prop :=
True` is proved, so nothing false is emitted — the cost is that the arm64 proof
layer now says NOTHING about the value a div0 path leaves, and the soundness
hole that leaves is the one
`bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md` is
about. What is lost is not a proof but a MEASUREMENT: §0 of that doc is a
refutation (the walk terminal's residual is the false goal `⊢ 1 = …`, byte for
byte with and without the old next step), and it is no longer executable through
this program, so the refutation is no longer pinned by anything.

## What is red, exactly, and what each red says

`TestTheZeroDivisorGuardAgainstLean` is the measurement class, and both of its
methods now fail for the same reason — there is no residual goal to read:

* `test_the_false_goal_survives_the_documented_next_step` (two subTests, one per
  spelling) asserts `"⊢ 1 ="` is in Lean's output. Lean's output is seven
  `declaration uses 'sorry'` warnings and nothing else, because `_TRACE`
  (`all_goals (first | done | (trace_state; sorry))`) has nothing to attach to.
* `test_the_residual_is_the_same_with_and_without_the_branch_fact` asserts a
  residual goal was traced at all, and its own message says the honest thing:
  "no residual goal was traced at all, so the measurement this class exists for
  did not happen".

`formal-call-proofgen` is a registered gate job with `deps=['preflight',
'prooflib']`, so this is a real red in the tally and is declared by no `expect=`.
Its sibling class `TestTheZeroDivisorGuardIsAFalseGoal`, which needs no Lean and
asserts the same subject from the text (`fdiv64`'s div0 arm is the literal `0`,
and a zero divisor leaves the image with status 1), is **green** — the defect
itself is untouched; only the route to it is.

## The exact next step

Three things, in this order, and none of them is a tactic.

1. **Decide what ONE opaque call should say, because that decision is what the
   div0 path now rests on.** The two options are the ones the claimed doc already
   names for the general case, specialised to a call that is on EVERY path: either
   the per-block terminal predicate (`arm64_go_exit … = none` for that block, a
   disjunction over halt addresses — the claimed doc's option 1, a `ProofLib`
   project), or an explicit divergence treatment for a block that cannot return
   (which is option 2 of the div0 doc, "stop claiming a value on the div0 path at
   all", and it is now the only one of the three that does not require the
   walk to execute the call). **Option 2 is now cheaper than it looked and is the
   one to argue first**, because the image really does leave and the source really
   does raise `ZeroDivisionError`: a formal value is one 64-bit word with no way
   to say "no value", and `prop := True` says it by declining to.
2. **Whatever is decided, make the one-call case ANNOUNCED the way the two-call
   case is.** A caller that asked for a theorem about `x0` and received one about
   reaching an address should not have to diff the emitted proof to find out.
   The `NO CONCRETE RUN TEST` comment is the right place and it is currently
   wrong about what it is commenting on.
3. **Then re-run the div0 measurement** and correct
   `bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md`'s
   §0 and its next step, which are written against a walk terminal this program
   no longer emits. Its three options are still the right three; what has moved
   is that option 1 ("make the model say what the machine leaves, per backend")
   is now a claim about a block the walk does not walk at all.

## Whose

The capability gap and the two-call refusal are
`bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`,
and `formal28-2` holds that claim — which is why this is a separate doc and not a
section appended to it. The div0 subject is
`bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md`, which
no worker holds. The three red rows are in `test_formal_call_proof_gen.py`,
added by `work/formal27-1`, whose measurement is correct and whose route is gone.

Nothing here is left unmeasured on purpose: the three reds are left RED rather
than marked or skipped, because each of them fails with a message that says
what stopped happening, and a marker over them would hide exactly that.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_call_proof_gen.py TestTheZeroDivisorGuardAgainstLean
# …and the shape, with no Lean and no proof check:
$ python3 - <<'PY'
import os, sys, tempfile
sys.path.insert(0, '.'); import formal.build as fb
tmp = tempfile.mkdtemp(); src = os.path.join(tmp, 'q.mojo')
open(src, 'w').write("def q(a, b):\n    return a // b\n")
info = fb.compile_formal(src, arch='arm64', output=os.path.join(tmp, 'q.aout'),
                         prove=False)
print(info['info']['extern_calls'], sorted(info['info']['labels']))
PY
# external_syms/extern_calls carry the fflush; every label matches a tree without it.
$ grep -c "all_goals (first | done | sorry)" <the generated proof>   # 0 here, 8 without the flush
```