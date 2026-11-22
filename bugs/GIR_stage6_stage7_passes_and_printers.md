# GIR stages 6 and 7: stage 6 (passes of `gen_module_impl`) is finished; stage 7 is open

Plan source: `doc/GIR.md`, Stage 6 (counted loops, arms of the giant functions, passes of
`gen_module_impl`) and Stage 7 (the other printers, including the C++ coroutine lowering in
`cpp_core.py`).

## Still open

- Stage 7 itself: `cpp_core.py` is the C++ coroutine printer. Its lowering still spells types and
  statements as strings; the plan moves it onto the same builder as stage 2b. **Blocked**: it starts
  after stages 2b and 3c, and `mojo/ir/build.py` (stage 2b) does not exist in the tree yet.
- Its VERIFICATION is no longer blocked: `tools/c_oracle.py` now hashes the companion `.cpp` (see the
  Status below), so a printer change can be proven byte-identical before it is made.
- Its WRITE SET may be: `bugs/GIR_W1_cpp_core.md` still carries the W1 wave's `STOP: claimed` line for
  `mojo/backend_gimple/cpp_core.py`, while `python3 tools/control.py claims` lists no live holder. Release
  one of the two before moving a `cpp_core.py` emission, or the two lanes edit one file.

## Next step

Stage 7, in this order:

1. Land `mojo/ir/build.py` (stage 2b, `bugs/GIR_stage2b_3c_builder_and_instr.md`) — or, if that lane is not
   yours, do the shape step first: `tools/extract_arm.py --list mojo/backend_gimple/cpp_core.py _cpp_expr`
   reports **3,458 movable lines in 10 arms** (`IdentExpr` 91, `MemberExpr` 284, `LambdaExpr` 132,
   `UnaryOp` 30, `BinaryOp` 245 and 39, `CompareChain` 42, `CallExpr` 2,212, `SubscriptExpr` 140, `AwaitExpr` 243 —
   every one `returns`, `extra inputs: none`; corrected 2026-11-21, see the fourth-round Status), `_cpp_stmt` **1,527** in 9 arms, `_cpp_with_stmt` 90 in 1; the `_cpp_for_stmt`
   (1,425 in 6) and `_cpp_yield_from` (126 in 2) arms need `target`/`call` annotations. An extracted arm is exactly the
   unit that later returns an `Ex` instead of a string, and each extraction is AST-identity-checked by the tool.
2. Then move one extracted arm at a time onto the builder, with
   `python3 tools/c_oracle.py check --base <the commit before> -j 4` reporting identical C **and** identical
   C++ companion for all 285 `tools/pydiff_corpus` programs and all 13 `tools/cpp_corpus` programs.

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

**The blocker is the write set, not the tool.** `bugs/GIR_W1_cpp_core.md` still carries a live
`STOP: claimed by the Claude W1 wave` line for `cpp_core.py`, and `doc/GIR_WORKERS.md` (W1, stage-4 tail)
assigns the same file (39 C-type string-test sites). `python3 tools/control.py claims` lists no live holder,
so that line looks stale, but only the orchestrator may remove it. Moving any `cpp_core.py` arm now would put
two lanes in one file. **Decision needed from the controller:**

1. Release the W1 `cpp_core` STOP line (orchestrator), then this lane runs the shape step on `cpp_core.py`
   exactly as Next step 1 says; or
2. Keep W1, and this lane takes the stage-2b route instead (`bugs/GIR_stage2b_3c_builder_and_instr.md`), which
   is another lane's claim and is not in this worker's claim set. `mojo/ir/` today holds `instr.py`, `reader.py`,
   `types.py`, `verify.py` but **no `build.py`**.

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
`python3 test_gimple_arms_extracted.py` is 6/8 on this tree, which is the SEPARATE pre-existing red
`bugs/GIR_arms_extracted_pin_has_two_movable_arms.md` records (`_lower_IdentExpr` 25 lines,
`_lower_binary_tail` 27) — untouched here, and it is not registered, so no gate runs it.

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
