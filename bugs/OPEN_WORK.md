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
| *(deleted 2026-10-03)* | **and the last row left of it is gone too**: `lib/ProofLib.lean`'s `MojoFunc`/`evalFunc` bind every parameter by position (`MojoEnv`, `mojoEnv_binds_by_position`), and what was still one-input after that — `mojo` itself, `eval_eq_mojo`, every run test, the universal theorem's entry state, and the startup stub's argument registers — is now at the ENTRY's arity, read once through `formal/model.py::entry_arity`. A two-parameter entry point is proved on both architectures (`formal/examples/twoparams.mojo`, 0 `sorry` on arm64), and it runs: `main(n, m)` answered 90 before, because `x1` held `argv` |
| *(deleted 2026-10-02)* | **both halves of the stack-argument convention are proved per-instruction now.** `FORMAL_x86_64_step_lemma_cqo_states_cdq.md` is gone because `lib/X86.lean` did not elaborate at all: `x86_step_cqo` stated `cdq` (`x86_sign_extend32`) after `da151f0c` corrected the model's arm to `x86_cqo`, so the lemma was a different instruction from the one the model decodes and the whole library failed to build — every `--formal` build with a proof was red on both backends, and every job that `deps` on `prooflib` was SKIPPED rather than run. Read this row before concluding that any formal build "needs `--no-prove`": it does not, and after the fix `formal-x86-endtoend`, `formal-x86-model`, `formal-ast` and `formal-sweep-truth` run again instead of skipping |
| *(deleted 2026-10-02)* | **the disp32 stack-argument load is gone too, and it was a third of the gap rather than all of it.** `FORMAL_x86_64_stack_argument_past_the_twentieth_needs_a_disp32_lemma.md` named the callee's side — `x86_step_mov_rm64_mem_disp32`, applicable at a real encoding (`formal/x86_64_model_coverage_test.py`, 20 lemmas / 43 encodings / 421 hypotheses) — but a stack argument past the twentieth is an instruction on BOTH sides of the call, and the CALLER's half was the bigger gap: every argument past the register file is stored through `[rsp + disp]`, which has no non-SIB encoding at any displacement, so `x86_step_mov_mem_sib_disp8` and `x86_step_mov_mem_sib_disp32` were needed for ANY call with a stack argument rather than only for the widest ones. All three are in `lib/X86.lean` and wired into `formal/x86_64_endtoend_test.py`. What the disp32 one is NOT is reachable from a generated proof: a 24-argument path is ~130 instructions and the closing `simp` times out, which is `FORMAL_x86_64_endtoend_chain_times_out_past_a_hundred_steps.md`. `_MAX_INCOMING_ARGS` stays 24 — the substitution this row warned against has not happened |
| `FORMAL_trust_audit_2026-10-04.md` | **the trust boundary, audited: 15 of the 19 admitted host contracts were FALSE of the real host.** Every instrument `formal/admitted.py` had — the per-module count, the scope rule, the emitted declaration, the inertness check — decides FORM, and all four were green on contracts that asserted the child's exit status is `0..255` (CPython reports `-N` for a death by signal), that captured output is an arbitrary byte string (a `str` here is NUL-terminated), that `poll` answers `-1` while running (`-1` is a `SIGHUP` death), that a killed child's handle still receives its signal (`Popen.send_signal` returns once collected), that `dlopen` failing means the library is absent (it fails on files that exist), and that `threading.Lock` is a kernel lock on a descriptor (it is a userspace semaphore, and a child took `flock` while this process held one). All corrected, and §7/§7a's own published census (15 across five modules; `subprocess` 7, `fcntl` 1) was stale and is now CHECKED in both directions. What is left: one limit of the scope rule. Its OTHER remainder, `FORMAL_native_decide_axiom.md`, is closed as a measurement and its numbers were wrong — the axiom is a per-use `t32s_t8s._native.bv_decide.ax_1_5`, NOT `Lean.ofReduceBool` (0 of `lib/`'s 375 theorems report it), and the 749 `native_decide`/`bv_decide` sites were an undercount (751) belonging to **53 theorems, with 304 kernel-checked**; §7's preamble and row 10 are corrected and `test_formal_sweep_truth.py::TestAxiomClosureCensus` pins it. What was left here — a claim about host STATE attached to a value by the word "meaning" passes seven banned adverbs — is CLOSED: `contract_text_is_scoped` has a third, structural rule (`value_attached_claim`) and `test_formal_admitted.py`'s `SCOPE_PROBES` is its instrument |
| `FORMAL_ast_bridge_carries_one_argument_per_call.md` | **the VALUE of a call is unprovable for two arguments and up.** `MojoExpr.call` carries ONE argument and the bridge's `callFunc` stub answers 0 for a user function's name, so a five-line program (`return f(1, 2)`) generates an AST that is false and fails with `⊢ False`; on arm64 the same program is refused earlier, for a different reason (the CFG walk is per-function). A sibling of the `MojoFunc` arity row above and NOT on its list of steps, so closing that one does not close this one — a seven-argument function is unprovable until both are |
| `FORMAL_dylib_export_loops_and_frame_bounds.md` | **`OPUS-4` only: the loop-fuel obligation, and it is the one piece left.** `OPUS-6` (x86) is closed — and the measurement found a defect rather than a number: `--backend` is a GLOBAL flag the `dylib` command never read, so `dylib --formal --backend=x86_64` built an **arm64** image, and `compile_formal_dylib(arch="x86_64", prove=True)` raised `KeyError` out of the arm64 generator. Both are now refused by name (`compile_formal_dylib` refuses, `fire.py` checks first with a better message), so there is no x86-64 dylib **contract** to classify. `OPUS-5`'s premise was wrong and is corrected in the document: `FrameBound` is already depth-indexed (`stride * (arg.toNat + 1) <= sp`, `contract_sound` inducts on `k` with `arg.toNat = k`, `frameBound_succ` is the step, `stride` comes from the emitter's frame layout), so the `bl` case is missing the recursion contract's per-level base/step walks and nothing in the library. What is left is `OPUS-4`: a ranking function or a fuel invariant for a looped export, a scheme extension scoped in the document §6 |
| `CODEGEN_bootstrap_resource_blowup.md` | the ~192 GB runaway, the 55 GB ceiling, attribution |
| `CODEGEN_noshim_dumpfull_preexisting_divergence.md` | native-vs-reference `.ci` divergence |
| *(deleted 2026-09-30)* | the nested-comprehension cluster is CLOSED on both the compiled and the formal backends: a 2+ clause comprehension no longer drops clauses (`_compr_pending_inner`), and the formal backends no longer exit 58/SIGSEGV at random — `_emit_range_list` gave every `range()` in a function one shared `_rabs` label, so the first range branched into the second's block and left through the second's `jmp div_label`. See the two commits on `work/codegen-old-divergences` and the cases in `test_x86_64_containers.py` |
| `DOCS_merge_left_citations_of_the_docs_the_branches_deleted.md` | merging eight formal branches deleted 14 bug docs and left 12 citations of them, one of them a stale `precondition` assertion in `test_formal_sweep.py` that is RED on `master` today; the inventory, the split between the historical `was X, deleted` convention and the eleven that mislead, and the walk that finds them |
| `FORMAL_sweep_work_map_2026-10-01_b3.md` | the b3 tree swept on BOTH architectures (630 files each, one tree): ranked causes, the first same-tree arm64-vs-x86-64 comparison (56 files, one ABI constant), the instrument's two splits of the `other refusal` bucket, and which cause is owned by which claim. **Read this before planning any formal work — it is the only map whose architecture comparison is real** |
| `FORMAL_the_host_import_rows_after_glob_ranked_by_what_they_actually_spell.md` | **the host-import rows after `glob`: `glob` was the last row that was both large and reachable, and the "next 4-6 modules by files blocked" does not exist as stated** — the rows under it are 22, 11, 10, 10, 4 and 4 files, the 22 is CLAIMED (`module:platform+fnmatch+collections-rest`), two are type factories whose capability has a doc and an owner, two need an object this target does not have, and the rest are 1-4 files. What `glob` moved, measured over its 50 blocked files: **42 of 50 changed class, 0 reached pass**, and 35 of the 42 land on ONE row (`cas.py:164`'s handler arm, `FORMAL_except_arm_is_never_emitted`, `formal8-5`) — a REFUSAL that is correct, because `formal` has no unwinder. Still open and unclaimed: **`shlex.quote` (1 file, the cheapest row in the census)** and `random`'s two module-level spellings (4 files, 2 reachable). Succeeded two host-import rankings, both **deleted with their queues** (2026-10-04): the `-5` sweep's (`stat`/`math`/`shutil`/`fcntl` and then `glob` landed; `subprocess`/`copy`/`ctypes`/`concurrent.futures` decided) and the 2026-10-03 one (`tempfile`/`textwrap`/`posixpath`/`html`/`glob` landed, and its last open item — `zlib` — measured to **0 uses**: three DEAD `import zlib` lines were the whole 27-file row, and they are deleted) |
| `FORMAL_std_os_io_scope_is_decided_by_five_modules_outside_the_claim.md` | **the `std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` sweep scope is 46 files, 3 of which build, and not one link of the chain that blocks the other 43 is inside the scope.** The `codegen` (in-file) class is **0** on both architectures after the dialect-EFFECT-statement lowering, so the scope's coverage is 6.5 % and everything left is `codegen/dependency`. `tools/formal_chain_probe.py` measures the chain the sweep reports only the terminal link of: 40 files behind `binary_heap.mojo`'s `pop()` (a PREP-time refusal whose named repair is a **stdlib edit, undeliverable from a repository worktree**) and then `std/algorithm/backend/tile.mojo`; 3 files behind `builtin_slice.mojo` alone, one link shorter. Read §2 for the link/owner table and §3 for why this claim cannot walk its own chain | 
| `FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` | **`std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu}` (the round-2 scope: `python` and `_gpu` in, `sys` and `time` out) is 46 files, 3 build on BOTH architectures, and all 43 of the rest are TWO features — max chain depth 1.** Round 1's chain (`binary_heap.mojo` → `tile.mojo` → `builtin_slice.mojo`, 40 files) **is gone** — the per-edge export gate landed — and **not one of the 43 names any of those three modules**. 37 are one feature (a bare call to a generic template whose type arguments are inferable: `FormatStruct` ×22, `dealloc` ×11, `align_up` ×2, `is_negative` ×1, `stat` ×1 — `formal19-1`'s), 6 are the other (a module with only module-level constants cannot be a dylib — `formal16-2`'s). **So this scope has no construct of its own left to lower, and closing link 1 does not move it: with `FormatStruct` answered the same 37 files reach `dealloc`, the same feature.** It also carries the three `tools/formal_chain_probe.py` defects that measurement exposed — the largest being that a resolution outside the throwaway copy was actionable and the stub step's next act is `write_text`, so the walk could have overwritten the real stdlib — plus §6's open item that `tools/formal_sweep_causes.py` cannot rank either feature (21 of 22 groups print NOT MEASURED) |
| `FORMAL_binary_heap_mojo_after_the_len_value.md` | **the largest row in the sweep (165 files) has TWO walls, and codegen was only the first.** `std/collections/binary_heap.mojo` was filed under `len(self._data)` — "a slot's declared type is not a value this path can supply" — and that refusal is FIXED (three defects, none of them the refusal's own text; the sweep map called its probe "a stdlib edit and therefore not makeable from a repository worktree", which was wrong). **0 of 10 re-measured files move anyway**, and with every codegen refusal in that file bypassed the module-dylib build fails at the export gate with the message the sweep already carried. **§3 row 0 (`pop(mut self) -> Self.T`, the file's own verdict for months) is FIXED as of 2026-10-03** — the receiver is handed over by reference, so the return register carries the popped element and the file's reported verdict moved to row 0a (`self.clear is not a field of BinaryHeap`), which is the one-word rewrite and is another claim's write set. **0 of the 165 still move**: wall two is the export gate and no codegen work on this file touches it. Read §2 before planning §3, and §3 before working this file |
| `FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it.md` | **`os.environ` is a real view now, and the row behind it was worth 0 passes.** `formal/hostmods/os` had said for months that `environ` "needs a `char **` walk" and that the three POSIX calls were all `os.environ[k]` could become. Both wrong: the walk was available (`os/_syscalls.mojo`'s `fs_environ_vec` asks the dynamic loader for the `environ` global at RUN time), and `getenv` answers `""` for both "set to nothing" and "not set", which a dict does not. So there is a snapshot blob with twelve operations over it, differential-tested against CPython on both backends against a FIXED environment (an inherited one cannot answer it — a shell adds `_` to a child's block and cannot add it to a parent that has already started). **The b8 map's §4.2 four files move off the `os.environ` refusal and 0 move to `pass`**: hand-rewriting the two in-file spellings lands one on a struct-receiver `write` and one on `sys.exit()`, which that map records as deliberately not taken. So an importer rewrite is priced, not proposed. Also carries the `p + k` trap this walked into — byte arithmetic on a typed pointer, in every spelling, unguarded when it is passed to a libc call rather than dereferenced |
| *(deleted 2026-10-04)* | **two of six FULL runs of `test_formal_os_backing.py` are 56/58, and both times the same pair** — `stat_dangle` and `stat_fifo` on arm64, `exit -9` with empty stderr, `memcap` peak 0.1 GB. Run alone, `stat_fifo` is 6/6. The cases link no code that changed, and they fail only with three builds in flight, so this is C2's "a SIGKILL here is evidence of nothing" and NOT a module defect — recorded because the report reads as one. **Fixed in the RUNNER, which is where its next step said the fix was**: `test_formal_os_backing.py` now normalises both its children through one `exit_status`, which reports a death by SIGINT/SIGKILL/SIGTERM as 128+signum with the signal named and `killed` True, tags the case `[KILLED]`, and counts those separately in the summary — still a FAILURE, because a killed case obtained no answer and no answer is not a pass, but no longer printed in the shape of a wrong answer. A FAULT (SIGSEGV, SIGBUS, SIGFPE, SIGILL, SIGABRT) is the image's own doing and stays an ordinary failure, tagged or not. The premise re-measured before landing: the two cases alone, six times, 4/4 every time at a 65 MB peak |
| `FORMAL_a_one_field_mutator_has_no_method_contract.md` | **the Lean half of the by-reference receiver, and the only part of that project still open.** The receiver convention itself landed 2026-10-03 (`work/formal15-mutator-return-abi`): a mutating method of a one-field struct receives the ADDRESS of its caller's one-word cell and writes the receiver back on every exit, which is what lifts `mutating_receiver_return_refusal` and lets `BinaryHeap.pop()` lower. `formal/arm64_proof_gen.py`'s `_frame_methods` now EXCLUDES such a method by name, because its premise (`x0` at entry is the receiver FRAME) is false under the new convention and it was being dropped only by an accident of the entry sequence. **What is left is the contract**: three things it would have to say, none with an answer today — the cell is the CALLER's frame and nothing bounds its depth, the constant propagation starts from "x0 arrives as the receiver" and has to learn a load-first rule, and the write-back repeats on every exit so the frame-store peel needs a case obligation. The x86-64 backend has no frame-contract machinery at all, so that half is a port and not a change |
| `FORMAL_sweep_work_map_2026-10-02_std-b.md` | sweep slice `std-b` (40 stdlib files, arm64): the class counts before and after three landed fixes, and a gate probe that measures what is behind `binary_heap.mojo` — **0 files move**, so the export rule is NOT this slice's constraint and what is behind it is a documented MLIR limit (17 files) plus monomorphisation. Read §5 before working §4 |
| *(deleted 2026-10-01)* | the multi-clause comprehension cluster is CLOSED for all four kinds: `set`/`dict` no longer drop every clause after the first (each merges with the runtime call its semantics need — `mojo_set_update` per element, `mojo_dict_update` per pair — and both now walk the source in INSERTION order, which a merged result's iteration order and repr both report), and a comprehension whose element is a container now carries `_nested_elem_types` / `_tuple_slot_types` across, so a 0 in a non-first slot reads as an int instead of NULL printing `None`. A heterogeneous list RETURNED BY A CALL reads its slots boxed, so a float slot is no longer handed to `strlen` (SIGSEGV). Regressions in `test_runtime_diff.py`; the adjacent shapes still open are in `CODEGEN_nested_container_as_dict_key_or_tuple_slot.md` |
| *(deleted 2026-10-02)* | the cross-module frame hand-off did not work for a free function's struct parameter, and the contract it needed — a per-parameter `frame_params` table on every export entry — was not published for a module that declared no framed struct. **Both fixed**: `_export_frame_contract` publishes for EVERY function, and `test_formal_cross_module.py` pins the published table, a layout disagreement refused by name, and a plain-parameter disagreement. No longer open; the row stayed because the sweep map cites it |
| *(deleted 2026-10-02)* | the two x86-64 backend gaps (both fixed): a bracketed callee this unit does not compile is now an EXPORT gap asked before it is a specialization gap (`formal/build.py`'s `_bracketed_export_gap`), and a bare call to a name the link line does not publish says so instead of reaching the assembler. Both landed with `work/formal3-2-r2-r2` and `work/formal3-5`; the row stayed because `formal/model.py` and `test_formal_x86_64_parity.py` still cite the doc in their comments (see `bugs/DOCS_merge_left_citations_of_the_docs_the_branches_deleted.md`) |
| *(optional, not a bug)* | **`struct.mojo`'s `pack` still has five value slots and could have eight.** `formal/hostmods/struct.mojo` declares that "a format naming more than five values cannot be packed here" and declines by returning an empty list; with both conventions landed (above) a `pack(fmt, v0..v7)` call is expressible on both backends, so widening the slots changes what the module can ANSWER rather than what it can reach. `<HHHHHH` (6 bytes) and `<4sBBBBBBB5x` (16 bytes) are both already in its buffer-size ladder and would become PACKED; `<IIQQQQQQ` (56 bytes) has no ladder entry and would still decline. The value slots would have to be DEFAULTED, since a slot past `_nvalues(fmt)` is never read. — DONE in `work/formal4-sweep-repo-c-r2` (`pack`'s five slots are now `=0`); only the WIDENING is left. This lived in `FORMAL_struct_pack_over_eight_arguments.md`, which is deleted because its BUG — the decline being unreachable — is fixed |
| `FORMAL_string_value_model.md` | what a string IS on the formal path, `len`/`==`/`+` on it, and the `String`-struct collision behind the 16 "a String receiver" refusals |
| `FORMAL_arm64_instruction_coverage.md`, `FORMAL_arm64_known_proof_gaps.md`, `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` | arm64 work — not duplicated here |
| `FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md` | the guard is emitted in every function on a call-graph CYCLE, so runaway recursion is a refusal on both backends (`deep` past 59 arm64 / 471 x86-64 exits 2, was a SIGSEGV). What is left is a chain of DISTINCT functions deep enough to exhaust the stack — finite depth, and nothing to stop it. The blocker is the per-export contract's "a `Refine.Block` is one function of one state", which is why the guard cannot simply widen. **Both backends.** |
| *(deleted 2026-10-03)* | **a method call on a SUBSCRIPT receiver now lifts wherever the source names the element type.** `FORMAL_method_call_on_a_subscripted_receiver.md` was the 17 of row 4's 25 files whose receiver's STRUCT was not established, so `_rewrite_method_calls` could not lift the call; `model.receiver_struct` is the one reader of "which struct does this receiver denote", and `formal/build.py::_subscript_receiver_target` asks it at the lift. A list literal of `T()` and a parameter declared `List[T]` both answer now (3 on both architectures where the refusal was a LINK sentence naming a bare `get`); a parameter annotated only `List` is still refused for the receiver's TYPE, and a name `owners` knows must not be bound to the struct that declares it when the receiver holds another (`test_formal_receiver_position.py`'s GUARD). The four receiver shapes and where each one's type would come from were the doc's inventory, and it is deleted because its bug is fixed |
| `FORMAL_dotted_base_bracket_list_is_not_classified.md` | the remainder of the closed `FORMAL_type_argument_read_as_a_container.md`: a subscript over a name this unit cannot classify (`external_call["sym", T]`'s 55-file half belongs to `formal-extcall-tuple`) keeps its refusal, because deciding it needs the imported module's declarations and `formal/imports.py` owns those. 0 swept files today |
| *(deleted 2026-10-05)* | **`std/testing/prop/random.mojo`'s three constructs from building are all FIXED, and the doc that carried them is deleted with the last of them.** `Rng(seed=7)` binds: a keyword DOES name a parameter, so `model.construction_keyword_refusal`'s selection runs over the whole CALL — positionals in declaration order up to the keyword-only boundary, plus the parameter names the keywords give — and the `why == "init"` arm, which was unreachable because `unmatched = [k for k, _v in kwargs if k not in slots]` ran first, now fires (`ffcd9542`; two constructors that both admit the call are still `ambiguous` rather than a guess, because the path resolves nothing by TYPE). The four `elif` walks went earlier (`work/formal8-5`): `_apply_receiver_writeback` was a DROPPED STORE (10 where the source says 15, both architectures) and `_rewrite_self_fields` a refusal. What remains from that row is unowned and unfiled rather than filed: `rebind[Scalar[dtype]]` is `FORMAL_known_limits.md` §1.2 Stage 5, and a no-field struct with a required-arg `__init__` is refused with a message that denies the constructor exists. |
| `FORMAL_callee_no_def_ceiling_zero.md` | the work map's row 8, "callee has no definition on this path": the ceiling is **0 of the 11 imported free functions** (and 0 of 12 before the re-measurement), and the row's one sentence was standing for five facts — an imported free function (26 files over `std/`+`test/`), a compile-time parameter, an MLIR-yielding intrinsic, a star-imported name, and genuinely unbound. All five sentences landed, and so did the cross-image per-parameter contract that lets the hand-off be a decision rather than an admission. What is left in it is Lean (`OPUS-4` in `FORMAL_dylib_export_loops_and_frame_bounds.md`, and `OPUS-6` there is closed — the x86-64 refusal was a *missing generator*, not a measurement), so nothing here is a `formal/` change. The clause every arm opens with now has a test: `test_refusal_taxonomy.py`'s `_no_def_callee_arm_checks` asks it at the source, one callee per arm (six, not five — `UNIMPLEMENTED_BUILTINS` was added later) |
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
