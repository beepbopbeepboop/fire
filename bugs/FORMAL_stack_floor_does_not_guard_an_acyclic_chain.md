# FORMAL_stack_floor_does_not_guard_an_acyclic_chain: CLOSED for programs — every prologue of an image that has an entry carries the guard

**Status 2026-10-05 (`work/formal27-5`): the RULE is unchanged and its
MEASUREMENT had drifted in three places, one of them contradicting the instrument
it cites. Re-measured with `python3 tools/formal_call_depth_census.py` (12 s, no
build) and corrected in `formal/model.py`, `test_formal_run.py` and here.**

| the corpus figure | as published | measured 2026-10-05 |
|---|---:|---:|
| deepest image, `formal/arm64_codegen.py` | 76 | **89** |
| deepest image, `formal/x86_64_codegen.py` | 69 | **78** |
| …as a multiple of the 60 frames arm64 affords | 1.3x | **1.5x** |
| images measured over the repository | 413 | **474** |
| median / p90 repository depth | 3 / 6 | **3 / 6** (unchanged) |
| **deepest chain the guard does NOT reach** | **7** | **7** (unchanged) |

**The last row is the one this document leaves OPEN, and it has not moved: the
module dylib's residual is a bounded 7 frames, median 3.** So the re-measurement
moved the number the closed half is argued from and left the open half exactly
where it was — which is the useful shape for a reader: the risk on programs is
concentrated in two files and the guard catches them (`deep(89)` is
`STACK_TRAP_STATUS`, not a SIGSEGV), and the module dylib is still the
`lib/Refine.lean` project at the end of this document.

**The drift was in three directions and one of them was a plain error.**
`test_formal_run.py` carried the residual as **12 frames** in two places
(14,000 lines apart) while the census's own docstring, `formal/model.py`'s
`body_has_conditional_branch`, `stack_floor_guarded_names` and this document all
said **7**; a fresh run says 7. And `formal/model.py` named the census's column
**`no-brch`**, which the tool does not print — the column is `unguard`, and it is
a depth rather than a per-image flag. All three are corrected in place, each with
the date and the command beside it, because **a figure copied between files is a
figure that stops agreeing with the instrument it cites** and nothing in the tree
compared them. What is deliberately NOT done is pinning these numbers in a test:
the guard's argument is about the corpus, so a test that asserted them would go
red on an unrelated merge — which is why the census exists as an instrument to
re-run rather than as a fixture to assert. That trade is stated at
`test_formal_run.py`'s `_STACK_FLOOR_DEPTH_PROBES`, and this re-measurement is
what it looks like when the corpus moves under a published figure.

**Area:** FORMAL (the stack-floor guard, both architectures).
**Status: MEASURED, WIDENED and then CLOSED (2026-10-03, `work/formal13-6` then
`work/formal16-6`).** The guard landed in `formal/model.py`
(`STACK_TRAP_STATUS`, `STACK_FLOOR_BUDGET_BYTES`, `stack_floor_address`,
`stack_floor_guarded_names`) and in both emitters (`_emit_stack_floor_guard`),
and it fixed the defect its predecessor doc recorded — recursion past the fixed
frame size is `exit(2)` and not a SIGSEGV, on both machines. The cycle-only rule
left the acyclic chain open; the measurement decided to widen it to every body
that already branches; and §0.2 closes the rest, because **the residual was not
a missing rule at all — it was the FLOOR's own reference point.**

| image | rule | straight-line chain of 600 |
|---|---|---|
| program (a startup stub, so no exports) | **every function** (§0.2) | **`exit 2`, both architectures** — was `exit 139`, a SIGSEGV with no output |
| module dylib (every function may be an export with a proved per-export contract) | cycle ∪ body-with-a-branch | unchanged: a straight-line chain is unbounded here, and `tools/formal_call_depth_census.py` still measures it (max 7 over this corpus, median 3) |

## 0.2 The residual closed, and it was the floor, not the rule
## (`work/formal16-6`)

**The measurement that decided it, and it is one line of the guard's own
sequence.** `_emit_stack_floor_guard` writes the floor **once**:

```
ADRP+ADD X17, &floor ; LDR X16, [X17]      the floor word
CBNZ X16, done                             ALREADY STORED — someone else set it
ADD X16, SP, #0 ; SUB X16, X16, #BUDGET    the first caller sets it
STR X16, [X17]
done:  ADD X17, SP, #0 ; CMP X17, X16 ; B.HS ok ; movz x0, 2 ; svc #0x80
```

So the reference point is **the SP of the first GUARDED function to run**, not
the image's base and not the current function's entry. Two consequences, and the
second one is the whole of this section:

