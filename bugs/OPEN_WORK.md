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
| *(deleted 2026-10-02)* | **the register-argument ceiling is GONE on both backends.** `FORMAL_x86_64_argument_registers.md` asked for the stack-argument convention both ABIs already have and it landed: `_MAX_INCOMING_ARGS` = 24 in each, with `formal/x86_64_codegen.py`'s `_load_home_from_stack`/`_emit_call` as the SysV half. `formal/hostmods/fnmatch.mojo` (`match_core(7)`) and `pathlib.mojo` build on x86-64, the two `KNOWN_X86_64_ONLY` rows in `test_formal_hostmods_census.py` are deleted, and the `X86_ONLY_REFUSALS` group in `test_formal_x86_64_parity.py` became positive cases. What it left behind is the next two rows, and they are the whole of it |
| `FORMAL_ast_bridge_binds_only_the_first_parameter.md` | **the only thing left of the above**: `lib/ProofLib.lean`'s `MojoFunc`/`evalFunc` bind ONE parameter, so a two-parameter entry point — legal on both architectures, and what `re.mojo` and `hashlib.mojo` are full of — produces a proof file that does not elaborate. Not an x86-64 item: one limit, both machines, same message |
| `FORMAL_x86_64_stack_argument_past_the_twentieth_needs_a_disp32_lemma.md` | the residue of the same change on the PROOF side: the callee's stack-argument load crosses from disp8 to disp32 at argument 20, and `lib/X86.lean` has a disp32 STORE lemma and no disp32 LOAD. The image is right (24 arguments compute 241 on both backends) and the model can step it; the per-instruction proof chain cannot be built. **Not a reason to lower `_MAX_INCOMING_ARGS`** — a working calling convention narrowed to suit an unwritten theorem is the substitution the filing warned against |
| `FORMAL_x86_64_step_lemma_cqo_states_cdq.md` | **`lib/X86.lean` does not elaborate, so EVERY `--formal` build with a proof fails on both backends.** `x86_step_cqo` still states `cdq` (`x86_sign_extend32`) after `da151f0c` corrected the model's arm to `x86_cqo`, so the lemma is a different instruction from the one the model decodes. Two lines, measured to elaborate clean on a scratch copy. Read this before concluding that any formal build "needs `--no-prove`" — it does not, the library is simply red |
| `CODEGEN_bootstrap_resource_blowup.md` | the ~192 GB runaway, the 55 GB ceiling, attribution |
| `CODEGEN_noshim_dumpfull_preexisting_divergence.md` | native-vs-reference `.ci` divergence |
| *(deleted 2026-09-30)* | the nested-comprehension cluster is CLOSED on both the compiled and the formal backends: a 2+ clause comprehension no longer drops clauses (`_compr_pending_inner`), and the formal backends no longer exit 58/SIGSEGV at random — `_emit_range_list` gave every `range()` in a function one shared `_rabs` label, so the first range branched into the second's block and left through the second's `jmp div_label`. See the two commits on `work/codegen-old-divergences` and the cases in `test_x86_64_containers.py` |
| `DOCS_merge_left_citations_of_the_docs_the_branches_deleted.md` | merging eight formal branches deleted 14 bug docs and left 12 citations of them, one of them a stale `precondition` assertion in `test_formal_sweep.py` that is RED on `master` today; the inventory, the split between the historical `was X, deleted` convention and the eleven that mislead, and the walk that finds them |
| `FORMAL_sweep_work_map_2026-10-01_b3.md` | the b3 tree swept on BOTH architectures (630 files each, one tree): ranked causes, the first same-tree arm64-vs-x86-64 comparison (56 files, one ABI constant), the instrument's two splits of the `other refusal` bucket, and which cause is owned by which claim. **Read this before planning any formal work — it is the only map whose architecture comparison is real** |
| *(deleted 2026-10-01)* | the multi-clause comprehension cluster is CLOSED for all four kinds: `set`/`dict` no longer drop every clause after the first (each merges with the runtime call its semantics need — `mojo_set_update` per element, `mojo_dict_update` per pair — and both now walk the source in INSERTION order, which a merged result's iteration order and repr both report), and a comprehension whose element is a container now carries `_nested_elem_types` / `_tuple_slot_types` across, so a 0 in a non-first slot reads as an int instead of NULL printing `None`. A heterogeneous list RETURNED BY A CALL reads its slots boxed, so a float slot is no longer handed to `strlen` (SIGSEGV). Regressions in `test_runtime_diff.py`; the adjacent shapes still open are in `CODEGEN_nested_container_as_dict_key_or_tuple_slot.md` |
| *(deleted 2026-10-02)* | the cross-module frame hand-off did not work for a free function's struct parameter, and the contract it needed — a per-parameter `frame_params` table on every export entry — was not published for a module that declared no framed struct. **Both fixed**: `_export_frame_contract` publishes for EVERY function, and `test_formal_cross_module.py` pins the published table, a layout disagreement refused by name, and a plain-parameter disagreement. No longer open; the row stayed because the sweep map cites it |
| *(deleted 2026-10-02)* | the two x86-64 backend gaps (both fixed): a bracketed callee this unit does not compile is now an EXPORT gap asked before it is a specialization gap (`formal/build.py`'s `_bracketed_export_gap`), and a bare call to a name the link line does not publish says so instead of reaching the assembler. Both landed with `work/formal3-2-r2-r2` and `work/formal3-5`; the row stayed because `formal/model.py` and `test_formal_x86_64_parity.py` still cite the doc in their comments (see `bugs/DOCS_merge_left_citations_of_the_docs_the_branches_deleted.md`) |
| *(optional, not a bug)* | **`struct.mojo`'s `pack` still has five value slots and could have eight.** `formal/hostmods/struct.mojo` declares that "a format naming more than five values cannot be packed here" and declines by returning an empty list; with both conventions landed (above) a `pack(fmt, v0..v7)` call is expressible on both backends, so widening the slots changes what the module can ANSWER rather than what it can reach. `<HHHHHH` (6 bytes) and `<4sBBBBBBB5x` (16 bytes) are both already in its buffer-size ladder and would become PACKED; `<IIQQQQQQ` (56 bytes) has no ladder entry and would still decline. The value slots would have to be DEFAULTED, since a slot past `_nvalues(fmt)` is never read. This lived in `FORMAL_struct_pack_over_eight_arguments.md`, which is deleted because its BUG — the decline being unreachable — is fixed |
| `FORMAL_string_value_model.md` | what a string IS on the formal path, `len`/`==`/`+` on it, and the `String`-struct collision behind the 16 "a String receiver" refusals |
| `FORMAL_arm64_instruction_coverage.md`, `FORMAL_arm64_known_proof_gaps.md`, `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` | arm64 work — not duplicated here |
| `FORMAL_formal_frame_size_bounds_recursion_depth.md` | neither backend guards the stack: a fixed 128 KiB (arm64) / 16 KiB (x86-64) frame per call and no depth test, so recursion past 61 (arm64) or 450 (x86-64) frames is a SIGSEGV and not a refusal. **Both backends.** |
| `FORMAL_method_call_on_a_subscripted_receiver.md` | the 17 of row 4's 25 files whose receiver's STRUCT is not established, so `_rewrite_method_calls` cannot lift the call: the four shapes of receiver, where each one's type would come from, and the 4 whose diagnostic is measurably wrong (a LINK diagnosis for a CODEGEN problem). Needs receiver-type inference — `construct:formal-value-model-gaps` |
| `FORMAL_frame_receiver_handoff.md` | who can take a frame address: the cross-module method hand-off (a binding bug, fixed), `Pointer(to=frame)` (an unjustified refusal, fixed), `origin_of` (the same mistake again — a compile-time intrinsic with no body, so no dereference for the sentence to describe; fixed), whether the frame layout and the struct's C layout coincide (measured: they do, for 8-byte fields), the three refusals that named a cause which was not operating, and the constructor-assigned field type that closed the `field slot holds a frame address` family (10 files → 2) |
| `FORMAL_frame_by_value_ceiling_zero.md` | map rows 7 and 8 of the sweep work map, **measured at a ceiling of 0**: 26 files, both refusals lifted behind a temporary guard, not one reaches `pass`, and 10 of the 26 land in a chain whose end is a documented permanent limit. Carries the per-file landing table, which is the deliverable. Two of the row-7 sub-shapes are now FIXED and the landing table is measured after both: `origin_of` (`14a2e42d`) and a subscript's argument list (`30e5e2e9`) — 4 of the 7 files move to a true refusal, 0 reach `pass` |
| `FORMAL_dotted_base_bracket_list_is_not_classified.md` | the remainder of the closed `FORMAL_type_argument_read_as_a_container.md`: a subscript over a name this unit cannot classify (`external_call["sym", T]`'s 55-file half belongs to `formal-extcall-tuple`) keeps its refusal, because deciding it needs the imported module's declarations and `formal/imports.py` owns those. 0 swept files today |
| `FORMAL_elif_arms_and_random_mojo_remainder.md` | `IfStmt.elifs` is a list of TUPLES and a `comptime if` is a distinct NODE, so a walk that recurses on `isinstance(node, list)` stops at the first `elif` and never sees a comptime branch at all — while `model.iter_nodes` walks both, which is why a REWRITER and a CHECK disagree and the check misreports a program the rewriter already handled. `_rewrite_method_calls` and `mojo/middle/boundnames.py`'s `_lbn_walk` are FIXED (on `work/formal5-slice-env-random`, with cases); **four more sites in `formal/build.py` have the same hole and each costs a WRONG ANSWER, not a diagnostic** — `_rewrite_self_fields`, `_rewrite_one_word_nested_field`, `_apply_receiver_writeback` (a dropped mutator store), `_rewrite_dotted_child`. **Both architectures.** The doc also carries `std/testing/prop/random.mojo`'s measured remainder (a keyword-only constructor that does not parse, a no-field struct with a required-arg `__init__`, and generic `rebind[…]` monomorphization, which is `FORMAL_known_limits.md` §1.2 Stage 5) |
| `FORMAL_callee_no_def_ceiling_zero.md` | the work map's row 8, "callee has no definition on this path": the ceiling is **0 of the 11 imported free functions** (and 0 of 12 before the re-measurement), and the row's one sentence was standing for five facts — an imported free function (26 files over `std/`+`test/`), a compile-time parameter, an MLIR-yielding intrinsic, a star-imported name, and genuinely unbound. All five sentences landed, and so did the cross-image per-parameter contract that lets the hand-off be a decision rather than an admission. What is left in it is Lean (`OPUS-4`/`OPUS-6` in `FORMAL_OPUS_dylib_termination_handoff.md`), so nothing here is a `formal/` change |
| `FORMAL_frame_refusal_preempts_the_import_diagnosis.md` | every frame refusal is raised before `_resolve_imports`, so a file that both trips a frame clause and imports something is reported as a `codegen` gap in itself — 80 in-scope files, 6 of 12 measured to change class. Fixing it re-numbers six rows of the map at once |
| `FORMAL_aliased_reexport_publishes_the_wrong_name.md` | `from leaf import base as aliased` in a package `__init__` publishes `base`; a consumer's `aliased(21)` cannot bind |

---

## A. The todo list this came from

Verbatim, with the current measured state attached to each. Ordered as I would
take them.

### A1. `call_rel32` — WIRED, no longer a blocker — **done, needs a run**

`x86_step_call_rel32` exists in `lib/X86.lean` and **is now** wired into the
generator's `_FORMS`/`_SUCCS`/`_resolve` trio
(`formal/x86_64_endtoend_test.py`: `_FORMS` at :177, the successor expression at
:259, the literal-address substitution at :429). `lib/X86.lean` also grew the
call/return *pairing* section — `x86_call_post`, `x86_ret_post`,
`x86_at_target` and the stack round-trip theorem — which is the "two successors
and a memory write" work this item said was real design rather than a wiring
change.

**Measured 2026-09-30 (`_plan` over `formal/examples`, no Lean):** `call_rel32`
is named as a missing lemma by **0 of 45** examples. Six plan clean *through*
it — `count`, `fact`, `fib`, `pow2`, `sqsum`, `sum` — and none is blocked by it.
So it is no longer on the critical path, and the "7 examples" figure in the
header below is what it was on 2026-09-26.

**What remains is verification, and the code says so itself**: the entry is
commented `NOT VERIFIED. This was wired without running the suite`, with the
open risk named as the continuation AT the target — a call's `rip` is
`m + 5 + off`, a literal supplied by the generator, and whether the path from
there re-enters a block whose certificate is wired is a question only a run
answers. Running `formal/x86_64_endtoend_test.py` settles it, and it needs Lean
runs this worker is not permitted to start; it belongs with the integrator.

What the remaining blockers actually are, same measurement: `movsx_r64_r8` (3),
`alu_ri32` (3), and one each of `alu_rr`, `shift_imm8`, `cqo`, `group3`,
`lea_r64_rm64`, `mov_r64_rm64`, `mov_rm64_r64` — i.e. A2 below, which is now
the whole of the uncovered-form work.

### A2. `movsx_r64_r8` (3 examples) + 8 one-example forms — **medium**

With `call_rel32` done (A1) this is now the WHOLE of the uncovered-form work.
The forms below are what `_plan` names as missing across `formal/examples`,
measured 2026-09-30: `movsx_r64_r8` (3), `alu_ri32` (3), and one each of
`alu_rr`, `shift_imm8`, `cqo`, `group3`, `lea_r64_rm64`, `mov_r64_rm64`,
`mov_rm64_r64`.

The list above names the old forms (`alu_rr:and`/`:or`/`:xor`, `alu_rr32:xor`,
`shift_imm8:shl`/`:shr`, `group3:div`, `alu_ri32:and`) because that is the list
this item was written from; where the measurement disagrees, the measurement
wins — note that `cqo` and `lea_r64_rm64` were not on it, and `alu_ri32` is
reported once as a family rather than per sub-op. One lemma each, and most
follow an existing shape — see the generalisation rule at the end of A4.

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
   reachable objects or a leak. Do this first.

Two causes now measured, both fixed at their call sites or worked around, and
both worth knowing before the next bisect because they produce the same
"it got slower and bigger" symptom by different means:

- `CODEGEN_selfhost_tokenize_region_eq_quadratic.md` — the self-hosted
  tokenizer's own closing-triple-quote scan is quadratic in each string
  literal (a runtime length check rescans from byte 0 on every character):
  0.05 s under python3, 2.5 minutes self-hosted, for `myinterpreter.py`,
  before a single statement is compiled.
- ~~`CODEGEN_container_eq_is_pointer_identity.md`~~ — **LANDED 2026-09-30.**
  `==` / `!=` between containers is Python value equality on the compiled path
  (runtime `mojo_set_eq` / `mojo_list_eq` / `mojo_dict_eq` / `mojo_value_eq`),
  diffed against CPython case by case in `test_container_equality.py` (24
  cases). Doc deleted. The ordering siblings (`<`, `<=`, `>`, `>=`) landed with
  it on 2026-10-01 — `test_container_ordering.py`, 35 cases.

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

### D4. Two finished branches each built the whole returned-frame convention, differently — **needs a decision**

`work/formal-string-return` and `work/formal-frame-escape` diverge from the
same commit and each implemented the caller-owned-block convention in full —
prologue, call site, model and its own refusal family. Merging the second onto
a tree carrying the first was attempted and aborted: 22 conflict regions over 8
files, and the two disagree about the *shape of the table the backends read*
and about the **arity of the predicate** `model.struct_returned_frame_sites` is
called with, so neither tree passes the other's tests
(`TypeError: _p() takes 1 positional argument but 2 were given`).

Neither is half-applied; both branches are intact. The map, the evidence, the
argument for which table shape to keep, and the five steps to reconcile are in
`FORMAL_returned_frame_two_incompatible_designs.md`. **Do not resolve it by
keeping both tables** — they answer the same question for the same image, and
which one a backend reads would then depend on which was assigned last.

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
