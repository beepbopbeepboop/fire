# OPEN_WORK: consolidated queue for the x86-64 formal and shared-infrastructure work

**Date: 2026-09-26. Nothing here is fixed; this is everything still open that
the x86-64 formal / self-hosting side knows about, plus the todo list it came
from.**

## Scope, and what is deliberately NOT here

This is the *x86-64 formal verification* and *shared self-hosting
infrastructure* slice. It does not duplicate the per-bug evidence — every item
below names the document that owns the detail.

**Not here: the arm64 codegen and arm64 proof-generator work.** That is the
other agent's active line; it now lives in the `FORMAL_arm64_*` / `CODEGEN_arm64_*`
documents, the root ledger having been split up and deleted, and it
arm64-side ledger. Items below that touch arm64 are listed only where the
x86-64 side has a mirror of the same defect, and are marked as such.

| where the detail lives | covers |
|---|---|
| `FORMAL_x86_64_end_to_end_proof.md` | B1–B23, the proof work, the per-form ledger |
| `CODEGEN_bootstrap_resource_blowup.md` | the ~192 GB runaway, the 55 GB ceiling, attribution |
| `CODEGEN_noshim_dumpfull_preexisting_divergence.md` | native-vs-reference `.ci` divergence |
| `CODEGEN_nested_comprehension.md` | nested comprehension, both backends |
| `FORMAL_x86_64_formal_backend_gaps.md` | the two backend gaps (both now fixed) |
| `FORMAL_string_value_model.md` | what a string IS on the formal path, `len`/`==`/`+` on it, and the `String`-struct collision behind the 16 "a String receiver" refusals |
| `FORMAL_arm64_instruction_coverage.md`, `FORMAL_arm64_known_proof_gaps.md`, `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` | arm64 work — not duplicated here |
| `FORMAL_frame_receiver_handoff.md` | who can take a frame address: the cross-module method hand-off (a binding bug, fixed), `Pointer(to=frame)` (an unjustified refusal, fixed), whether the frame layout and the struct's C layout coincide (measured: they do, for 8-byte fields), and the three refusals that named a cause which was not operating |

---

## A. The todo list this came from

Verbatim, with the current measured state attached to each. Ordered as I would
take them.

### A1. `call_rel32` — 7 examples, the last big uncovered form — **high**

The largest single blocker left in the x86-64 proof work. `x86_step_call_rel32`
**already exists** in `lib/X86.lean`; it is simply not wired into the
generator's `_FORMS`/`_SUCCS`/`_resolve` trio. What makes it more than a
lookup is that a call has **two** successors *and* a memory write: it pushes
the return address and jumps. The pushed word has to be shown separated from
the callee's frame, and the callee has to be in the path tree at all. Real
design work, not a wiring change.

### A2. `movsx_r64_r8` (3 examples) + 8 one-example forms — **medium**

After `call_rel32`, the remaining uncovered forms are `movsx_r64_r8` and
singletons: `alu_rr:and`/`:or`/`:xor`, `alu_rr32:xor`, `shift_imm8:shl`/`:shr`,
`group3:div`, `alu_ri32:and`. One lemma each, and most follow an existing
shape — see the generalisation rule at the end of A4.

### A3. 14 termination proofs carry a `sorry` — **medium**

Not free. Each is a real step lemma or a memory-separation inequality Lean
declined, reported per file so the gap is countable. The cause is a single
thing: for a function that spills its argument, the closing read's address is a
`mem_write_bytes` chain whose offsets are literals but whose *value slot* is
symbolic, so `decide` reports `Expected type must not contain free variables`
and `omega` cannot see through `mem_write_bytes`. Relating the stack
arithmetic symbolically would close them.

### A4. 4 loop examples — `countdown`, `sum_range`, `wdiff`, `wge` — **low**

No finite path tree, because the chain walks one straight line and has no way
to represent a join or a back edge. A limit of the method as built, not a proof
failure. Needs induction over the back edge.

### A5. Make `lib/ProofLib.olean` the first build step when something fails — **high, cheap**

`lib/X86.lean` imports `lib/ProofLib.lean`, so an unrelated arm64 edit to
ProofLib breaks every x86-64 proof, and the resulting error names a file the
x86-64 side never touched. Purely a build-hygiene fix and it removes a
recurring misdiagnosis.

---

## B. Codegen defects characterised but not fixed

### B1. x86-64 nested comprehension returns 98 for 100 — **high**