1. **A guarded function deep in a chain sets the floor too deep for that chain.**
   `f1 → … → f80 → g`, every body straight-line and `g` the only one with a
   branch: `g` sets the floor at 80 frames down and immediately compares SP
   against SP − 7.5 MiB, which passes. The chain has already spent its stack by
   then. **Widening the guarded SET cannot fix this** — the doc's second rule
   widens the set, and the set does not decide where the floor is written.
2. **so the rule that does fix it is "every prologue", and the only question is
   what it costs.** For a program image it costs nothing: `main` is the entry,
   there are no exports, and the per-export contract
   (`arm64_proof_gen._dylib_contract_proof`) is a MODULE-DYLIB artefact. For a
   module dylib it costs a proved contract per straight-line export, which is
   exactly the cost the cycle-or-branch rule was written to avoid.

Which is why the rule is a **parameter** and not a replacement:
`model.stack_floor_guarded_names(functions, structs, every_function=False)`, and
both emitters pass `every_function=emit_startup` — the same fact, since an image
with a startup stub has an entry and an image without one is a module dylib.

**Guarding the ENTRY alone does not do it, and that is worth stating because it is
the obvious cheaper half.** The check runs once, in `main`'s prologue, where the
stack is one frame deep. It is the whole set that has to be guarded.

Measured, both architectures, on the shape that is the residual exactly — 601
straight-line functions, no cycle and no branch anywhere:

```
before   exit 139        SIGSEGV, no output, no status a caller can read
after    exit 2          STACK_TRAP_STATUS, on arm64 and x86_64
```

(the row is `test_formal_run.py`'s
`both_arch_a_straight_line_chain_past_the_floor_is_a_status`, which REPLACES
`guard_a_straight_line_chain_is_left_alone` — the row that used to say this out
loud, and which the fix turns from a confession into the pin.)

**The proof side, checked rather than argued,** because the guard is now in every
prologue of every program image and the whole of what could break is the emitted
proof:

| | result |
|---|---|
| `test_formal_run.py` | **PASS=905 FAIL=0** — every formal image in the suite builds and RUNS with the guard in every prologue, on both architectures |
| `formal/examples/absval.mojo`, arm64, `fire.py build --formal` | proof emitted and **accepted by Lean** (3.1 GB peak, exit 0) |
| `formal/examples/absval.mojo`, x86-64, same | proof emitted and **typechecks at exactly 2 admitted `sorry`** — that generator's design floor, unchanged |
| `test_formal_run.py`'s stack-floor probes | 26 PASS, 0 FAIL — the 23 cycle/branch probes plus 3 new ones for the third rule, which pin BOTH halves: `every_function=True` covers the straight-line chain, and `every_function=False` leaves the module-dylib answer exactly where it was |

`formal/examples/count.mojo` still fails its arm64 proof, **before and after** —
it is the dec1 `x30` family (`bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md`),
which `bugs/FORMAL_proof_coverage_census_2026-10-03.md` §4 records as
`lean-rejected` on this tree. It is not this change's regression and it is named
here so a reader who runs it does not have to re-derive that.

**What is left, and it is the module dylib.** A module dylib's exports are entries
in the only sense that matters — a host calls them at an arbitrary depth — and
their straight-line chain is still unguarded, still bounded by the corpus at 7
frames (median 3, `tools/formal_call_depth_census.py`, which now asks the
question of the module-dylib rule on purpose and says so in its own comment).
Closing THAT is the `lib/Refine.lean` project below: a guarded prologue is a
two-way conditional, `Refine.Block.step` is one function of one state, and an
export with a branch has no `Block` to certify.

## What is fixed, and what it cost

```
arm64    deep(59) exit 0    deep(60) exit 2    was: 61 then SIGSEGV (exit 139)
x86-64   deep(471) exit 0   deep(472) exit 2   was: ~450 then SIGSEGV
```

The two lost arm64 frames are the trade `STACK_FLOOR_BUDGET_BYTES` states in
its own comment: the budget is 7.5 MiB, the measured usable stack below the
startup stub's SP is between 7.63 and 7.75 MiB, and being under it costs one to
two 128 KiB frames. A budget that OVERestimates the real stack leaves the guard
silent and the program dies as it did before — no worse than the defect — while
one that underestimates costs depth, which is a refusal and never a crash. That
asymmetry is the reason the number is a named policy constant and not a literal
in two emitters.

## The measurement, and it decided the rule

`model.call_graph_depth` (new, with `model.call_graph_edges` factored out of the
old `recursive_function_names` so the rule and the measurement walk ONE graph)
and `tools/formal_call_depth_census.py` (new — parse plus one graph per file,
680 files, no sweep and no build). Over this repository and the stdlib:

