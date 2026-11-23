# GIR stages 6 and 7: stage 6 (passes of `gen_module_impl`) is finished; stage 7 is open

Plan source: `doc/GIR.md`, Stage 6 (counted loops, arms of the giant functions, passes of
`gen_module_impl`) and Stage 7 (the other printers, including the C++ coroutine lowering in
`cpp_core.py`).

## Still open

- The builder half of stage 7: each of `cpp_core.py`'s five dispatch functions is now a list of
  one-line calls (see the fifth-round Status), but an arm still returns C++ **text**. Moving one
  arm at a time onto the IR is what remains. (Corrected 2026-11-22: `mojo/ir/build.py` DOES exist —
  stage 2b landed in `efa173346` — so the W2 claim this line used to name is not a blocker.)
- The W1 write-set line: the W1 `cpp_core` packet, which carried the `STOP: claimed` line on `cpp_core.py`, landed 2026-11-22 (its doc is deleted), so the write set is free.
  `python3 tools/control.py claims` lists no live holder, and this round's edit does not touch any
  of the 35 type-string sites the packet is about (counts unchanged: 11 / 12 / 12), so the packet
  can still run on top of it; only the orchestrator removes the line.

## Next step

Stage 7's remaining half, in this order:

1. Land `mojo/ir/build.py` (stage 2b, the builder lane's work; its doc was deleted with the lane's
   branch) — another lane's claim. Then move one arm at a time onto the builder, smallest first (`_cps_aug_assign` 32 lines,
   `_cps_import_stmt` 38, `_cpy_handle_local` 48, `_cpw_async_with` 90, ...), with
   `python3 tools/c_oracle.py check --base <the commit before> -j 4` reporting identical C **and**
   identical C++ companion for all 285 `tools/pydiff_corpus` programs and all 13 `tools/cpp_corpus`
   programs.
2. If the builder is still elsewhere, any further `cpp_core.py` split (for example the 363-line
   `for_target_is_tuple` arm, which `extract_arm.py` refuses) is independent of it; re-measure with
   `python3 tools/extract_arm.py --list mojo/backend_gimple/cpp_core.py <parent> 25`, which now
   prints `0 lines can be moved` for all five printers.

## Status 2026-11-22 (planning round, eleventh): measured remainder and the ordered port plan

Measured on `ef2094112` (`python3` over `cpp_core.py`, counting `f"{indent}` statement lines and
expression f-strings):

| arm | lines | text sites | kind |
|---|---|---|---|
| `_cpf_named_target` | 876 | 80 | statement lines (the largest single arm) |
| `_cps_assign_stmt` | 804 | 46 | statement lines (container, tuple, class-attr forms) |
| `_cps_expr_stmt` | 384 | 28 | statement lines (`printf` and call forms) |
| `_cpy_handle_local` | 50 | 13 | statement lines |
| `_cpf_call_iterable` / `_cpf_word_iterable` / `_cpf_param_call` / `_cpf_simple_target_call_iterable` / `_cpf_list_iter_cursor` / `_cpy_unsupported_shape` | 42-179 | 5-10 each | statement lines |
| `_cpw_async_with` | 93 | 4 | statement lines |
| `_cpf_generator_handle` | 35 | 3 | statement lines |
| `_cps_aug_assign`, `_cps_while_stmt` | 41, 59 | 2, 1 | statement lines (one or two left) |
| 11 `_cpx_*` expression arms | 32-2215 | expression f-strings | C++ **expressions**, not lines |

So: 0 of 30 arms are fully on the IR; 14 still build statement text; 11 build expression text (no
`{indent}` lines, so they are not counted above). Expression arms need an Ex printer for C++ (casts,
receivers, runtime-stub calls), which is a different job from the statement shapes.

**Ordered plan (each step one measured change, oracle identical, closure checked):**

1. `_cps_expr_stmt`'s `printf` and call lines (28 sites): a `call` Ex with `ex_text` arguments and the
   `fflush` line as a second `expr` (`build.call_void` is the existing builder for `f(args);`).
2. `_cps_assign_stmt`'s container forms (`mojo_list_set_*`, `mojo_dict_set_*`, `mojo_list_clear`,
   `mojo_list_extend`, `mojo_class_setattr`) as `call_void` shapes (46 sites; the tuple-unpack forms
   `mojo_list_get_int` / `mojo_iter_word` after).
3. `_cpy_handle_local`, `_cpy_unsupported_shape`, `_cpw_async_with`, `_cpf_generator_handle`, and the
   five small `_cpf_*` arms (about 40 sites together).
4. `_cpf_named_target` (80 sites, 876 lines): first split it with `tools/extract_arm.py` along its
   target kinds, then port each extracted arm as in steps 1-3. Do not port it whole.
5. The 11 expression arms, smallest first: `_cpx_slice_expr` (32), `_cpx_unary_op` (33),
   `_cpx_walrus` (42), `_cpx_compare_chain` (45), `_cpx_await_expr`, `_cpx_subscript_expr`,
   `_cpx_member_expr`, `_cpx_ident_expr`, `_cpx_binary_op`, `_cpx_lambda_expr`, and `_cpx_call_expr`
   (2215 lines) last. Each needs Ex shapes for the C++ forms it produces (a `cast` and a `call`
   with a receiver are already in `mojo/ir/instr.py`; a C++ `addr`/`index` shape may need adding).

Acceptance for the stage: every printer arm's return is built from `mojo/ir/instr.py` shapes, the
arms test pins 0 text sites, the oracle is identical on all 285 C and 13 coroutine programs, and the
closure stub set is unchanged.

**Stage 5c: the call-site analysis (planning, not built).** The fact the stored `None` and the scalar
store need is: for each unannotated parameter `p` of a function `f`, the kinds passed at every call of
`f` (`none`, a scalar literal kind, a struct instance, other). `mojo/middle/infra_infer.py` already has the
shape of this: `callsite_tagged_literal_params` (near line 2035) walks every bare-name call to a
module-level `def` and records the bool/None literal arguments. The extension is to record the kind of
every argument for every such parameter, and then to mark a field stored from `p` as scalar-only
(box-eligible) only when every call site passes a scalar literal, and as pointer (excluded) when any
call site passes a struct instance or an object of a class.

Acceptance (from the 5c doc): the reduction prints `42` and `None` under the runner; `pydiff` OK on
`classes/03_none_field_later_set.py`; `classes/12_linked_list_nodes.py` and
`classes/13_binary_tree_inorder.py` are not CRASH (WRONG is no worse than before); the oracle changes
only the programs that store `None` into a scalar-only word field.

## Status 2026-11-22 (ninth and tenth rounds): more statement headers on the IR

- `_cps_multi_assign_stmt` prints each `name = value;` through `_cpp_assign_line`.
- `_cps_if_stmt` builds its `if`, `else if`, `else` headers and every closing brace through
  `_cpp_ir_line` (`if` / `elseif` / `else` / `end` shapes, which `mojo/ir/instr.py` already had).
- Verified each against its base: `test_gimple_cpp_core_arms.py` 30/0; `c_oracle` identical on all 285 C
  programs and all 13 coroutine C++ companions; `--closure` no new stubs (3 == 3).
- Still text: the expression arms (`_cpx_*`, which are f-string expressions, not statement lines, so they
  need expression shapes, not headers), and the statement arms' bodies in `_cps_assign_stmt` (72 text
  lines), `_cps_expr_stmt` (30), and the `_cpf_*`/`_cpw_*`/`_cpy_*` arms.

## Status 2026-11-22 (eighth round): `_cps_while_stmt`'s header, guard and closers are on the IR

- `mojo/ir/instr.py` gained `while` (`while (<cond>) {`) and `break` (`break;`) shapes; `if` and `end` were
  already there.
- `_cps_while_stmt` builds its loop header, the yield-condition guard (`if (!(...)) { break; }`), the
  flag-tracked `if (!brk)`, and every closing `}` through `_cpp_ir_line`. Its body is still printed by the
  statement arms; the `bool _mg_brk` declaration is still text.