`test_x86_64_containers.py:229`, n = 5. Two short, not a crash and not a wrong
count, so elements *are* appended and a couple carry the wrong value. Specific
to the recursion in `X86_64Codegen._emit_compr_gen`
(`formal/x86_64_codegen.py:2529`). Already ruled out, so nobody re-checks them:
the control temps *are* allocated; the append cursor is *not* register-held; the
outer loop is self-healing for R10/R11.

### B2. x86-64 nested comprehension `len` reads 4, not 16 — **high, separate bug**

A *different* defect from B1 and easy to conflate with it: here the **count**
is wrong, not the values. The blob header is not updated by the appends the way
the append path reads it, and `label(start_label)` protects the *outer* loop's
next iteration, not the inner generator's append. A fix for B1 does not
necessarily fix this.

### B3. Dict comprehension computes the wrong value — **medium (arm64-owned)**

`{i: 100 + i for i in range(3)}` gives the right keys and the right count next
to wrong values (`d[1] == 1`, want `101`). Partially fixed on arm64. The
x86-64 side has not checked whether it shares this.

### B4. arm64 4x4 nested comprehension sums to exactly double — **medium (arm64-owned)**

`len` = 16 correct, sum = 48 where 24 is right, while 2x2, 3x2, no-`i` and
constant-element nestings are all exactly right. A correct count with a doubled
sum means wrong values or double appends, not a count bug. **4x4 is the case to
check a fix against** — 2x2/3x2 passing does not cover it.

---

## C. Self-hosted native: memory and divergence

### C1. The ~192 GB growth is unexplained — **high, and it gates everything**

A whole-program `--dump-full fire.py` reached ~192 GB on 2026-09-26 and had to
be killed by hand, against ~96 GB completing on 2026-09-25. At least 2× the
last known-completing footprint, against a documented success criterion of
"materially below 45 GB".

Do **not** start by optimizing: the slope is unknown, and the flag probe
already showed `-O1`/`-O2`/`-O3` barely differ in footprint (93.7/93.7/95.6 GB),
so compiler-binary optimization is not the lever. Measure first:

1. Bisect the ~40 commits since 2026-09-25 using **single-module** dumps as a
   cheap proxy. Never the whole-program dump unattended.
2. Profile by phase; establish whether peak is in the *transitive* dump.
3. **Cheapest and most valuable: distinguish live-set from fragmentation** — an
   allocation-count probe, or `leaks`/`vmmap`. Answers whether the memory is
   reachable objects or a leak. Do this one first.

### C2. The self-hosted runtime's never-frees allocator — **high**

The original suspect, implicated in a case that turned out to have a *different*
cause — which is not the same as being cleared. Never exonerated. The standing
recommendation is to free or reuse intermediate allocations, or at least the
walker's transient node lists.

**A SIGKILL here is evidence of nothing.** A manual `kill -9` and an OS kill
are the same signal, and this area has now been misdiagnosed twice by inferring
OOM from a silent death. Establish the cause in the foreground under a memory
monitor; never under `(…&)`.

### C3. Four stage1-vs-stage2 `.ci` divergences — **medium**

`fire_compiler.ci`, `fire.ci`, `module_loader.ci`, `myinterpreter.ci`. Tracked
in `CODEGEN_noshim_dumpfull_preexisting_divergence.md`; deliberately **not**
assumed to share a root cause — each must be compared independently. The set is
not stable, because that doc records `PYTHONHASHSEED`-dependent nondeterminism
in the python3-interpreted reference path itself.

### C4. Native `SIGTRAP` / exit 133 during large Stage 2 transitive dumps — **medium**

Intermittent, path/state-dependent, not a simple compile failure. Narrowed to a
self-hosting *import* failure: `module_loader._mojo_type_to_c()` uses a
function-local `from gimple_codegen import _mojo_type`, and in the flattened
whole-program closure `_mojo_type` is also visible through
`mojo.middle.types`, so the resolver reports it as ambiguous. A qualified
member call was not sufficient — the self-hosted backend lowered it as an
unavailable stub. Two speculative workarounds were tried and **neither is
retained** (one caused a native allocator failure).

### C5. `test_native_dumpfull.py:75` still reports a fixed bug — **low, one line**

The message hardcodes *"the known original SIGBUS in `_rewrite_assign_stmt`
writes the correct file before crashing, so an ABSENT file is a worse
regression, not the known issue."* That SIGBUS was root-caused and **fixed**
2026-09-20. It also argues the reader *out* of the right answer here, and
discards the one signal that distinguishes the cases. `tools/memcap.py` now
shields it (a breach kills the harness before it can misreport) but the message
is wrong on its own terms. Deferred repeatedly; it is genuinely a one-liner.