```
deepest image: 76 frames                                    <- RE-MEASURED 2026-10-05: 89
  arm64  traps at  60 frames; deepest measured is 76 = 1.3x the budget
  x86-64 traps at 480 frames; deepest measured is 76 = 0.2x the budget
deepest chain the guard does NOT reach (bodies with no branch, no cycle): 7
76    202   1400   4   formal/arm64_codegen.py   <-- AT/OVER the arm64 budget
69    188   1195   4   formal/x86_64_codegen.py <-- AT/OVER the arm64 budget
44    195    694   3   fire_compiler.py
...
repository   413 images; median depth 3, p90 6, max 76
stdlib       181 images; median depth 3, p90 7, max 16
```

**Re-measured on this tree (2026-10-05, `work/formal27-5`), same command, and
every line of it a `Counter` over the same graphs:**

```
89    242   1631   4    formal/arm64_codegen.py   <-- AT/OVER the arm64 budget
78    228   1462   5    formal/x86_64_codegen.py <-- AT/OVER the arm64 budget
44    206    733   3    fire_compiler.py
23    865   2351   4    formal/model.py
22    128    385   5    formal/hostmods/re.mojo
...
repository   474 images; median depth 3, p90 6, max 89
stdlib       181 images; median depth 3, p90 7, max 16
```

**89 is 1.5x the 60 an arm64 budget affords** (it was 1.3x), the deepest
branch-free chain is **still 7**, the median and p90 are unchanged, and the
repository has grown from 413 images to 474 — so the risk on programs is exactly
as concentrated as this document said it was (two files, both this backend's own
codegen) and the guard catches both, while the MODULE DYLIB residual this
document leaves open is unmoved. The two figures that had to be corrected
elsewhere in the tree when this was re-measured are in the Status at the head.

**The answer to the question this document spent three revisions asking is
"close" — the corpus is ALREADY INSIDE the hole, by 1.3x — and the two deepest
images are the two this backend's own codegen lives in**, which is the file this
document already named as the one to measure first. The median is 3 and the p90
is 6, so the risk is concentrated in exactly two files and is not a general
property of the corpus; the depth is also an upper bound twice over (`iter`'s
edges are a superset of the calls the emitter makes, and `call_graph_depth`
bounds the longest simple path by the condensation), so the real figure is at
most 89 and at least 60 — either way the same order as the budget, and the
re-measurement at the head of this document is what moved the upper end.

**The x86-64 figure is why the rule had to be widened rather than the budget
raised.** 89 frames is 0.2x x86-64's budget and 1.5x arm64's, so a budget change
would fix one machine by making the other's guard fire earlier for no reason.

## The rule that landed

```python
model.stack_floor_guarded_names(functions, structs)
    = {f.name for f in functions
       if on_a_call_graph_cycle(f) or body_has_conditional_branch(f)}
```

**The second clause is free, and the argument is about the per-export contract
proof, not about code size.** `arm64_proof_gen._dylib_contract_proof` returns
`""` — no contract — for an export whose body contains ANY conditional branch,
because `Refine.Block.step` is one function of one state and a conditional branch
does not have one. So a body that already branches has no contract to lose, and a
body that does not is left exactly as it was. "Every function" would trade
proved contracts for nothing, which is what this document's predecessor
measured; "every function that already has a branch" does not.

**Which makes the predicate's DIRECTION load-bearing rather than tidy**, because
the same argument read backwards says a predicate that over-counts would take a
contract away from an export that has one. `body_has_conditional_branch` counts
only constructs that ALWAYS lower to a conditional branch on both backends with
no purity gate in front of them — `if`, `while`, `for`, `assert`, `try`, `match`,
a comprehension with a condition — and deliberately does NOT count a **ternary**
or a **short-circuit chain**, because both backends have a BRANCHLESS lowering
chosen by a purity predicate (`a if c else b` becomes a CSEL on arm64; the
branchless `and`/`or` form is gated on the left operand needing no conversion).
It also does not descend into a nested `def`, whose branch is in the nested
function's own prologue; `formal/build.py`'s `_flatten_closures` lifts every
nested def to top level before the function table exists, so this is defensive,
and `iter_nodes` would not have been.

Verified on both architectures, measured before and after, on the shape the
measurement says is reachable:

| program | before | after |
|---|---|---|
| 600 distinct functions, each calling the next, each with an `if` — arm64 | **SIGSEGV, exit 139** | `exit(2)` |
| the same program on x86-64 | **SIGSEGV, exit 139** | `exit(2)` |

600 rather than 61 because x86-64's frame is 16 KiB to arm64's 128 KiB, so its
budget affords 480 frames and a 61-deep chain is correctly INSIDE it — a single
depth cannot show the defect on both machines, and a case that fires on one is a
case about the frame size rather than about the guard.
`test_formal_run.py`'s `both_arch_an_acyclic_chain_past_the_floor_is_a_status`.
The negative beside it was `guard_a_straight_line_chain_is_left_alone`, and §0.2
is what turned that negative into a second positive: the straight-line chain it
used to leave alone now traps too.