- Verified against `a47c26338`: `test_gimple_cpp_core_arms.py` 30/0; `c_oracle` identical on all 285 C
  programs and all 13 coroutine C++ companions; `--closure` no new stubs (3 == 3).
- Still returning text: 25 of 30 arms (`_cps_while_stmt` is partly on the IR, so it's counted with them).

## Status 2026-11-22 (seventh round): `co_return` is an IR shape; `_cps_return_stmt` is on the IR

- `mojo/ir/instr.py` gained a `coreturn` kind (`co_return;` / `co_return <expr>;`).
- `_cps_return_stmt` now builds all three of its branches from the IR: the helper `return` (earlier),
  the async `co_return <expr>;`, and the generator's value store plus `co_return;` (an `assign` followed by a
  `coreturn`), and the bare generator `co_return;`. No branch returns a literal text line any more.
- Verified against `6f4d25d30`: `test_gimple_cpp_core_arms.py` 30/0; `c_oracle` identical on all 285 C
  programs and all 13 coroutine C++ companions (the coroutine corpus exercises every `co_return` form);
  `--closure` reports no new stubs (3 == 3).
- Printer arms still returning C++ text: 26 of 30 (the `_cpx_*`/`_cps_*`/`_cpw_*`/`_cpy_*`/`_cpf_*`
  arms other than `_cps_aug_assign` and `_cps_return_stmt`).

## Status 2026-11-22 (sixth round): the first printer arm is on the IR; the "blocker" was a checker fault

Landed: `_cps_aug_assign` (the smallest arm) builds its `name = name op val;` line from the stage-2b
shapes (`Instr('assign')` with `ex_var`/`ex_bin`/`ex_deref`/`ex_text`, new in `mojo/ir/instr.py`), printed
by `_cpp_assign_line`. Behaviour is unchanged.

Verified against `5399414e1` (the commit before this round):

- `test_gimple_cpp_core_arms.py`: 30 arms, 0 failures.
- `c_oracle check`: all 285 `pydiff_corpus` programs identical C; all 13 `cpp_corpus` coroutine programs
  identical C++ companion (the corpus has `+=` inside generator and async bodies, so the arm is reached).
- `c_oracle check --closure`: no new stubs, 3 == 3 (`PRESENCE_WORD`, `_IDENT_CHARS`, `_NONE_TYPE_MARKER`
  on both sides).
- `compile_stdlib.py`: the same 18 unexpected failures as the pre-round base, same module set.

**Correction to the earlier "blocker".** Those three stubs were never new. They are in base too. The
earlier report came from a checker fault, fixed in `5399414e1`: a failed closure dump (the base dump was
killed at the old 8 GB memcap ceiling) was cached as a stub list, so the base and the tree were compared
against failure messages. The ceiling is now 20 GB. The three stubs are a pre-existing self-host gap
(module-level constants imported by `module_gen.py` and read in `resolve_shared.py`); they are not caused
by stage 7 and are not fixed here.

**Next arms** (one at a time, each with the same four checks): `_cps_while_stmt`, then the other
`_cps_*` arms smallest first. Each one needs its own expression shapes in `mojo/ir/instr.py`, because
the C++ text is built by the parent printer, not by `build.py`.

## Status 2026-11-22 (fifth round): stage 7's shape step is landed — all 30 printer arms are functions

Landed (one code commit, `89c65d3a1`): `tools/extract_arm.py` moved every top-level `if` arm of
`cpp_core.py`'s five dispatch functions into its own module-level function. No moved line was edited
by hand, apart from the one call spelling described below; the tool's AST-identity check accepted
every extraction.

| parent | before | after | arms |
|---|---|---|---|
| `_cpp_expr` | 3,566 lines | **101** | 11 `_cpx_*` |
| `_cpp_stmt` | 1,582 | **73** | 9 `_cps_*` |
| `_cpp_with_stmt` | 344 | **256** | 1 `_cpw_async_with` |
| `_cpp_yield_from` | 716 | **595** | 2 `_cpy_*` |
| `_cpp_for_stmt` | 1,846 | **456** | 7 `_cpf_*` |

`python3 tools/extract_arm.py --list mojo/backend_gimple/cpp_core.py <parent> 25` prints
`0 lines can be moved` for all five. The one remaining refusal is the 363-line
`for_target_is_tuple` arm (`binds name(s) read later: target`).

The two annotation questions the fourth-round plan flagged are answered from the compiler's own
dump (`python3 fire.py --dump mojo/backend_gimple/cpp_core.py`): `target` and `call` are erased
words (`int64_t target;`, `int64_t call;`), so both are passed **unannotated**, the same treatment
stage 6 gave `_gg_stmts`. `declared: dict` / `indent: str` / `s: 'ForStmt'` / `yf: 'YieldFromExpr'`
keep the parent's own spelling.

**One hand edit, and the latent bug it exposed.** The IfStmt arm's elif-chain recursion was the only
bare module-level printer call in the file (`return _cpp_stmt(gen, ...)`); it now reads
`return gen._cpp_stmt(...)`, the spelling of the other ~40 call sites (the method is a one-line
delegate in `gimple_codegen.py:5685`). With the bare call, extracting the arms makes
`python3 fire.py --dump cpp_core.py` fail after 142 s with `RecursionError` in
`_specialize_mixed_generator_callers`: `mojo.middle.coro`'s `_ParamFlow` (coro.py:1680) reports a
cycle of functions that each pass their own `gen` parameter on as "this parameter is the referenced
generator", then clones the callee `_cpp_receiver_ctype` until the stack overflows. Measured with a
depth probe: 4 `sources_ok` levels on the previous commit, 331 on the crashing variant. The
underlying defect (the cycle branch of `_ParamFlow.sources_ok` answering "fed" for a pass-through
cycle nothing feeds) is fixed in `mojo/middle/coro.py`, pinned by `test_coro_paramflow_cycle.py`; the
`gen._cpp_stmt` spelling is still used here and is pinned by the new test.

Verified:

- `python3 test_gimple_cpp_core_arms.py` (new): 30 arms across 5 printers, 0 failures. It pins each
  arm as a module-level function called once, the five parent line ratchets, the `0 lines can be
  moved` end state, and the no-bare-printer-call rule. On the pre-change file it reports **46
  failures**.
- `python3 tools/c_oracle.py check --base 3462c536c -j 4`: all 285 `tools/pydiff_corpus` programs
  generate **identical C**, all 13 `tools/cpp_corpus` programs generate **identical C++ companion** —
  the coroutine lowering is byte-identical.
- `python3 fire.py --dump mojo/backend_gimple/cpp_core.py`: succeeds in 12 s (was 15 s before; the
  8.7 MB `.ci` differs because the compiler's own module now has 30 more functions, which is
  expected and not emitted-program output).
- `python3 test_gimple_generator_runner.py`: 520 passed, 0 failed.
- `python3 test_regress_cpp_oracle_covers_lowering.py`: 13 programs, 2 shapes, 0 failures.
- `python3 test_type_string_ratchet.py`: 0 failures; `cpp_core.py`'s counts are unchanged
  (`== 'int64_t'` 11, `== 'char *'` 12, `== 'MojoList *'` 12), so the W1 packet is untouched.
- `python3 test_gimple_arms_extracted.py` is 6/8, a separate pre-existing red at the time
  (two movable arms, in `_lower_IdentExpr` and `_lower_binary_tail`) that this round did not
  touch; both arms have since been extracted and the test is 8/8.

**Not done:** the builder half of stage 7. No arm returns an `Ex` yet and no `mojo/ir/build.py`
exists. The self-hosted compile of `cpp_core.py` itself is not verified here (light lane, no
bootstrap): the new functions' parameters are inferred from their own bodies, and some differ from
their parent's inferred type (`_cps_expr_stmt`'s `s` is `int64_t` where the parent's is
`MojoList *`), which is the same class of change the stage-6 pass extractions made and accepted.
The integrator's gate covers it.