---

## D. Contradictions and unknowns — needs a decision, not more work

### D1. Which symptom does the current tree actually produce? — **needs resolving**

Two accounts of `check-native-dumpfull` disagree, and they imply different
bugs:

- `CODEGEN_noshim_dumpfull_preexisting_divergence.md` (2026-09-25): *"still
  the known pre-existing SIGSEGV (NO fire.ci, exit 139)"*.
- Reported 2026-09-26: reaches ~192 GB, `exit -9`, killed **by hand**.

Either the tree has changed, or these are two different failure modes of one
underlying instability, or one of the two observations is stale. This is worth
settling before optimising anything, because "SIGSEGV at 139" and "runaway
allocation" would be fixed by different changes. Cheap to settle: one run
under `tools/memcap.py` at a ceiling low enough to trip quickly, in the
foreground, with the exit code and peak recorded.

### D2. The loop classification does not agree with itself — **low**

The gate reports `19 no finite tree (4 loop, 15 uncovered form)`, and its
totals are self-consistent (24 proved + 19 = 43). But the emitter's own
refusals disagree: of the 19, five say `body loops` and five say `or branches
out of the function`, and only one example is caught by the separate
`_has_loop` predicate. So "4 loop" is narrower than the set of examples the
emitter actually rejects as loop-shaped. The *form* counts are stable and
trustworthy (`call_rel32` 7, `movsx_r64_r8` 3, eight singletons); the loop
split is not. Cheap to reconcile, and worth doing before anyone reasons about
"how many loop examples are left".

### D3. A/B sweep shows 605 CI-DIFFs, untriaged — **medium, may be benign**

At 2026-09-25: `clean=157 CI-DIFF=605 SELFHOST-CRASHED=0 AST/TOK-DIFF=0`.
CI-DIFF is nominally the headline category — "a real self-host MISCOMPILE" — so
605 is a lot, but the sweep is at scale and the categories have never been
worked through. **Nobody has triaged this.** It may be one systematic
difference rather than 605 bugs, and it should be triaged before anyone
investes in it, because a single shared cause would collapse the number.

---

## E. Method notes worth carrying forward

Not work items — things that were learned the hard way and should not be
re-learned. The generalisation rule, from the x86-64 proof work:

> Generalise a form when the backend actually emits more than one shape of it,
> and not otherwise. `movzx r64, r8` is emitted as the identical `48 0f b6 c0`
> in all 33 instances, so a concrete lemma covers them all and a
> register-parameterised one would be machinery nothing calls. Every form that
> *was* pinned to one register pair, though, turned out to need generalising —
> so it is a heuristic, not a proof.

Three more, each of which cost real time and each of which is a trap that
reappears:

- **A lemma with contradictory hypotheses compiles, typechecks and proves its
  goal.** It is simply inapplicable, so the file is green and the lemma is
  doing nothing — worse than absent, because absent shows up as a gap. Check
  hypotheses are *satisfiable at a real call site*; "the file builds" is
  exactly the signal that misses this.
- **The `sorry` guard must be `try (…) <;> all_goals sorry`**, inside the
  inline `by`. An unsolved goal in a sub-`by` is an *elaboration* error, so
  nothing enclosing it catches it. And `first | a | b` is wrong: `first`
  commits to the first alternative that does not *throw*, not the first that
  *closes the goal*.
- **A heartbeat timeout is not catchable by `try`.** The budget is the only
  lever.

## F. The x86-64 formal numbers to beat

From `make check-formal-x86-endtoend`, all suites run rather than assumed:

| | result |
|---|---|
| `formal/x86_64_model_test.py` — model vs hardware | 43/43 agree, 0 wrong |
| `formal/x86_64_model_coverage_test.py` | 151 samples over 57 forms, all steppable |
| `test_formal.py --backend x86_64` | 43/43 PASS, 0 known gaps, 0 fail |
| value theorem (every input, `rax` a fixed constant) | **3** proved |
| termination theorem (every input reaches the exit pc) | **10** no-sorry, **14** with a sorry |
| no finite path tree | 19 (4 loop, 15 uncovered form — but see D2) |
| failing | 0 |

The number to watch is **terminates proved with no sorry (10)**. A change that
pushes it down has taken a real proof away even when every file still builds —
which is precisely the failure a vacuous or inapplicable lemma hides, and the
reason the value theorem's 3 is not the headline.