**What it costs, measured rather than argued:** `test_formal_run.py` PASS=806
FAIL=0 (782 before this pair of changes, +15 stack-floor probes, +7 guard
probes, +2 generated cases). `test_formal_dylib.py` PASS=19 FAIL=0 with Lean
actually running — 1 m 5 s at 3.1 GB peak, so the CAS verdicts were a cache MISS
on the new proof bytes rather than a replay, which is the measurement that says
"no export lost a contract".

## What is still not fixed, and it is the proof side — a MODULE DYLIB only

**For a program image this is closed (§0.2): every prologue carries the guard and
600 straight-line functions in a chain exit 2 instead of dying.** What is left is
the module dylib, whose exports are entries in the only sense that matters — a
host calls them at an arbitrary depth — and whose straight-line chain the corpus
bounds at **7 frames** (median 3) against arm64's 60.

Closing it is not an emitter decision, and §0.2 says exactly why it is not one
for an image that HAS exports:

* `formal/arm64_proof_gen.py::_dylib_contract_proof` returns `""` for an export
  whose body contains ANY conditional branch, and the guard's own `cbnz`/`b.hs`
  is one. Its comment says so, and the enclosing emitter turns the empty string
  into a NAMED `sorry` obligation against the derived spec.
* So with the guard in EVERY prologue, `test_formal_dylib.py`'s
  `a wrong spec is rejected, not believed` went red with exactly the message it
  exists to be able to produce: *"lean ACCEPTED a contract claiming triple
  computes a wrong multiplier — the per-export contract is not being checked
  against the machine, so it is an admitted claim wearing a proof's clothes"*,
  and the proof census went from one `sorry` in the file to one per export.
  Measured on the guard applied to every prologue, then reverted.
* **The fix belongs in `lib/Refine.lean` / `lib/Contracts.lean`**: a
  `Refine.Block` whose step is a two-way conditional needs either a `Block` per
  arm with a join, or a step relation that quantifies over the condition — and
  either way `Contracts.ExportBody.atExit`, which is stated at
  `image.base + image.codeSize`, has to be re-derived for a body that can leave
  through two addresses. That is a proof-side project with the `prooflib` build
  in front of it.
  **One of the two blockers this section used to name is GONE**, which is worth
  recording because it is the kind of fact that costs a reader an hour: the
  `sorry`s at `InImage` and `Semantics` are no longer there —
  `lib/ProofLib.lean:5285` records that "the old `in_image_stub` was `by sorry`
  over" a false statement and that `native_decide` now closes it. So the standing
  obstacle is the two-way `Block` alone, which is a smaller project than this
  section described.
* **And the schema is more ready than it was.** `lib/Refine.lean`'s control-flow
  layer already has `Edge.cbz (bi) (reg) (taken) (target)` — a conditional branch
  with a DECIDED outcome — and the step lemmas are emitted PER INSTRUCTION with
  both arms discharged by `by_cases` + `simp` (see the `idx == 51` /
  `idx in (16, 17)` arms of the generator's tactic chain, whose comment names
  the stack-floor guard's own `B.HS` as the case it was measured on). What is
  missing is a `Block` per arm plus the join, not a way to state a branch.

The cheaper third option this document used to offer — "on a cycle, or reachable
from one" — is **dominated** by what landed and is not worth taking: a DAG with
no cycle in it has no member reachable from one, so it would guard nothing that
the cycle rule did not already guard, and the measured offender
(`formal/arm64_codegen.py`, 89 frames) is a DAG.

## Reproducing

```
$ printf 'def deep(n: Int) -> Int:\n    if n <= 0:\n        return 0\n    return deep(n - 1) + 1\n\ndef main(n: Int) -> Int:\n    return deep(5000)\n' > .tmp/deep.mojo
$ python3 fire.py build --formal --no-prove -o .tmp/d50 .tmp/deep.mojo && .tmp/d50; echo $?
2
$ python3 fire.py build --formal --backend=x86_64 --no-prove -o .tmp/x50 .tmp/deep.mojo && arch -x86_64 .tmp/x50; echo $?
2
$ python3 tools/formal_call_depth_census.py            # the measurement above
```

`test_formal_run.py`'s `stack_floor_deep_recursion_is_a_status` /
`stack_floor_mutual_recursion_is_a_status` / `both_arch_an_acyclic_chain_past_the_floor_is_a_status`
(both architectures) plus `check_stack_floor_decision`'s seven guarded-set probes
and eight `call_graph_depth` probes are the regression net for what landed.