## Status 2026-11-21 (fourth round): planning round — stage 7's shape step is blocked on a claim decision

Output: a planning guide (no code change). Re-measured with `tools/extract_arm.py --list` on
`mojo/backend_gimple/cpp_core.py` (13,347 lines), and corrected the Next step's counts, which were stale:

| parent | movable lines (tool) | arms | notes |
|---|---|---|---|
| `_cpp_expr` | **3,458** | 10 | the doc said 3,389 / 8. The two missing arms are `UnaryOp` (30, returns) and `BinaryOp` `:=` (39, returns) |
| `_cpp_stmt` | **1,527** | 9 | matches the doc |
| `_cpp_with_stmt` | **90** | 1 | matches |
| `_cpp_for_stmt` | **1,425** | 6 movable of 9 listed | the 363-line `for_target_is_tuple` arm is `NO` (binds `target`), so it is not in the count |
| `_cpp_yield_from` | **126** | 2 | needs `call` annotation |

**The write-set blocker is resolved (2026-11-22).** The W1 `cpp_core` packet landed and its doc is
deleted, so `cpp_core.py` is no longer claimed by it. The decision this lane was waiting on (option 1,
release the STOP line, then run the shape step on `cpp_core.py`) is taken; the plan below is the one to run.

**Plan once released (option 1), so the next round needs no re-investigation:**

- Order: `_cpp_yield_from` (126, 2 arms, smallest, exercises the `call` annotation) -> `_cpp_with_stmt` (90)
  -> `_cpp_stmt` arms, smallest first (`VarDecl` 44, `AugAssignStmt` 32, `ReturnStmt` 42, ...) -> `_cpp_expr`
  arms (`IdentExpr` 91 first) -> `_cpp_for_stmt` (`target`-annotated arms last).
- Each extraction: `python3 tools/extract_arm.py FILE _cpp_expr LINE NEWNAME "DOC" [name:ann ...]` with the
  line from `--list`, then `python3 test_gimple_module_passes.py`-style pin for `cpp_core.py` if one exists
  (it does not yet: add `test_gimple_cpp_core_arms.py` pinning the arm count, as the module-gen pin does).
- Proof per extraction: `python3 tools/c_oracle.py check --base <prev commit> -j 4` — the `tools/cpp_corpus`
  half is the one that sees a coroutine lowering change. Quick test only in the light lane; the full corpus run
  is the integrator's.
- Tests that prove the shape step: the AST-identity check inside `extract_arm.py` (it refuses on mismatch), and
  the oracle reporting 0 changed programs in both corpora.

**Not done:** no `cpp_core.py` edit, no `mojo/ir` builder, no emitted text changed. This round changes only this doc.

## Status 2026-11-21 (third round): the stage-7 oracle now hashes the C++ printer

The doc's own Next step said `c_oracle.py check` "reporting identical C for all 285
`tools/pydiff_corpus` programs" was evidence a coroutine-lowering change was safe, because "the corpus
includes the C++ companion output, so a coroutine-lowering change is hashed". **That was false, and it
is the defect this round fixes** — a stage-7 round following it would have landed a `cpp_core.py` change
believing it had been verified.

Measured:

- `tools/pydiff_corpus` holds 285 programs and **0** of them produce a non-empty companion: none is a
  coroutine program, and the default coroutine backend is the A3 stack-switch lowering
  (`mojo.middle.coro.enabled()` is False only for `MOJO_CORO=cpp`), so `compile_to_gimple_with_cpp`
  returns `cpp == ''` for every one.
- The old `c_oracle.py` therefore compared `md5(c + '\0' + '')` per program — a hash with no slot the
  companion could ever occupy.
- Proof by a real lowering change: renaming the generator base symbol in `cpp_async.py` (`_mojogen_` ->
  `_mojogen_probe_`) left the old oracle printing "all 285 programs generate identical C", exit 0.

Landed (this commit), all outside `cpp_core.py` so the W1 write set above is untouched:

- `tools/cpp_corpus/` — 13 coroutine programs, `generators/` (while+`co_yield`, `for range`, `yield from`,
  `try`/`except`/`raise`, `with`, lambda+call+interpolated string, float/bool/comparison chain/subscript,
  a generator METHOD on a struct, tuple target + value-carrying `return`, a captured closure) and `async/`
  (`await` chain, async generator + `async for`, `try`/`except` in an async function). Every one produces
  a non-empty companion: 8,869-13,895 chars, and the set covers both promise shapes (`co_yield` and
  `co_await`).
- `tools/c_oracle.py` hashes and compares a SECOND corpus with the backend pinned: `hash_tree(..., cpp=True)`
  runs its child with `MOJO_CORO=cpp`, an EMPTY companion is an `ERR` (not a hashable no-op, so the corpus
  cannot silently stop exercising the lowering), and `base`/`check` compare both corpora (the cache key
  covers both, `--closure` unchanged). The same `_mojogen_probe_` rename now reports **9 of 13** programs
  generating different C++ and exits 1.
- `test_regress_cpp_oracle_covers_lowering.py` pins it: every `tools/cpp_corpus` program is accepted and
  non-empty, both shapes are present, the oracle's per-program hash is neither `md5(C)` nor
  `md5(companion)` alone, and the default backend still emits no companion (the reason a second corpus is
  needed). It fails against the pre-fix oracle ("has no CPP_CORPUS"), and fails 12 of 13 if the
  `MOJO_CORO=cpp` selection is dropped from `hash_tree`.

Verified: `python3 tools/c_oracle.py check -j 4` — all 285 programs identical C, all 13 coroutine programs
identical C++ companion; `python3 test_regress_cpp_oracle_covers_lowering.py` — 13 programs, 2 shapes,
0 failures (and 12 failures of 13 with the `MOJO_CORO=cpp` selection removed from `hash_tree`, and a
`FAIL: tools/c_oracle.py has no CPP_CORPUS` against the previous commit's oracle);
`python3 test_gimple_module_passes.py` — 27 passes pinned, 8674/8674 lines, 0 failures.
`python3 test_gimple_arms_extracted.py` is 6/8 on this tree, a SEPARATE pre-existing red at the
time (two movable arms, in `_lower_IdentExpr` and `_lower_binary_tail`) — untouched here, and it
is not registered, so no gate runs it. Both arms have since been extracted and it is 8/8.

NOT done: stage 7 itself. No `cpp_core.py` emission moved onto a builder — `mojo/ir/build.py` (stage 2b)
still does not exist — and nothing in this round changes emitted text (the oracle proves that: both
corpora identical to the previous commit).

## Status 2026-11-21 (second round): stage 6 is finished — 0 movable passes remain

Landed (one commit, `tools/extract_arm.py --phase` only: no moved line was edited by hand):
the remaining 14 movable statements of `gen_module_impl` are now top-level functions that return
nothing, each called once. 447 statement lines -> 14 call sites, so `gen_module_impl` is
9,107 -> **8,674** lines, and
`python3 tools/extract_arm.py --list-phases mojo/backend_gimple/module_gen.py gen_module_impl 25`
prints `0 lines can be moved`. Everything the tool still lists is its own refusal, which is the
accepted end state: a pass that returns a value, that binds a name read later, or that calls a
nested function (29 nested functions here capture a local, and lifting one needs a typed parameter
per captured local).

The new parameter annotations are the C types the parent's locals had in the compiler's own
output (`python3 fire.py --dump mojo/backend_gimple/module_gen.py`): `char *` -> `str`,
`_Bool` -> `bool`, `MojoList *` -> `list`, `MojoSet *` -> `set[str]` (the two are sets of names),
`MojoDict *` -> `dict`, `int64_t` -> no annotation. The one erased-word local passed is `_gg_stmts`
(`int64_t` in the parent, deliberately unannotated), so the self-hosted compiler types it the same
way the parent did; the CPython dump infers `MojoClass *` for it from the body's one field use and
casts at the call site.

Verified:

- `python3 test_gimple_module_passes.py`: 27 passes pinned (13 + 14), `gen_module_impl`
  8,674/8,674 lines, 0 failures. The test also runs `--list-phases` and requires the
  `0 lines can be moved` end state; on the pre-change file it reports 30 failures (14 missing
  signatures, the 9,107-line parent, and 447 movable lines).
- `python3 tools/c_oracle.py check --base 25ce47f3c -j 4`: all 285 `tools/pydiff_corpus`
  programs generate identical C.
- `python3 test_gimple_lint.py`: passed, 0 failures, 13 corpus files, 313,334 statements (it
  compiles `module_gen.py` in single-file `--dump` mode, so the moved code still lowers cleanly).

NOT done: stage 7 (blocked on stage 2b). The self-hosted bootstrap is not verified here (a
light-worker round may not run it); the annotations above are the only way this change can affect it.

## Done when

- Stage 7: `cpp_core.py`'s lowering builds `mojo/ir` instructions instead of C++ text, with
  `python3 tools/c_oracle.py check` reporting identical C for `tools/pydiff_corpus` **and** identical
  C++ companion for `tools/cpp_corpus` (the second is the one that can see the lowering; the first
  cannot).
- The doc is deleted in that commit (with `python3 tools/dangling_doc_refs.py --ratchet`).

**Step 1 of the plan, done (2026-11-22):** `_cps_expr_stmt`'s `printf` and `fflush` lines (the single-scalar
and tagged-word print forms) are built by `_cpp_call_line` (a `call` shape with `tight=True`, printed as an
`expr`). Verified: arms test 30/0; `c_oracle` identical on all 285 C and 13 coroutine programs; closure
stubs unchanged (3 == 3). The multi-argument print lines and the remaining `_cps_expr_stmt` forms (28 sites
before this step, about 20 left) are still text.


## Status 2026-11-22 (continued): the simple statement forms are on the IR

Landed, each verified (`test_gimple_cpp_core_arms.py` 30/0; `c_oracle check --base HEAD`: all 285 C and 13
coroutine C++ programs identical; `compile_stdlib.py` PASSED 592, FAILED 18 = 0 expected / 18 unexpected,
the same module set as before):

- `ecdb1887d`: three `fname(args);` statements in `_cps_expr_stmt` (fnptr and captured-callable calls).
- `ecdb1887d`: five `lhs = rhs;`
  statements (class-attribute store, generator-variable store incl. `*name`, list-iterator setup).
- New IR shape `coyield` in `mojo/ir/instr.py` (`co_yield <expr>;`), used for the three `co_yield`
  statements of `_cps_expr_stmt`; the `abort()` pair and `self->f = self->f op val;` in `_cps_aug_assign`
  now go through `_cpp_call_line` / `_cpp_ir_line` / `_cpp_assign_line`.

Still text (measured 2026-11-22, after the above): `_cpf_named_target` 80 sites, `_cpp_yield_from` 39,
`_cpp_for_stmt` 37, `_cps_assign_stmt` 18 (container forms, `self->f = ...`, `(void)(...)`), `_cpy_handle_local`
13 (needs `for (;;)` and `throw` shapes), `_cpp_container_literal_init` 12, `_cpp_yield_tuple` 14,
`_cpp_for_generator_delegate` 10, `_cpf_call_iterable` 10, `_cpp_with_stmt` 9, `_cpf_*` loop headers
(`for (...) {`, which need a loop-header shape), and the 11 `_cpx_*` expression arms. The plan's remaining
steps are therefore: loop-header and `throw` shapes in `mojo/ir/instr.py`, then the container and
named-target forms, then the expression arms.

## Status 2026-11-22 (later): loops, assigns and the first big extraction

Landed, each verified (arms 30/0; `c_oracle check --base HEAD` identical on 285 C and 13 C++ programs;
`compile_stdlib.py` PASSED 592, FAILED 18 = 0 expected / 18 unexpected, the same module set):

- `58ed00ebd`: `_cpf_generator_handle` (while/assign/end) and the `_cpw_async_with` and tuple-unpack
  statements in `_cps_assign_stmt`.
- `79d5adde9`: a `for` header shape; `_cpf_list_iter_cursor` prints through it.
- `8f2bcf9bf`: a `block` shape; `_cpy_handle_local` prints through block/if/for/assign/expr (its one-line
  `if (!step) break;` and multi-line `throw` stay text).
- `dba81700d`: a `decl` shape and ONE helper `_cpp_counted_list_loop` for the three copies of the counted
  list loop (`_cpf_word_iterable`, `_cpf_param_call`, `_cpf_call_iterable`).
- `a35104a5b`: `tools/extract_arm.py` moved the 582-line expression-iterable arm of `_cpf_named_target`
  into `_cpf_named_target_iter_expr` (pure move, AST-identical). 60 lines of the parent are still movable.

Text sites per printer function now (`awk` over `{indent}`, 2026-11-22 after the above):

    48 _cpf_named_target_iter_expr(gen,
    39 _cpp_yield_from(gen,
    37 _cpp_for_stmt(gen,
    32 _cpf_named_target(gen,
    14 _cpp_yield_tuple(gen,
    12 _cpp_container_literal_init(gen,
    10 _cpp_for_generator_delegate(gen,
    9 _cps_assign_stmt(gen,
    9 _cpp_with_stmt(gen,
    7 _cpp_async_for_stmt(gen,
    6 _cpp_raise_stmt(gen,
    6 _cpf_call_iterable(gen,

Next, in order: (1) the 60 movable lines of `_cpf_named_target`; (2) the `_cpf_named_target_iter_expr`
body (the bulk of the 80 sites) by target kind; (3) `_cpp_yield_from` and `_cpp_for_stmt` (both need the
`for`/`while` shapes already added, plus `ifbody`); (4) the 11 `_cpx_*` expression arms, which need
expression shapes for C++ casts, receivers and runtime-stub calls, not statement shapes.

## Status 2026-11-22 (batches): the extracted arms, yield-from and most for-statement lines

Landed since the previous status (each: arms 30/0 plus the helper checks; `c_oracle check --base HEAD`
identical on 285 C and 13 C++ programs; `compile_stdlib.py` PASSED 592, FAILED 18 = 0 expected / 18
unexpected, the same module set):

- `6a369cab7`, `a35104a5b`: `_cpf_named_target` is `0 lines can be moved` (its arms are
  `_cpf_named_target_call_iter`, `_cpf_named_target_call_iter2`, `_cpf_named_target_iter_expr`).
- `21c39f43c`: the expression-iterable arm prints through the IR (tuple unpack, indexed element loops,
  scalar stub, cached/sorted loops, for/else, plain range-for). Also FIXES a latent crash:
  `_cpp_assign_line` now coerces string operands to `ex_text`. Several earlier call sites passed text, which
  reached `Instr.show()` as a str on paths the corpus does not reach; the generator corpus found it. The
  arm test now pins every IR helper with text operands directly.
- `ac3a1a12a`: the simple lists of `_cpp_yield_from` (dyn-call and word-iterable cursor loops, for over a
  collection, list-get range) print through assign/for/coyield/end.
- `a2d1c304b`: most single-line declarations, loop headers, closers and scalar assigns in `_cpp_for_stmt`.

Text sites per printer function now (`awk` over `{indent}`):

    24 _cpp_yield_from(gen,
    23 _cpf_named_target(gen,
    17 _cpp_for_stmt(gen,
    14 _cpp_yield_tuple(gen,
    12 _cpp_container_literal_init(gen,
    10 _cpp_for_generator_delegate(gen,
    9 _cps_assign_stmt(gen,
    9 _cpp_with_stmt(gen,
    7 _cpp_async_for_stmt(gen,
    6 _cpp_raise_stmt(gen,

Still open: the multi-line concatenated assigns (`MojoList * x = ` split across lines) in `_cpp_for_stmt`
and `_cpp_yield_from`; the sub-generator guard block in `_cpp_yield_from` (`{ ... }` + if/for(;;)/throw);
`_cpp_yield_tuple`, `_cpp_container_literal_init`, `_cpp_for_generator_delegate`, `_cpp_with_stmt`,
`_cps_assign_stmt`; and the 11 `_cpx_*` expression arms, which need expression shapes.

Process note: the oracle does not reach every converted path. Each new helper or shape needs a direct check in
`test_gimple_cpp_core_arms.py` (as the helper text-operand check now does), not only a byte-identical corpus run.

## Status 2026-11-22 (later batches): statement printers mostly on the IR

Landed since the previous status (each: arms 30/0 plus the helper checks; `c_oracle check --base HEAD`
identical on 285 C and 13 C++ programs; `compile_stdlib.py` PASSED 592, FAILED 18 = 0 expected / 18
unexpected, the same module set):

- `82fe1317f`: seven two-line concatenated assigns in `_cpp_for_stmt`/`_cpp_yield_from`; the sub-generator
  guard block in `_cpp_yield_from` (block, if, for(;;), pending-exception throw, closers).
- `f8fb9ceb7`: `_cpp_yield_tuple` (the tuple list builders and `co_yield <tuple>`).
- `5f99a3773`: `_cpp_container_literal_init` (list, dict and set literals).
- `5bbeac708`: `_cpp_for_generator_delegate` (block, while, index assign, closers); a `throw` shape; one
  single-line raise.
- `b0705633e`: `_cpp_with_stmt` (tempdir guard, alias declarations, open-file assign, close calls). Its
  line count was held at the 256-line ratchet by shortening the new calls, not by raising the ratchet.
- `324497245`: `_cpp_async_for_stmt`'s statement list.
- `4522a6fac`: the repeat and range forms of `_cpp_yield_from`.
- `72581a406`: `_cps_assign_stmt`'s simple lines (unpack decls, self-field store, setattr, subscript store, void).
- `1734a775f`: `_cpf_simple_target_call_iterable`.

Total `{indent}` text sites in `cpp_core.py` are now 82 (down from about 260 at the start of this batch
series). Largest remaining, by the awk count over each `def`:

    23 _cpf_named_target(gen,
    10 _cpp_for_stmt(gen,
    6 _cpf_call_iterable(gen,
    5 _cpp_raise_stmt(gen,
    5 _cpf_named_target_call_iter2(gen,
    4 _cpy_unsupported_shape(gen,
    4 _cpp_try_stmt(gen,
    4 _cpf_named_target_call_iter(gen,
    3 _cpp_yield_from(gen,
    2 _cpy_handle_local(gen,

Still open: the remaining 23 in `_cpf_named_target` (its own branches), `_cpp_for_stmt` (10), `_cpf_call_iterable` (6),
`_cpp_raise_stmt`'s multi-line `_MojoCppExc{...}` throws (5), and the multi-line `mojo_vararg_fn_new` assign.
The 11 `_cpx_*` expression arms are a separate job: they return expression text, which needs C++ expression
shapes (casts, receivers, runtime-stub calls) in `mojo/ir/instr.py`, not more statement shapes.
Stage 5c is unchanged: blocked on the pointer-versus-scalar call-site analysis or an owner decision.

## Plan (planning round, 2026-11-22): the expression printers

Statement printers are done as far as the shapes go: `cpp_core.py` has 82 `{indent}` text sites at the last
count, the largest being `_cpp_for_stmt` (10), `_cpf_call_iterable` (6), `_cpp_raise_stmt` (5, multi-line
`_MojoCppExc{...}` throws) and `_cpy_unsupported_shape` (4). What remains is the expression side.

**Measured.** The 11 `_cpx_*` arms are 2,217 (`_cpx_call_expr`), 289 (`_cpx_member_expr`), 250
(`_cpx_binary_op`), 248 (`_cpx_await_expr`), 145 (`_cpx_subscript_expr`), 137 (`_cpx_lambda_expr`), 96
(`_cpx_ident_expr`), 47 (`_cpx_compare_chain`), 44 (`_cpx_walrus`), 35 (`_cpx_unary_op`), 34 (`_cpx_slice_expr`)
lines, about 3,500 in all. `_cpp_expr(gen, e)` dispatches to them and returns `str` from every branch; 235
`gen._cpp_expr(` call sites across `mojo/backend_gimple/` take that `str`.

**Why it is not a statement-style conversion.** `mojo/ir/instr.py`'s `Ex.show()` renders no parentheses for
`un`/`bin`/`cast`/`call`, and the arms wrap their text in `(...)` (`_cpx_unary_op` returns `(!x)`). The arms
also take their operands as text, so an `Ex` built from them would be `ex_text` leaves. The IR gains value only
when operands are `Ex`, which means the dispatcher has to return `Ex`.

**Approach (chosen).** Migrate the dispatcher, not the arms:

1. Add a `paren` kind to `Ex` (`(` + a + `)`) and check `cond`'s spacing against the arms' `?:` text.
2. Add `_cpp_expr_ex(gen, e) -> Ex`, the dispatcher's new body: every branch returns an `Ex`. A branch whose arm
   is not yet migrated returns `ex_text(<the arm's current str>)`.
3. `_cpp_expr(gen, e)` becomes `return _cpp_expr_ex(gen, e).show()`. The 235 callers do not change.
4. Migrate the arms one at a time, smallest first: `_cpx_slice_expr` (34), `_cpx_unary_op` (35), `_cpx_walrus`
   (44), `_cpx_compare_chain` (47), `_cpx_ident_expr` (96), `_cpx_subscript_expr`, `_cpx_lambda_expr`,
   `_cpx_binary_op`, `_cpx_member_expr`, `_cpx_await_expr`, and `_cpx_call_expr` last (2,217 lines; it needs
   `_cpx_call_expr`'s own split with `tools/extract_arm.py` first).

**Proof per step.** (a) `test_gimple_cpp_core_arms.py` pins that the dispatcher returns `Ex` for each migrated
branch and that `_cpp_expr` equals `_cpp_expr_ex(...).show()` for a fixed set of nodes; (b) `c_oracle check
--base HEAD` identical on 285 C and 13 coroutine programs; (c) `compile_stdlib.py` unchanged verdict. The oracle
does not reach every arm, so each arm also gets a direct node-level check in (a), as the helper checks do now.

**Not done in this round.** No code change: this is the plan the next round executes. Step 1 (the `paren` kind and
its test) is the smallest first commit.

**Stage 5c** is unchanged: blocked on the pointer-versus-scalar call-site analysis or an owner decision
(`doc/GIR_WORKERS.md` §6).

## Status 2026-11-22 (expression plan, steps 1-12): ten of eleven expression arms return Ex

The expression plan above is executed through step 12. Commits: `9a5867c05` (step 1, the `paren` shape),
`bf6dfd0bd` (step 2, the dispatcher returns `Ex`; `_cpp_expr` is `gen._cpp_expr_ex(e).show()`; one-line
`gen` delegate in `gimple_codegen.py`), then one commit per arm: `e2e5fb31d` slice (list-step and word-step as
`call`), `9d48f7723` unary (`paren`, `un`, `bin`, `call`), `94d289c60` walrus and compare chain (`paren`,
`bin` with `=`, `bin` with `&&`), `6f58b2c84` identifier (wrap), `f335d3194` subscript (`call`, `index`),
`49dc7971a` binary (`call`, `paren(bin)`), `fda723321` lambda (wrap: C++ lambda text), `64b379e86` member
(`field`, `call`), `72532e250` await (`coawait`), and `eda30cc25`, which extracts the three callee arms of
`_cpx_call_expr` (766, 1,226 and 129 lines) as pure moves.

Every arm migration was checked the same way: the arm test pins each branch through a stub generator with
expected strings taken from HEAD's output for the same stub; a direct comparison against HEAD's function on the
same inputs; `c_oracle check --base HEAD` identical on 285 C and 13 coroutine C++ programs; and the
`compile_stdlib.py` verdict unchanged (PASSED 592, FAILED 18 = 0 expected / 18 unexpected).

**Still open (the last expression arm).** `_cpx_call_expr` returns text, and its three extracted children
(`_cpx_call_member`, `_cpx_call_ident`, `_cpx_call_callexpr`) return text: 2,121 lines, the bulk of the
expression printer. The arm test keeps `_cpx_call_expr` on `EXPR_ARMS_STILL_TEXT`. Porting it is the next
round: the children first, each by its own return shapes (most are `call`, with a few `field`/`index`/`paren`
and lambda text leaves), smallest (`_cpx_call_callexpr`, 129) first, then the two large ones after another
`tools/extract_arm.py` pass on them. The same per-branch comparison against HEAD applies.

**Known gaps from these steps.** (1) The floormod and div branches of `_cpx_binary_op` are not reached by any
stub input; their call text is pinned on the helper, not through the arm. (2) `test_selfhost.py` fails
(2 passed, 1 failed) with 73 GCC errors, identical on HEAD (checked in a detached worktree; error sets equal
after stripping the path). It predates this work and is not fixed here; it is the owner's gate. (3) The
oracle reaches most arms but not every branch, which is why each migration carries a direct check.

## Status 2026-11-22 (step 13): the last expression printers

`0843cb5fa` ports `_cpx_call_callexpr` (129 lines, four returns) to `call` shapes; `_cpp_call_ex` now accepts
`Ex` arguments. Its parent `_cpx_call_expr` takes the child's text with `.show()` until it is ported.

**What is left in the expression printers:** `_cpx_call_member` (771 lines, 64 returns), `_cpx_call_ident`
(1,231 lines, 58 returns), and the parent `_cpx_call_expr` (which only dispatches to the three children now).
`EXPR_ARMS_STILL_TEXT` in `test_gimple_cpp_core_arms.py` names them.

**Plan for the next round.** Do not port the 122 returns as one batch. Classify each return first, with a
script that reads the AST and prints: callee name and whether the return is a plain f-string call (`call`
shape), a `field`/`index` access, a `(a op b)` (`paren(bin)`), or a multi-line helper (text leaf). Port the
call-shaped returns with the exact-count rewrites used for the subscript and binary arms; leave the multi-line
helpers as `ex_text` leaves and say so in the commit. Then port the parent, which dispatches to the children
through `.show()`, and remove the `.show()`. Each batch keeps the same proof: a stub or `GimpleGen`-based
comparison against HEAD for the branches it reaches, the arm test, `c_oracle check --base HEAD`, and the
`compile_stdlib.py` verdict.

**Known from this round.** The `(c_ret)(call)` and double-return branches of the callee arm are not reached by
any input built here; they share the call builder with the reached branch, so they are verified by reading.

**Classification of `_cpx_call_member` (64 returns), measured with an AST pass over the arm (2026-11-22):**
17 call f-strings (`NAME(args)` with one level of call, e.g. `mojo_list_pop_at(...)`, `int_exists(0, ...)`),
25 paren/cast f-strings (`(mojo_list_append_int(...), 0)`, `(char *)NAME(...)`, `(NAME(...) != 0)`),
9 other f-strings (`{_sym}(self, ...)`, `{obj}.{member}(...)`, the `std::` calls), 2 binops (a list
expression and a lambda, text leaves), 1 conditional expression, 3 constants, 1 subscript, and 4 returns that
call a text-returning helper (`_cpp_as`, `_cpp_emit_generator_start_expr`), which are text leaves until the
helper returns Ex. A naive "already Ex" match on helper names is wrong for these four; check the helper's return
type before counting it as Ex.

Porting order for the next round: the 17 call f-strings first (`call` shape, with the argument text as
leaves where the argument is itself a helper call), then the 25 paren/cast forms (`paren(call)` or
`paren(bin)`), then the 9 others, with the 4 helper-call returns last, after the helpers are checked.

## Status 2026-11-23 (step 13, continued): seven member-call returns are `call` shapes

`fc555d283` ports seven plain `NAME(args)` returns of `_cpx_call_member` (the `staticmethod`,
`self`, `cls`, module-object and class-qualified forms, the receiver-prefixed form, and
`_dict_fn(...)`) from f-strings to `_cpp_call_ex`, with the argument order unchanged.

The 17/25/9/4 counts in the step-13 classification are out of date: master had already ported
most of the non-call returns, so the remaining `_cpx_call_member` returns are re-counted from
the arm itself, not from that table.

Verified: `c_oracle check --base HEAD -j 4` gives identical C on all 285 pydiff programs and
identical C++ companions on all 13 coroutine programs; `test_gimple_cpp_core_arms.py` pins 30
arms with 0 failures; `compile_stdlib.py` gives `FAILED: 0 (0 expected, 0 unexpected)`, no skips.

Still open: the remaining `_cpx_call_member` returns (multi-line helpers, paren/cast forms,
the helper-call returns), `_cpx_call_ident` (1,231 lines), and the parent `_cpx_call_expr`'s
`.show()` dispatch.

## Status 2026-11-23 (step 14): the call dispatch returns `Ex`; 63 returns are still text leaves

`_cpx_call_expr` and `_cpx_call_ident` now have the contract `-> Ex`. Their `.show()` calls at the
member and callexpr boundaries are gone, and the `_cpp_expr` caller no longer wraps the result in
`ex_text`. Every return in those two functions goes through `_as_ex(...)`, which passes an `Ex`
through and wraps text in an `ex_text` leaf. That is a transitional adapter, not a port: the 63
wrapped returns still spell C++ text, and `_cpx_call_ident` (1,231 lines) is still a text arm
underneath. `EXPR_ARMS_STILL_TEXT` in `test_gimple_cpp_core_arms.py` is now empty.

Still open: the text returns of `_cpx_call_member` (about 30 f-string sites), the text returns
inside `_cpx_call_ident` (its calls to `_cpp_emit_generator_start_expr`, the comprehension
helpers and the `_cpp_as` casts), the `(char *)` cast forms (a `cast` needs a type object
for `char *`), and the comma forms `(X(...), 0)`, which need a comma shape the IR does not have.

Verified: `c_oracle check --base HEAD -j 4` gives identical C on all 285 pydiff programs and
identical C++ companions on all 13 coroutine programs; `test_gimple_cpp_core_arms.py` pins 30
arms with 0 failures; `compile_stdlib.py` gives `FAILED: 0 (0 expected, 0 unexpected)`, no skips.

## Status 2026-11-23 (step 15): 29 of the member arm's 30 text returns are Ex shapes

`_cpx_call_member` now builds 29 of its 30 f-string returns as Ex trees, not text leaves:

- 14 comma forms `(NAME(args), 0)` are `paren(comma(call, 0))`. The new `comma` operand kind
  renders `a, b`, and `_cpp_comma_ex` builds it.
- 7 cast-of-call forms `(char *)NAME(args)` are a `cast` to `char *` (`_cpp_cast_ex`) over a call.
- 3 parenthesized calls and comparisons (`(NAME(args) != 0)`) are `paren` over `bin`.
- 5 plain calls with text arguments (`int_relpath`, `std::abs(...) < 1e-9`, `int_write`,
  `std::<member>(...)`, `<obj>.<member>(args)`) are `call` shapes.

Still text: the `mojo_dict_get_int` return with a runtime cast type (`({_dict_val_ct})...`). Its
cast type is a C spelling that `type_named` has not been checked against, so it stays a text leaf
for now; the check is to render each `_dict_val_ct` value the arm can produce and compare.

Every shape was checked to render the exact text of the f-string it replaced (seven representative
cases, all identical). Verified: `c_oracle check --base HEAD -j 4` gives identical C on all 285
pydiff programs and identical C++ companions on all 13 coroutine programs; `test_gimple_cpp_core_arms.py`
pins 30 arms with 0 failures; `compile_stdlib.py` gives `FAILED: 0 (0 expected, 0 unexpected)`, no skips.

Still open: the `_dict_val_ct` return above, then `_cpx_call_ident`'s 1,231 lines of text, which
include calls to `_cpp_emit_generator_start_expr`, the comprehension builders and `_cpp_as`.

## Status 2026-11-23 (step 16): 32 of `_cpx_call_ident`'s text returns are call shapes

`_cpx_call_ident` now builds 32 of its returns as `call`, `cast`, `paren` or `cast`-over-`paren` Ex
trees instead of text: the `mojo_*_len` and `mojo_str*` / `mojo_repr_*` / `mojo_make_*` runtime calls,
the `mojo_hasattr` / `mojo_getattr_*` / `mojo_range*` calls, the `os`-style and generator-helper calls
built from `fname`, `cpp_fname`, `_sym`, `_nhs[fname]` and `@@CSYM:...@@` (their argument lists are
passed as lists), and the `((int64_t)(x))` / `((double)(x))` / `((char *)(x))` parenthesized casts.
Each shape renders the exact text of the f-string it replaced.

Still text (about 26 returns): the C++ lambda bodies (`[&]() {...}()`, statement blobs, not calls);
helper calls whose return type is not yet checked (`_cpp_emit_generator_start_expr`,
`_cpp_next_on_generator_expr`, `_cpp_build_container_from_iterable`, `_cpp_rethrow_pending`,
`gen._cpp_expr`); the `mojo_list_slice_word` return (5937), whose trailing `, ` on a one-argument
call differs from `_cpp_call_ex` (the original emits a trailing comma that is not valid C, so it
needs a deliberate decision, not a silent change); the `(int64_t)(void *)malloc(1)` cast chain; and
the bare text leaves (`'0'`, `args[0]`, `'const_cast<char *>("")'`).

Also still open: the `mojo_dict_get_int` return in `_cpx_call_member` (runtime cast type).

Verified: `c_oracle check --base HEAD -j 4` gives identical C on all 285 pydiff programs and
identical C++ companions on all 13 coroutine programs; `test_gimple_cpp_core_arms.py` pins 30 arms
with 0 failures; `compile_stdlib.py` gives 610 passed, `FAILED: 0 (0 expected, 0 unexpected)`, no skips.

## Status 2026-11-23 (step 17): `mojo_list_slice_word` is a call shape; what is left is lambda bodies

The 6-argument `mojo_list_slice_word` return of `_cpx_call_ident` is now a `call` shape. Its
trailing-comma concern from step 16 does not apply: the arm is guarded by `len(args) == 6`, so
`args[1:]` always has five elements.

What remains as text returns in the call arms, and why each is a leaf rather than a missed port:

- C++ lambda bodies (`[&]() -> T { ... }()`): `_cpx_call_ident`'s `mojo_list_get_*`, slice,
  comprehension, `_W` word-container, and `malloc` returns, plus `_cpp_next_on_generator_expr` and
  `_cpp_build_container_from_iterable`. Their bodies are statements, not expressions, so they need a
  lambda shape with a statement body, which is a design step, not a call port.
- `_cpp_emit_generator_start_expr` and `_cpp_rethrow_pending`: they return a call or a lambda as text.
  Converting them means changing their return type and every call site, which is its own step.
- Bare text leaves (`'0'`, `args[0]`, `'const_cast<char *>("")'`, `'1'`): already single-token
  `ex_text` values, not calls.
- `mojo_dict_get_int` in `_cpx_call_member`: runtime cast type, not yet checked against `type_named`.

Verified: `c_oracle check --base HEAD -j 4` gives identical C on all 285 pydiff programs and
identical C++ companions on all 13 coroutine programs; `test_gimple_cpp_core_arms.py` pins 30 arms
with 0 failures.

## Status 2026-11-23 (step 18): the lambda shape exists; two lambda helpers are on it

`Ex('lambda')` is the IR shape for a call-once C++ lambda: `text` is its return C type, `body` is a
list of `Instr` (`decl`, `if`, `expr`, `throw`, `end`, `return`), and it renders as
`[&]() -> T { stmt stmt }()`. `cpp_core.py` has `_cpp_instr` to build a body statement.

Two helpers now build their lambda on it, each pinned byte-for-byte in
`test_gimple_cpp_core_arms.py` to the text it printed before:

- `_cpp_next_on_generator_expr` (both branches: a tracked handle, and a direct construction through a
  `decl`), with the shared body in `_cpp_next_lambda_ex`.
- `_cpp_rethrow_pending` (the runtime-raiser rethrow). It now returns an `Ex`; its one text consumer,
  `_cpp_expr_ex`'s none-guard table, takes the stored `Ex` directly.

Still text: the lambdas in `_cpx_call_ident` (`mojo_list_get_*`, slice, comprehension, `_W` word
container, `malloc`, and the `mojo_getattr`/`mojo_list` bodies), `_cpp_build_container_from_iterable`'s
lambda, and `_cpp_emit_generator_start_expr`'s start expression. Each is a statement body that the
shape can now hold; porting each is the next step, one lambda at a time, with the same byte-for-byte pin.

Verified: `c_oracle check --base HEAD -j 4` gives identical C on all 285 pydiff programs and identical
C++ companions on all 13 coroutine programs; `test_gimple_cpp_core_arms.py` pins 30 arms and the
lambda texts with 0 failures.

## Status 2026-11-23 (step 19): `_cpp_emit_generator_start_expr` returns Ex; its `base_start(...)` is a call shape

The generator-construction expression is built as a `call` Ex (`_cpp_call_ex(f"{base}_start", cargs)`),
and the keyword-argument path returns its text through `_as_ex`. Its four callers: the member arm and
the identifier arm take the `Ex` directly. The two statement printers (the `next()` handle and the
generator-assignment start) still need C text, so they take `.show()` at the boundary; those printers
are the next text consumers to port.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine
programs; `test_gimple_cpp_core_arms.py` 30 arms, 0 failures.

## Status 2026-11-23 (step 20): four more lambdas are on the lambda shape

`Ex('lambda')` now renders an empty return type as `[&]() { ... }()`, and an empty statement in a
body takes no separator (so an empty opaque block does not double a space). Four lambdas are
ported, each on structure rather than text:

- the `isi` cache lambda (`const int64_t v = ...; return (a || b);`, no return type), in `_cpx_call_ident`;
- the list-iterator `next` lambda (an `if` with its miss statement, then `return get(list, cur++)`);
- the min/max accumulator lambda (a run of opaque blocks, then `return`);
- the `_cpp_build_container_from_iterable` lambda (a declaration, the loop body, `return acc`).

`_cpp_build_container_from_iterable` returns an `Ex` now; its `ex_text` caller in the comprehension
arm takes it directly. The arm test pins the empty-return-type and empty-statement rules.

Still text lambdas in `_cpx_call_ident`: the `_W` word-container lambda, the list-copy lambda with its
callable body, the struct constructor (`calloc` plus `attr_inits`), and the pack call with
`_pack_stmts`. Each needs its own port, the last three with a byte pin.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine
programs; `test_gimple_cpp_core_arms.py` 30 arms, 0 failures, with the new rules pinned.

## Status 2026-11-23 (step 21): the identifier arm's lambdas are on the lambda shape

Four more `_cpx_call_ident` lambdas are `Ex('lambda')` now, each with an exact body:

- the `tuple()`/`list()` copy, with its `_W` word container: the struct definition as one opaque
  statement, the `mojo_list_copy` declaration, the optional tuple marker, and the `_W{...}` return;
- the `sorted()` copy over a list: its declarations, the element-copy loop and the sort (the loops are
  brace-less, so they stay opaque statements), the `mojo_list_append_int` loop, and the return;
- the struct constructor: the `calloc` declaration, then the `__mojo_type_id` stamp and the attribute
  initialisers as one opaque statement (they have no separator between them in the output), then `return _t`;
- the `*args`/`**kwargs` call: the pack statements, then `return (int64_t)(intptr_t)(f(args))` built as casts
  and a call.

`_cpp_cast_ex` now keeps a spelling the type table does not carry exactly (`intptr_t` is `int64_t`
there, which would have printed the wrong cast in the `*args` lambda). Pinned in the arm test.

Remaining text lambdas on the call paths: `_cpx_call_member`'s `str.format_words` lambda, and the
comparator lambda inside the `sorted()` lambda (a leaf: the comparator is a lambda with its own
parameters). Helpers outside the arms that still print lambdas: `_cpp_dyn_call_expr`,
`_cpp_generator_start_kwargs_expr`, `_cpp_boxed_list_literal_expr`, `_cpp_list_literal_arg_expr`.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine
programs; `test_gimple_cpp_core_arms.py` 30 arms, 0 failures.

## Status 2026-11-23 (step 22): three more call-path lambdas are on the lambda shape

- `_cpx_call_member`'s `str.format_words` lambda: a declaration, the format-argument statements (trimmed
  of their trailing space, so the join reproduces the old text), and the `mojo_str_format_words` call.
- `_cpp_dyn_call_expr` (a call through a callable-valued parameter): the `_W` word container as one
  opaque statement, two declarations, the packed-argument statements, and the `_W{mojo_dyn_call(...)}`
  return.
- `_cpp_generator_start_kwargs_expr` (a generator call with `**kwargs`): one statement run, then the
  `{base}_start(...)` call.

`_cpp_dyn_call_expr` now returns an `Ex`. Its five callers in the statement printers print text, so they
call the new `_cpp_dyn_call_text` (the one named text boundary for that helper). `_cpp_generator_start_kwargs_expr`'s
only caller already takes an `Ex` through `_as_ex`.

Not measured: whether the corpus reaches the `format_words`, dynamic-call and `**kwargs` generator paths.
The C oracle is identical, but identical output on these three is verified only where the corpus hits them.

Remaining text lambdas on the call paths: `_cpp_boxed_list_literal_expr` and `_cpp_list_literal_arg_expr`
(their parts carry leading spaces, and an empty literal would print a double space that the join drops; needs
a check of whether an empty literal reaches them), `_cpp_try_kwargs_forward_call`, and the comparator leaf
inside the `sorted()` lambda.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine programs;
`test_gimple_cpp_core_arms.py` 30 arms, 0 failures.

## Status 2026-11-23 (step 23): the list-literal lambdas are on the lambda shape

- `_cpp_boxed_list_literal_expr` (a list or tuple literal whose elements are nested containers or struct
  pointers): a declaration, the element statements (joined and trimmed, so the output is unchanged),
  and `return`. It returns an `Ex`. Its nested recursion and its three text consumers (the assignment
  printer, `_cpx_call_member`'s append path, and the nested element) take `.show()`.
- `_cpp_list_literal_arg_expr` (a list literal at a call-argument position): the empty literal is an `Ex`
  leaf; the nested case delegates to the boxed helper; the typed case is a lambda (declaration, the typed
  `append` statements, `return`). It returns an `Ex`. `_cpp_call_arg_expr` (which feeds five text call-slot
  sites) and the `_a0` site take `.show()` at that boundary; the two `ex_text` wrappers in the member and
  identifier arms take the `Ex` directly.

Empty literals are safe: the boxed helper always starts with its declaration, and the empty arg literal is
`mojo_list_new ()` with no lambda.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine programs.
Coverage: the corpus has many list literals in assignments and nested tuples (the boxed path), but none that I
found at a call-argument position, so the typed argument lambda is checked by the oracle only where it runs.

Remaining text lambdas on the call paths: `_cpp_try_kwargs_forward_call`, and the comparator leaf inside the
`sorted()` lambda.

`test_gimple_cpp_core_arms.py` 30 arms, 0 failures.

## Status 2026-11-23 (step 24): the call arms have no text lambdas left

- `_cpp_try_kwargs_forward_call` (a `**kwargs` forward through a runtime dict lookup): each statement line is an
  opaque statement, and the `return` is a call shape. It returns an `Ex`; its caller already takes it through `_as_ex`.
- The `sorted()` comparator is a `closure` (a lambda VALUE, not called in place), with a new IR kind
  `Ex('closure')`: `name` is the parameter list, `text` the optional return type, `body` the statements. It renders
  `[&](params) { stmt }`. The `stable_sort` call that takes it is a call shape. Pinned in the arm test.

What the call arms do now: every lambda they print is an `Ex('lambda')` or `Ex('closure')`. The text lambdas that
remain in `cpp_core.py` are in expression printers outside the call arms (`_cpx_member_expr`, `_cpx_lambda_expr`,
`_cpx_binary_op`), in statement printers (`_cps_assign_stmt`, `_cpf_simple_target_call_iterable`, `_cpp_try_stmt`), and in
`_cpp_assign_cast_type`, `_cpp_raise_tuple_msg_expr`. Those are the next lambda work, not call-arm work.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine programs;
`test_gimple_cpp_core_arms.py` 30 arms, 0 failures, with the closure and the stable_sort text pinned.

## Status 2026-11-23 (step 25): six expression-printer lambdas are on the lambda shape

`_cpx_member_expr` (two callable-member thunks: a `std::function` cast of a `[&]() -> int64_t { return f(...); }`
closure, now `_cpp_int64_thunk`), and `_cpx_binary_op` (the `and`/`or` word-holding struct (`_cpp_struct_word_lambda`),
the `and`/`or` word left operand, the string `or` with a word left operand, and the `in` over a set of words).

`_cpp_int64_thunk` is a `closure`, not a `lambda`: it is cast to a callable type and not invoked in place, so it has
no trailing `()`. The arm test caught this (it had been a `lambda`) and pins it now.

Coverage: the C oracle is identical, but the corpus does NOT reach these six sites (the oracle stayed identical even
when the thunk briefly rendered a wrong trailing `()`). Their helpers are pinned byte for byte; the six sites are
verified by transcription against their old f-strings, not by the corpus. A targeted corpus program for each
(callable member, `and`/`or` on a word, `in` over a set of words) would make that check real.

Remaining text lambdas: `_cpx_lambda_expr` (3), `_cps_assign_stmt`, `_cpf_simple_target_call_iterable`,
`_cpp_try_stmt` (2), `_cpp_raise_tuple_msg_expr`, `_cpp_assign_cast_type`.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine programs;
`test_gimple_cpp_core_arms.py` 30 arms, 0 failures, with the thunk, struct-word and closure texts pinned.

## Status 2026-11-23 (step 26): the expression and raise lambdas are on the lambda shape

- `_cpx_lambda_expr`'s three lambda values (a one-parameter boxed closure cast to the one-argument callable
  type, a parameter-list closure cast to a lambda type, and the no-parameter callable closure) are `closure`s
  under a paren and a cast, as the thunks were.
- `_cpp_raise_tuple_msg_expr` (the `char *` message of a tuple raise): a call-once lambda over its statements,
  parenthesized. Its two callers take `.show()` at the message boundary.
- The dynamic word-call lambda is now one helper, `_cpp_dyn_word_lambda`, used by `_cpp_dyn_call_expr` and by the
  call-iterable site in `_cpf_simple_target_call_iterable` (which had its own copy of the same text). The arm test
  pins it byte for byte.

Still a text lambda: `_cpp_try_stmt`'s scope-exit guard (`_MojoScopeExit fin([&]() { ... });`). It is a multi-line
statement block printed as text lines, so it belongs to the try printer's block shape, not to the expression lambda
shape. `_cpp_assign_cast_type` and `_cps_assign_stmt` match `[&]` only in a docstring and a comment; they print no lambda.

Verified: `c_oracle check --base HEAD -j 4` identical on all 285 pydiff programs and all 13 coroutine programs.
As in step 25, the corpus does not confirm the `_cpx_lambda_expr` sites or the raise-tuple site; they are checked by
transcription and the helper pin. `test_gimple_cpp_core_arms.py` 30 arms, 0 failures.
