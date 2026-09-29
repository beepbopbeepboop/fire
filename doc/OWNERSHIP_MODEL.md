# Ownership, Borrowing, and Lifetimes — full design

Supersedes the previous version of this file (a short phase-1 audit note
from an earlier "stage2/mojo" era of this project, dated before self-
hosting/compiled-output existed at all — its "Current Bug: Invalid C Code
Generation" section is now FIXED and stale; see "Current state" below for
what's actually true today, re-verified 2026-09-15). This version is the
full target design: real `borrowed`/`inout`/`owned` semantics, real `^`
move tracking, a real borrow checker, and ASAP destruction — the complete
model real Mojo uses to get Rust-class performance without a GC, not just
enough syntax to parse it.

Written 2026-09-15 while investigating
`bugs/CODEGEN_container_no_deallocation_unbounded_growth.md` and
`bugs/CODEGEN_container_free_registry_dangling_entries.md` — those two
bugs' root fix (deciding exactly when a compiled program may free a
container) is a strict subset of what a real ownership system gives for
free. This doc is the long-term, correct answer; those two bug docs stay
as the pragmatic short-term fix and get explicitly superseded in Phase 3
below.

## TODO — live tracking checklist

Kept at the top and updated in place as items land (checked, with a one-
line note) or split into sub-items — this is the actual work queue, not a
historical log; see the phase sections below for full context on each.

Current priority order (2026-09-15, updated once more): **1, 2, and 3 are
ALL now landed/resolved** — 1 (function-scope Phase 3 destruction) and 3
(exception-unwinding fix, incl. the try/except-eligibility widening) are
real code landed and gate-clean; 2 (async/coroutine ownership) turned out
to already be covered by existing Layer 1 stack-switch infrastructure
once 1 and 3 landed, needing no coroutine-specific code at all. Next
open work is the "not yet scheduled" list below, plus 1's own
loop-body-scoped-destruction follow-up.

**Two real, serious bugs found and fixed 2026-09-15, later still, while
investigating Phase 6 (directed to start next, ahead of Phases 4-5 per
explicit instruction) — both were live in the item-1/item-3 code above
from the moment it landed, only surfaced once a repro happened to hit the
exact shape:**
1. **Stale `_owned_free_candidates`/`_owned_free_pushed` leaking into
   struct methods and toplevel code — a confirmed use-after-free
   (reproduced as a `MallocScribble` segfault).** `gimple_gen_funcs.py`'s
   `_gen_struct_method` and `_gen_toplevel` share `gen.gen_stmt`/
   `_gen_stmt_ReturnStmt` (and therefore `emit_return_frees`) with
   ordinary functions, but neither ever called `begin_function` to reset
   the owned-free state — only `gen_func` does. A struct method (or
   toplevel code) whose own local happened to share a bare NAME with an
   unrelated free function's real Phase-3 candidate got that stale
   candidate's `mojo_*_free` silently spliced into its own return,
   freeing a value that may have just escaped (e.g. `self.field =
   local_with_same_name`). Fixed: a new `reset_no_candidates(gen)` public
   entry point in `gimple_gen_infra.py`, called from both sites — Phase 3
   still doesn't support methods (out of scope), but now correctly means
   "zero candidates" instead of "whatever leaked in."
2. **`emit_return_frees` ran BEFORE evaluating the return expression, not
   after — a confirmed use-after-free for any `return <expr using the
   candidate>`** (`return d["x"]`, `return d.get(k)`, `return len(d)`,
   ...). `ownership_destruct.py`'s rule 3 only disqualifies a candidate
   that IS the returned value (`return d`); it correctly does NOT
   disqualify a candidate merely READ from in the return expression
   (`_scan_expr`'s subscript/member safe-receiver carve-outs), but the
   codegen call site freed the candidate before that read ever ran.
   Reproduced as a minimal `d = {}; d["x"] = 1; return d["x"]` returning
   `0` instead of `1` once freed memory happened to get zeroed, and as an
   outright segfault under `MallocScribble`. Every earlier verification
   in this doc that "looked correct" (own_try_test's 640000, the
   generator's 10, etc.) was unknowingly relying on freed-but-not-yet-
   reused memory still reading back correctly — allocator luck, not a
   correct program. Fixed: `_gen_stmt_ReturnStmt` (`gimple_gen_stmts.py`)
   now calls `emit_return_frees` AFTER `gen.lower_expr(node.value)`
   computes the return value, not before.
   Both fixes re-verified against the full gate (test suites, check-
   linkmode, check-selfhost, stdlib dylib rebuild 0 skips,
   `compile_stdlib.py` 664/664, `make bootstrap` 180/180) and against
   every earlier repro in this doc, now re-checked under `MallocScribble`/
   `dangerouslyDisableSandbox` (all pass with exit 0, not just "printed a
   plausible-looking number"). `check-native-dumpfull` re-confirmed as
   the same pre-existing divergence via a proper same-worktree `--no-
   cache` A/B (see that bug doc's newest entry — the naive "compare to a
   number written down earlier" methodology used for the previous three
   confirmations turned out to be unreliable, since the metric is
   sensitive to build/cache state, not just source content).

1. [x] **Wire `ownership_destruct.py`'s analysis into codegen — narrow
   scope first.** LANDED 2026-09-15. Emits real `mojo_*_free` calls for
   eligible function-scoped locals via three public entry points in
   `gimple_gen_infra.py` (`begin_function`/`emit_return_frees`/
   `emit_fallthrough_frees` — the ENTIRE feature's logic lives in that one
   file's "Phase 3 codegen wiring" + "Public entry points" sections;
   `gimple_gen_funcs.py`/`gimple_gen_stmts.py` each make exactly one call
   in, no private details leak out, per this project's engineering
   standard, not just its Mojo semantics).
   - [x] Insertion points found: `gen_func` (gimple_gen_funcs.py, function
     entry + fallthrough) and `_gen_stmt_ReturnStmt` (gimple_gen_stmts.py,
     each return).
   - [x] Eligibility guard: no `try`/`except`, no nested `def`/`lambda`
     ANYWHERE in body, AND — a real gap found and fixed during this same
     pass, not shipped with it — the function itself must not be
     `is_async`/`is_generator` (a coroutine/generator's `return` is
     rewritten by gimple_gen_coro.py into `__mojo_coro_set_return(...)` +
     fall-through, a different lowering than this wiring was built
     against; the original check only walked for a NESTED FunctionDef and
     missed the top-level function carrying these flags itself).
   - [x] Wired, dispatching on `gen.var_types` to the right
     `mojo_{dict,list,set}_free`.
   - [x] Correctness verified directly (not just "didn't crash"): a
     50,000-iteration call loop into a function constructing dict+list+set
     every call, asserting the returned value is exactly right on EVERY
     call — zero wrong results. Confirmed via `--dump`'d `.ci` that the
     three frees land in the right place (right after the last use,
     immediately before `return total;`).
   - [x] Leak fix confirmed via `leaks --atExit`: 3.4MB peak footprint for
     that same 50,000-iteration repro, vs. 267MB for the ORIGINAL
     `leak_check.mojo` repro's 200,000 (unfreed, loop-scoped) iterations —
     real, measured, order-of-magnitude improvement for the case this
     scope covers.
   - [x] `leak_check.mojo` itself re-run and confirmed UNCHANGED at
     267.3MB — correctly still not covered (its containers are
     loop-scoped, out of this v0's documented scope), not silently/
     unsafely "fixed."
   - [x] `test_gimple.py` (308/308) and `test_module_cache.py` (76/76)
     stay green; `test_ownership_check.py` (24/24) and
     `test_ownership_destruct.py` (20/20) stay green.
   - [x] Full CLAUDE.md gimple/codegen quality gate — RUN 2026-09-15.
     `make check-linkmode` (3/3), stdlib dylib build, `compile_stdlib.py`
     (both confirmed green independently), `make check-selfhost` (1/1),
     and `make bootstrap` (180/180 byte-identical across 3 stages) all
     PASS. `make check-native-dumpfull` FAILS — but confirmed, via a
     from-scratch `git worktree` build of unmodified HEAD, to ALREADY
     fail identically before any of this session's changes (see
     `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`'s
     2026-09-15 entry) — a pre-existing, separately-tracked gap unrelated
     to this work, not a regression this wiring introduced.
   - [x] Two real bugs surfaced and fixed BY the gate, exactly as it's
     meant to: (1) `make bootstrap` caught non-deterministic free-call
     ordering — `_owned_free_candidates` is a Python `set`, iterated
     directly; fixed by sorting at the point of emission. (2)
     `check-native-dumpfull` caught a self-host-only crash: a real,
     serious escape-analysis soundness gap in `ownership_destruct.py`
     where a bare identifier read outside a closure was a silent no-op
     by default (only specific shapes like a bare/tuple `return` were
     ever checked) — `return [x]`, `x.field`, or any read not matching
     one of those exact shapes was invisibly missed, so `x` could be
     wrongly freed while still reachable. Rewrote `_scan_expr` so a bare
     identifier read ALWAYS disqualifies by default, with exactly three
     narrow, explicit safe carve-outs (own-method/subscript receiver,
     a resolved `read`-parameter argument, a whitelisted non-retaining
     builtin) — see the module's own updated docstring. Also fixed a
     separate, unrelated self-host gap found via the same investigation:
     `from X import Y as Z` (a renamed single-name import) doesn't
     resolve under this project's self-hosted compile — grep confirmed
     no other file in the codebase used that exact form; switched to a
     plain `from X import Y`. Both fixes re-validated against the full
     20/20 fixture suite and the 664-file real-stdlib sweep (candidate
     count correctly dropped 115→84 after the soundness fix — fewer,
     but now all real, not fewer because something broke).
   - [ ] Extend to loop-body-scoped containers (free at the bottom of
     each iteration) — the case `ownership_destruct.py`'s docstring
     explicitly says v0 doesn't handle, and `leak_check.mojo`'s own
     repro still needs. Not started.
2. [x] **Design (not necessarily implement yet) ownership across async/
   coroutines — INVESTIGATED 2026-09-15, real design update landed, not
   yet actionable.** Read `mojo_coro.h`/`mojo_coro.c`/`mojo_coro_gen.c` in
   full (see the cross-cutting section's "UPDATE" for the complete
   writeup, including a correction of a wrong claim made live during this
   same investigation — an `env`/frame "leak" that turned out not to
   exist, `__mojo_gen_destroy` already frees it).
   - [x] Confirmed: a coroutine/generator body's own locals run on a REAL
     STACK (not a separate heap capture-frame), so their lifetime model is
     NOT fundamentally different from an ordinary function's — narrower
     and better news than assumed going in.
   - [x] Confirmed via source: `MojoGen` only holds call arguments +
     bookkeeping, and IS fully freed today by `__mojo_gen_destroy`; no
     frame-level leak to design around.
   - [x] Narrowed the real blocker to something concrete and actionable:
     `__mojo_coro_destroy`'s cancellation path re-enters the body via a
     synthetic GeneratorExit, driving the SAME broken `mojo_raise`/
     `longjmp` mechanism flagged in the exception-handling section — so
     coroutine cancellation IS an exception-unwind scenario, not an
     independent problem needing its own from-scratch design.
   - [x] Recommendation updated: land the exception-unwinding fix (item 3,
     below) FIRST, then re-assess how much of this gap it already closes
     before designing anything coroutine-specific.
   - [x] **RESOLVED 2026-09-15, later still — this was looking in the
     wrong layer, and the gap it worried about doesn't actually exist
     for the default backend.** `__mojo_coro_set_return` (`mojo_coro.h`)
     is a LOWER runtime-C symbol belonging to the old `gimple_cpp_*.py`
     C++20-coroutine emitter (`MOJO_CORO=cpp`, a differential-oracle
     fallback, not the default per doc/COROUTINE.html §5.5). The DEFAULT
     backend (`gimple_gen_coro.py`'s Layer 1 stack-switch pre-pass,
     unconditionally active unless `MOJO_CORO=cpp` is set — confirmed no
     such env var is set in this project) already rewrites `return e`
     inside an eligible generator/async body, as an AST PRE-PASS run
     BEFORE ordinary codegen (`ast_rewriter.rewrite` → this pre-pass →
     `gen_func`), into `__mojo_gen_set_return(__c, e); return;` — a
     PLAIN, un-flagged `FunctionDef` (`body_fd.is_generator = False;
     body_fd.is_async = False`, set explicitly by `_lower_one_async`/
     `_lower_one_async_gen`/the generator equivalent) containing only
     ordinary statement shapes. This function reaches Phase 3's
     `begin_function`/`_is_free_eligible_function` as an entirely
     ordinary function — no special-casing needed, and (per item 3
     above) a `try`/`except` inside it no longer disqualifies it either.
     Verified empirically, not just argued: a generator with a `d = {}`
     local used only internally (never escaping) correctly gets a real
     `mojo_cleanup_push_dict`/`mojo_dict_free` pair AND the right
     accumulated result over its `yield`s; a generator that instead
     `return`s the container itself gets ZERO push/free for it (the
     `__mojo_gen_set_return(__c, d)` call's unresolved callee correctly
     disqualifies `d` via `_scan_expr`'s CallExpr default — the exact
     same generic protection that already covers an ordinary function's
     unresolved calls, no coroutine-specific carve-out required). Same
     `SETRET_SHIM` call shape is used uniformly for plain `async def`,
     async generators, and generators (`_rewrite_async_stmts`/
     `_rewrite_async_gen_stmts`/the generator rewrite all emit it), so
     this finding covers all three, not just generators. The genuinely
     remaining gap is narrow: a generator/async function that FAILS
     Layer 1's own eligibility check (`_eligible_async_common` and
     friends) falls back to the old C++20 emitter and stays
     `is_generator`/`is_async = True` all the way to codegen — Phase 3
     already, correctly, still excludes those via the existing flag
     check; no regression, no false coverage claimed.
3. [x] **The exception-unwinding fix (option 2, per-frame cleanup-thunk
   registry) — CORE MECHANISM LANDED 2026-09-15.** `runtime/mojo_runtime.
   {c,h}`: a kind-tagged cleanup-thunk stack (`mojo_cleanup_push_dict/
   list/set`, `mojo_cleanup_cancel_n`, `mojo_cleanup_checkpoint_save`),
   wired into `mojo_raise()` so it walks and frees every still-live owned
   local back down to the catching try's recorded checkpoint BEFORE the
   `longjmp` that used to skip past all of them silently. Codegen side
   (`gimple_gen_stmts.py`/`gimple_gen_infra.py`): try/with entry now
   saves the checkpoint right after bumping `_mojo_exc_top`; every
   `VarDecl`/single-target `AssignStmt` pushes a thunk when its target is
   a Phase-3 owned-free candidate; the existing return/fallthrough free
   sites now also cancel the matching thunk count (normal path unchanged
   — still exactly one free — only the exception path gains coverage).
   - [x] This closes the doc's own original motivating example exactly:
     "a function allocates a MojoDict, then something three calls deep
     raises" — the allocating function doesn't need a try of its own,
     only a try somewhere up the call stack, which is the case this
     fixes. Verified, not just argued: a repro (a `{}`-candidate `dict`
     built then unconditionally raised past on every call, 200,000
     iterations from an outer `try/except`) measured **109.5MB peak
     footprint → 8.6MB peak** before/after (built both ways from the
     same source by stashing/restoring the fix, `leaks --atExit`'s
     "0 leaks" summary alone is NOT reliable evidence here — the
     container registries make every leaked container still technically
     "reachable," so peak physical footprint is the real signal, same
     methodology item 1 used).
   - [x] Full gate run clean: `test_gimple.py` 308/308,
     `test_module_cache.py` 76/76, `test_ownership_check.py` 24/24,
     `test_ownership_destruct.py` 20/20, `make check-linkmode` 3/3,
     `make check-selfhost` 1/1, from-scratch stdlib dylib rebuild (0
     skips), `compile_stdlib.py` 664/664 (0 unexpected, up from 663/664),
     `make bootstrap` 180/180 byte-identical across 3 stages.
     `make check-native-dumpfull` FAILS but re-confirmed as the SAME
     pre-existing, already-tracked divergence (see
     `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`'s new
     2026-09-15 "later same day" entry) — same ~20800-21100 first-byte
     window and ~530KB gap as that doc's own same-day baseline, both
     sides up ~28KB from this session's own new code being dumped
     identically on both, not new divergence.
   - [x] **Widened `_is_free_eligible_function` past its own `try`/
     `except` exclusion — LANDED 2026-09-15, later still.** A function
     containing its own `try`/`except` is now Phase-3 eligible too: the
     checkpoint/thunk machinery above already makes a candidate's
     construction and free safe to straddle a `try` in the SAME
     function, the identical reasoning that made it safe across a
     callee's. Verified with a candidate (`d = {}`) whose lifetime spans
     a `try` in its OWN function, caught locally (never propagating) —
     correctness checked by hand-computing the expected accumulated
     result over 200,000 iterations (exact match, not just "didn't
     crash"), and the SAME peak-footprint methodology as above: **112.5MB
     peak → 8.6MB peak** for the identical repro, measured by stashing/
     restoring just this change. Full gate re-run clean end to end
     (`test_gimple.py` 308/308, `test_module_cache.py` 76/76,
     `test_ownership_check.py` 24/24, `test_ownership_destruct.py`
     20/20, `make check-linkmode` 3/3, `make check-selfhost` 1/1,
     stdlib dylib rebuild 0 skips, `compile_stdlib.py` 664/664 0
     unexpected, `make bootstrap` 180/180); `check-native-dumpfull`
     re-confirmed as the SAME pre-existing divergence a third time (see
     that bug doc's newest entry — same first-differing-byte offset
     21086, ~530KB gap unchanged, only a ~3KB shift on each side from
     more functions now emitting push/cancel calls).
   - [ ] Coroutine `return e` insertion point (item 2's own follow-up,
     above) is unaffected by this — still not started.

Not yet scheduled, tracked here so they aren't lost: Python-interop-aware
destructor dispatch, loop-body-scoped destruction (item 1's own
follow-up, above — LANDED 2026-09-28, see doc/MEMORY.html §7.1), and
Phase 4-6 (real calling convention, move-vs-copy, stack allocation).

- [ ] **Beef up the solver to stack-home as much as possible — IN PROGRESS
  (2026-09-28).** Landed (each with fixtures in `test_ownership_destruct.py`
  and a bounded-memory runner test):
  - [x] `for x in local:` / comprehension clauses over a bare local are
    non-escaping reads;
  - [x] the same name declared in sibling loop bodies qualifies in each;
  - [x] real callee information: `ownership_destruct._summarize_params`
    proves a parameter non-retaining from the callee's own body (not from the
    `read` keyword — the compiled path lowers a copy as the same pointer);
    codegen passes `_build_analysis_funcs(stmts)` (plain, uniquely-named,
    non-imported free functions only);
  - [x] non-empty list/dict/set literals are stack-homed
    (`emit_container_new` consumes a storage request; unconsumed -> heap);
  - [x] lists have a 4-slot inline buffer: no `malloc` for short lists, stack
    or heap (doc/MEMORY.html §10).
  Still open: containers nested inside a literal; temporary containers from
  expressions consumed once (comprehension/slice/split results, arguments to
  `extend`); struct instances, closure envs, boxed mutable locals; string
  buffers; struct-method callee tables; storage homing in `__GIMPLE` bodies;
  the container-kind registry's cost (~45% of a short list's remaining time);
  inline slot arrays for dicts/sets. Success = the doc/MEMORY.html §5 table
  all-flat and §10's end-to-end numbers measured against Rust.

## Why this matters, not just "more spec compliance"

Real Mojo's whole pitch is systems-language performance with Python
ergonomics, and the mechanism is specifically: **no GC, no refcounting,
compile-time-tracked deterministic destruction, zero-cost borrows**. Every
one of those is an ownership-model feature. Skipping the ownership model
and just interpreting Mojo source with Python-reference semantics (which
is what this compiler does today) caps this project's ceiling at "a slow
Python with Mojo syntax," never "competitive with Rust" — the two stated
goals (complete model, Rust-competitive performance) are the same project,
not two separate ones. Performance work that doesn't first fix ownership
(e.g. micro-optimizing the current malloc'd-box-per-container runtime)
will keep hitting the same ceiling: you cannot cheaply know when to free
something, or avoid heap-boxing it at all, without knowing who owns it.

## Explicit non-goal: preserving today's shortcuts

The direction here is "what should this compiler actually be," not "what's
the smallest diff on top of what exists." Several things in the current
codebase are cheap workarounds adopted to get *something* working, not
correct designs to build around — this doc should be read as calling for
their removal, not their accommodation:

- **The kind-registries** (`_mojo_list_registry`/`_mojo_dict_registry`/
  `_mojo_set_registry` in `runtime/mojo_runtime.c`) exist only because
  boxed values carry no type tag, so the runtime has to guess a pointer's
  kind by set-membership. A real ownership/type system with static types
  flowing through codegen makes most of these guesses unnecessary at the
  call sites that currently need them — the registries should shrink or
  disappear as Phase 3+ lands real static ownership/type info, not gain
  more permanent members forever. Treat "do we still need this registry
  lookup here" as a live question at every phase, not settled.
- **`__copyinit__`/`__moveinit__` sharing one body** (`mojo_compiler.py:
  1286-1303`) is a stand-in that happened to not crash anything, not a
  considered semantic choice — Phase 5 replacing it with a real move
  isn't "adding a feature," it's fixing something that was always wrong.
- **`param_convs` parsed and ignored** is dead weight pretending to be a
  feature — a program can declare `owned`/`read`/`mut` today and get
  silently identical behavior no matter what it wrote. That's worse than
  not parsing the keywords at all, because it looks correct. Phases 1-4
  closing that gap should be treated as fixing a live correctness bug in
  how this compiler represents Mojo semantics, not a nice-to-have.
- **"Everything pointer-shaped is a mutable, freely-aliasable reference"**
  (today's de facto calling convention) is the root cause the leak bugs
  exist at all, and it's not a deliberate performance choice — it's the
  default you get from doing nothing. Don't preserve it as a fast path
  once Phase 4 lands; replace it.
- Anywhere a future phase finds another one of these — a cast that's
  "correct" only because nothing ever exercises the case it'd get wrong,
  a stub that silently no-ops (`mojo_set_discard` was exactly this until
  today — see `bugs/CODEGEN_container_free_registry_dangling_entries.md`),
  a shared body copy-pasted across two conceptually-different operations —
  fix it in place rather than routing around it. Consistent with this
  project's standing "no triage, fix the bugs" policy (memory:
  `feedback_no_triage_subagents`) and "consolidate duplicates rather than
  maintaining parallel implementations" (CLAUDE.md).

## Current state (re-verified 2026-09-15)

**Parser — mostly correct, further along than the old note said:**
- `mojo_compiler.py:3792-3799` correctly disambiguates postfix `x^`
  (ownership transfer) from binary `a ^ b` (XOR) by lookahead on the next
  token, and produces `UnaryOp(op='^', operand=x)` for the postfix case.
  This was the old doc's "current bug" (`_t1 = ^msg` invalid C) —
  independently already fixed since; not reproducible today.
- `mojo_compiler.py:2620` (`_CONV_KWS`) recognizes the full convention
  keyword set, both old- and new-style Mojo spellings: `read` (=
  `borrowed`), `mut` (= `inout`), `owned`/`var`, plus `out`, `ref`,
  `deinit`. Every parameter's convention is captured into
  `FunctionDef.param_convs: dict[name, str]` (`mojo_compiler.py:463`).
- `@value`-decorated structs get synthesized `__copyinit__`/`__moveinit__`
  (`mojo_compiler.py:1286-1303`) alongside the fieldwise `__init__`.

**Codegen and interpreter — conventions are parsed, then completely
ignored. This is the actual gap, confirmed by direct grep, zero hits:**
```
grep -rn "param_convs" gimple_gen_funcs.py myinterpreter.py   # zero hits
```
- `gimple_gen_exprs.py:661-663`: `^` lowers as a pure pass-through
  (`return ot, ov`) — valid C, but semantically a no-op. The source
  variable is never marked moved, no destructor/free fires, and using it
  again afterward is silently legal (real Mojo: a hard compile error).
- `__copyinit__` and `__moveinit__` are synthesized with byte-for-byte
  identical bodies (`mojo_compiler.py:1296-1303`) — a member-by-member
  copy in both cases. There is no real move (steal the source's
  resources, leave it empty/destructor-free) vs. copy (independent deep
  copy) distinction anywhere in this codebase.
- Calling convention today, verified via `gimple_gen_funcs.py`'s
  `_signature_ctypes`/`_param_ctype`: every pointer-shaped value
  (`MojoDict *`/`MojoList *`/`MojoSet *`/struct pointers) is passed as a
  raw C pointer regardless of its declared `read`/`mut`/`owned`
  convention — i.e. every parameter is a de facto mutable, aliasable,
  ownership-preserving reference today. This happens to work only because
  nothing is ever freed (the leak bugs) — the moment freeing exists, an
  `owned` parameter and a `read` parameter MUST behave differently or a
  `read`-only borrow will get freed out from under its owner.
- No move-tracking, no use-after-move diagnostic, no aliasing/borrow
  checker, no ASAP destruction, no distinct owned-vs-borrowed calling
  convention. All four are unimplemented, not partially implemented.

## The rules to implement (from Mojo's real semantics)

1. **Single owner.** Every value has exactly one binding that owns it at
   any point in the program.
2. **`read` (`borrowed`, the default)** — callee gets a read-only
   reference; caller retains ownership and validity; callee must not
   mutate or free through it.
3. **`mut` (`inout`)** — callee gets a mutable reference; caller retains
   ownership; while borrowed mutably, no other reference (read or mut) to
   the same value may be live — this is the aliasing rule the borrow
   checker enforces.
4. **`owned` (`var` in parameter position)** — callee receives the value
   outright; the caller's binding is no longer valid after the call
   (enforced the same way a `^` transfer is).
5. **`x^` (transfer)** — moves ownership of `x` to the expression's
   result; `x` becomes uninitialized/invalid at that point; using `x`
   afterward is a compile error, not a runtime condition.
6. **ASAP destruction.** A value's destructor (compiler-inserted
   `mojo_*_free`/`__del__`) runs at its LAST USE, not necessarily at
   lexical scope end — real Mojo does liveness-based destruction, not
   naive block-scope destruction. (This project should land block/
   function-scope destruction first — see Phase 3 — and treat true
   ASAP-at-last-use as a later refinement; block-scope destruction is
   still strictly correct, just occasionally later than optimal.)
7. **Borrow checker aliasing rule.** Any number of concurrent `read`
   borrows of a value are fine; a `mut` borrow requires exclusivity (no
   other `read` or `mut` borrow of the same value alive at the same time).
   This is what makes destruction/mutation provably safe without runtime
   checks — the same rule Rust calls "shared xor mutable."
8. **No refcounting by default, anywhere in the core model.** The
   destruction scheme above (compile-time-known single owner, destructor
   call inserted exactly where that owner's lifetime provably ends) is
   the ENTIRE story for ordinary `struct`/container values — no counter,
   no atomic increment/decrement, no runtime tracking of how many
   references exist. Reference counting only belongs in two specific,
   narrow, non-default places in real Mojo, and this project should not
   reach for it anywhere else:
   - **`ArcPointer`** — an explicit, opt-in stdlib wrapper type for the
     genuinely-hard cases single ownership can't express (shared
     ownership, cycles, graphs). It does real atomic increment/decrement
     on copy/drop, and a caller pays for that ONLY by explicitly wrapping
     a value in it. This project doesn't implement `ArcPointer` yet
     (no stdlib type of that name exists in this tree currently) — worth
     adding once Phases 1-5 give single-owner destruction a solid
     foundation to opt out of, but it must stay opt-in; it should never
     become how ordinary `struct`/`List`/`Dict`/`Set` values are managed.
   - **CPython interop (`PythonObject`).** `runtime/mojo_python.c` already
     does real `Py_INCREF`/`Py_DECREF`/`Py_XINCREF`/`Py_XDECREF` against
     CPython's own `ob_refcnt` (confirmed: `grep -n "Py_.*INCREF\|Py_.*DECREF"
     runtime/mojo_python.c`, ~9 call sites today) — this is CORRECT and
     should stay exactly as-is: when this compiler holds a real `PyObject*`
     handed to it by an embedded CPython, it MUST play by CPython's own
     memory-management rules, which are refcounting. This is not a
     violation of "no refcounting by default" — it's refcounting at a
     foreign-runtime boundary, which is a different thing, and real Mojo
     does the identical thing for its own `PythonObject`. Don't generalize
     this pattern to non-Python values; don't let it justify introducing a
     refcount field on `MojoDict`/`MojoList`/`MojoSet` "for consistency."

## Proposed phased implementation

Ordered so each phase is independently landable, independently testable,
and de-risks the next one — mirrors how the A3 coroutine stack-switch
project (`doc/COROUTINE.html`) was staged, which is this project's closest
precedent for "big semantic project done in reviewable layers."

### Phase 0 — parser/AST completeness audit (small, do first)

**STATUS (2026-09-15): LANDED.** Confirmed all convention keyword
spellings (old and new: `inout`/`mut`, `borrowed`/`read`, `var`/`owned`)
parse correctly into `param_convs` for free functions, struct methods,
`self`, and `async def` — no gaps found. Added canonicalization
(`Parser._canon_conv` in `mojo_compiler.py`) so `param_convs` always
stores the canonical spelling regardless of which keyword the source
used, so every later consumer checks one spelling, not two synonyms.
Confirm every convention keyword and `^` round-trips through the AST with
no gaps, across all syntactic positions this compiler accepts (function
params, method `self`, lambda/closure params if any, nested function
defs). Write down param_convs' exact value space (`read`/`mut`/`owned`/
`var`/`out`/`ref`/`deinit`/`None`) as a fixed enum other phases key off of,
rather than raw strings scattered through match sites. No codegen/
runtime change in this phase — pure audit + maybe a small refactor of
`param_convs` from `dict[str,str]` into a typed enum.

### Phase 1 — move tracking & use-after-move diagnostics (compile-time only)

**STATUS (2026-09-15): LANDED.** `ownership_check.py` + `test_ownership_
check.py` (24 fixture cases as of Phase 2 landing, see below). Validated
against real source, not just fixtures: zero crashes and zero false
positives across a full sweep of the real Modular Mojo stdlib tree on this
machine (664 `.mojo` files under `std/`, `test/`, everything). That sweep
FOUND and fixed five real false-positive classes during development (not
hypothetical — each cost a real diagnosis pass against actual stdlib
source): an unhandled `ComptimeIfStmt` branch shape (fstat.mojo), an
unhandled `WalrusExpr` rebind inside a loop (tempfile.mojo), the
`owned`-parameter-implies-move mistake described in the module's own
docstring (path.mojo/asyncrt.mojo/iter), a try/except handler seeing
post-try-body state instead of pre-try state (iter/__init__.mojo), and
`x.type`/`type_of(x)` compile-time-type-only reads being misread as
runtime uses of a moved value (asyncrt.mojo, test_arc.mojo). Re-run the
stdlib sweep (see the module docstring for the exact command shape) after
any future change to this file — it has caught real, non-obvious bugs
every time it's been run so far, not just confirmed a clean bill of
health.
A new per-function static-analysis pass (new module, e.g.
`ownership_check.py`, run after parsing, before/alongside codegen):
- Walk each function body in AST order (straight-line + branches/loops),
  tracking each local binding's state: `Live`, `Moved`, `Uninit`.
- `x^` and passing `x` to an `owned` parameter transitions `x` to `Moved`.
- Any subsequent read of a `Moved` binding on a path that doesn't
  re-assign it first is a **compile error** (this is a real, useful
  diagnostic on its own, independent of anything else in this doc —
  ship it as soon as it's correct).
- Branches: a binding moved on only one arm of an `if`/`else` is `Moved`
  after the join only on paths that took that arm — standard flow-
  sensitive analysis (a value moved in one branch and not the other is a
  real Mojo compile error too: "conditionally moved").
- Loops: a value moved inside a loop body must not be used on the next
  iteration — treat loop-back-edges conservatively (if it's not
  re-initialized before the back-edge, it's an error) rather than
  attempting precise fixed-point analysis initially.
- No codegen changes yet. This phase's entire value is a correctness
  diagnostic + the data structure (per-binding move points) later phases
  consume.
- Test plan: a fixture-driven accept/reject test file, mirroring
  `test_type_system.py`'s structure — dozens of small `.mojo` snippets
  each expected to either compile clean or fail with a specific
  use-after-move diagnostic.

### Phase 2 — aliasing / borrow-checker rules (compile-time only)

**STATUS (2026-09-15): LANDED, narrower than originally scoped —
intentionally.** Implemented as single-call-argument-list aliasing only
(`_check_call_aliasing` in `ownership_check.py`): the same binding passed
through two-or-more of a resolved callee's parameters where at least one
is `mut` (e.g. `swap(x, x)` for `def swap(mut a: Int, mut b: Int)`). The
"live for the duration of a call" cross-statement tracking this section
originally sketched was NOT built — this codebase genuinely has no
first-class reference value that survives past its one call expression to
track (confirmed while implementing: there's nothing resembling a stored
`ref`/`Pointer` binding anywhere real to hang a "still borrowed" state
on), so the single-call-argument-list scope is not a shortcut taken under
time pressure, it's the actual boundary of what's expressible today.
Revisit this section for real once/if `ref`-typed locals get real
first-class support. Same real-stdlib-sweep validation as Phase 1: 664
files, 0 false positives, 0 crashes; the three deliberate REJECT fixtures
(`same_name_aliases_two_mut_params`, `same_name_aliases_mut_and_read_
params`) confirm it actually fires, not just stays quiet.

Extend the Phase 1 pass to also track *live borrows* of each binding
(a `read` or `mut` reference taken by a call argument, for the duration
of that call — this compiler has no first-class reference/lifetime
values to track beyond a call's argument-passing, which keeps this phase
scoped and tractable):
- While a `mut` borrow of `x` is live (i.e., during the callee's
  execution — approximate this as "during that one call expression" since
  there's no cross-statement reference storage in real Mojo either
  without explicit `Pointer`/`ref` values, which are out of scope here),
  no other borrow of `x` may be taken — e.g. `f(x, mut x)` or nested calls
  that alias the same binding both mutably and otherwise.
- Also a compile-time diagnostic only, same fixture-test structure as
  Phase 1. No runtime/codegen change.

### Phase 3 — ownership-directed destruction (supersedes the ad hoc escape analysis)

**STATUS (2026-09-15): GROUNDWORK LANDED (`ownership_destruct.py` +
`test_ownership_destruct.py`), NOT the finished phase — do not wire this
to codegen yet.** What it does: a whole-function (not flow-sensitive),
deliberately low-recall static analysis identifying local bindings that
are PROVABLY a function's sole, permanent owner (never aliased, returned,
`^`-transferred, passed to a non-`read` parameter, captured by a closure,
or `del`'d) of a container they construct exactly once. Validated the
same way as Phases 1-2: 15/15 fixtures (including two real bugs found and
fixed by the fixtures themselves — a missed `^`-inside-call-argument scan,
and a wrong test expectation this exercise corrected, see the module's
own history), plus a full sweep of the real Modular stdlib tree (664
files): 0 crashes, 115 real candidate functions found across 30 files,
spot-checked by hand and confirmed genuine (e.g. `test_list.mojo`'s
`test_list_resize`'s `l: List[Int] = [1]`, used only via `.resize()`/
`.shrink()`/subscript — a real, correct destroy candidate under this
runtime's own heap-boxed-everything model, independent of what real
Mojo's own stack-vs-heap allocation would choose for the same code).

**UPDATE (same day): the definite-assignment gap above is now closed** —
`_definitely_assigned` (a second pass over the same function, tracking
"names definitely assigned on every path" via set intersection across
every if/elif/else/loop/try/except arm, excluding `raise` as a
function-exit point since the exception-unwinding gap below makes that
its own unresolved problem) is now composed into `analyze_function`'s
result. Re-validated: 20/20 fixtures (5 new, specifically targeting this
gap — an if-only-one-arm case, a loop-body-only case, and a try-body-only
case all now correctly excluded), and the full 664-file real-stdlib sweep
is UNCHANGED at 0 crashes / 115 candidates across 30 files — every
previously-found real candidate was, in fact, already definitely assigned
in practice, so this closed a real soundness hole without losing any of
the validated signal.

**Still NOT ready to wire into codegen**, and this is now the accurate
remaining list: the codegen-surgery step itself (wiring into
`gimple_gen_stmts.py`/`gimple_gen_funcs.py` to actually emit `mojo_*_free`
calls at the points this analysis identifies), PLUS the exception-
unwinding gap and the coroutine-frame-lifetime gap documented in the
cross-cutting section below. This groundwork now answers "which bindings,
freed where" soundly for the ordinary-control-flow case; it does not yet
answer "how do those frees survive an exception" or "what does this mean
inside a suspended coroutine frame" — those remain separate, unresolved
projects, not smaller follow-ups of this one.

Once those gaps are closed, the plan below still applies:
- Using Phase 1's per-binding move data, a local binding that (a) owns a
  `MojoDict*`/`MojoList*`/`MojoSet*`/destructible struct value, and
  (b) is never moved out (never `^`-transferred, never passed to an
  `owned` param, never returned) by the end of its function, is
  PROVABLY the sole, permanent owner of that value for its whole
  lifetime — emit the matching `mojo_*_free`/`__del__` call at every
  return/fallthrough point that binding is still live and un-moved.
- A binding that IS moved out at some point needs the free call placed
  only on the paths where it WASN'T moved (flow-sensitive, using the same
  data Phase 1 already computed) — this is strictly more precise than
  the ad hoc "does it escape anywhere in the function, if so never free
  it" conservative rule sketched in
  `bugs/CODEGEN_container_no_deallocation_unbounded_growth.md`'s "where
  the fix goes" section. Recommend abandoning that doc's standalone
  escape-analysis plan once this phase lands — implement the fix here
  instead, and close that bug doc against this one.
- Nested/loop-body-scoped bindings (the `leak_check.mojo` repro's actual
  per-iteration `d`/`s`/`l`) fall out of this naturally: each loop
  iteration is its own binding lifetime, so a container created and never
  moved out of the loop body gets freed at the bottom of each iteration —
  this is the case the ad hoc function-scope-only first cut explicitly
  said it would NOT handle; this phase's flow-sensitive approach handles
  it directly, no special-casing needed.
- `mojo_dict_clear`'s existing double-free war story
  (`runtime/mojo_runtime.c:2441-2449`) is exactly the class of bug this
  phase must not reintroduce — test aliasing (`x = d; y = x`) explicitly:
  only ONE of the aliases should ever be considered "the owner" for
  free-emission purposes (Phase 1/2's move-tracking should already make
  `y = x` either an error, per real Mojo's copy/move rules for
  non-`@value` types, or a real copy via `__copyinit__` — either way there
  should never be two live bindings that both think they own the same raw
  pointer without one of them being a checked-out borrow).
- Test plan: the existing `leak_check.mojo` repro from the two bug docs,
  re-run through `leaks --atExit` before/after — physical footprint should
  go from growing-with-iteration-count to flat. Then the harder test:
  self-hosted `myinterpreter.py` (already part of `make check-selfhost`)
  under the same `leaks` check as a real-world stress case, since it's
  full of exactly the closures/nested-containers/aliasing shapes that
  make this phase hard (see the earlier discussion in this conversation).

### Phase 4 — real calling convention (owned = move, read = true immutable borrow)
Once Phase 1-3 exist, make the C ABI reflect the declared convention
instead of "everything's an aliasable pointer":
- `owned`/transferred-`^` arguments: caller emits no free for that value
  (ownership left with the callee); callee is now responsible per Phase 3.

  **BLOCKED 2026-09-15 — do not implement without Phase 5 first, this is
  a real, verified hazard, not just caution.** Checked `^`'s ACTUAL
  codegen (`gimple_gen_exprs.py:662`): `if node.op == '^': return ot, ov`
  — a complete no-op. There is no move, no copy, no source invalidation;
  `f(d^)` and `f(d)` compile to byte-identical C, a plain pointer
  pass-through either way. Real Mojo's rule is that passing a bare value
  (no `^`) to an `owned` parameter triggers an IMPLICIT COPY (caller and
  callee end up independently owning separate values); only an explicit
  `^` is a genuine move. This codegen implements neither distinction.
  Consequence: making a callee free its own `owned` parameter (this
  bullet's plan) would be unconditionally unsafe for ANY call site that
  passes a value to an `owned` parameter without `^` — which real Mojo
  code is free to do, relying on the implicit copy — since the callee
  would free memory the caller still holds and expects to remain valid
  (or, if the caller's own copy is itself a Phase-3 candidate, freed
  again at the caller's own return: a guaranteed double-free). This is
  exactly what Phase 5 (real move vs. copy) is a prerequisite for, now
  confirmed by direct inspection rather than inferred from the doc's own
  ordering. Do not attempt this bullet until Phase 5 lands and every
  `owned`-parameter call site either does a real copy or the compiler
  hard-rejects a missing `^`.
- `read` arguments: today's plain pointer pass-through is *already*
  functionally a read-only-in-practice borrow as long as codegen never
  emits a mutating call through a `read`-declared parameter — add a
  compile-time check (extension of Phase 2) rejecting any mutating method
  call/assignment through a `read` parameter, rather than a runtime
  distinction; the C representation doesn't need to change, just what's
  allowed to compile.

  **NOT started.** Unlike the `mut` bullet below, this rule doesn't exist
  in `ownership_check.py` at all yet — it needs a genuinely new analysis
  (walk a function body, flag any assignment/mutating-method-call/
  mutating-argument-position through a `read`-declared parameter), not
  just wiring up something already validated. Deferred rather than
  rushed given the remaining session time went to the `mut` bullet
  instead (see below) — enumerating "what counts as mutating" exhaustively
  and correctly is real, unrushed design work of its own.
- `mut` arguments: same representation as today, but Phase 2's exclusivity
  rule is now enforced, which is the actual safety property real Mojo
  sells here.

  **LANDED 2026-09-15.** `ownership_check.check_module` (Phase 1 move-
  tracking + Phase 2 exclusivity, both landed and fixture-validated since
  earlier the same day) had never actually been wired into a real
  compile — reachable only from its own test suite and `__main__` block,
  so a real violation compiled clean either way. Before wiring it in as a
  hard gate, re-ran it (fresh, not from memory) against the full 664-file
  real Modular stdlib AND this project's own 60-file self-hosted-
  compiler/test corpus (724 files total): 0 diagnostics, 0 crashes —
  the empirical basis for treating a violation as a hard compile error
  (`SyntaxError`) rather than a warning. Wired into `gimple_codegen.py`'s
  `_run_pipeline`, right after parsing and BEFORE `ast_rewriter.rewrite`
  (the same AST shape the 724-file sweep was run against). Verified with
  a real fixture (`consume(x^); print(x)`, a genuine use-after-move):
  correctly rejected with a clear `file:line:col: use of moved value 'x'`
  message; verified the escape hatch (`MOJO_SKIP_OWNERSHIP_CHECK=1`,
  matching this project's `MOJO_CORO=cpp`/`MOJO_NO_SHIM=1` convention)
  bypasses it. Full gate re-run clean (test suites incl. the two
  ownership fixture suites, `check-linkmode`, `check-selfhost` — the
  compiler's own self-compile hits zero false positives — stdlib dylib
  rebuild 0 skips, `compile_stdlib.py` 664/664 matching the standalone
  sweep exactly, `make bootstrap` 180/180); `check-native-dumpfull`
  verification handed off mid-session to another agent already doing
  that specific A/B work — not independently re-confirmed here for this
  change.

### Phase 5 — real move vs. copy for `@value` structs
Give `__moveinit__` a real body distinct from `__copyinit__`: a move
should be a shallow field copy PLUS leaving the source's destructor a
no-op (mark it moved-from, matching Phase 1's tracking, so the source's
own end-of-scope destructor call from Phase 3 is skipped for that
binding) instead of today's identical-to-copy deep-copy body. This is
required for Phase 3's destruction logic to be correct for struct values,
not just raw containers.

### Phase 6 — performance payoff (the actual "compete with Rust" step)
Directed to start here 2026-09-15, ahead of Phases 4-5, despite this
section's own original "only attempt once Phases 1-5 are solid" caution
— see the v0 landing below for how the scope was narrowed to stay safe
anyway. With real ownership known statically:
- Non-escaping containers/structs (Phase 3 already proves this) can be
  **stack-allocated** instead of `malloc`'d through `mojo_*_new` at all,
  eliminating the per-container heap round-trip entirely for the common
  case — this is the single biggest performance lever available and is
  categorically unreachable without Phases 1-3 existing first.
  This directly reframes the historical Metal/MSL offload goal (see
  memory: MSL/Metal offload long-term goal) — stack-allocating hot-path
  containers is a prerequisite for tight GPU-adjacent loops, not just a
  CPU-side win.

  **v0 LANDED 2026-09-15**: only a Phase-3 candidate whose single
  constructing assignment is an EMPTY container literal/call (`{}`,
  `[]`, `set()`, bare `dict()`/`list()`/`set()` with no args) is stack-
  allocated — deliberately narrower than "every Phase-3 candidate," to
  avoid reimplementing `_lower_dict_literal`/`_lower_list_literal`/
  `_lower_set_literal`'s non-empty-population logic (element-type
  inference, spread handling, per-element append dispatch) against a
  stack pointer; a non-empty-literal candidate keeps today's exact heap
  alloc + `mojo_*_free`, tracked via a per-name `_owned_stack_allocated`
  set so nothing can ever apply the wrong teardown to the wrong case.
  `runtime/mojo_runtime.{c,h}`: `mojo_dict/list/set_init`/`_destroy`
  (the in-place halves of `_new`/`_free`, which are now thin wrappers
  around them) — `_destroy` tears down only the internal buffers/
  registry membership, never the struct pointer itself. The cleanup-
  thunk registry (Phase 3/item 3) gained 3 more kinds
  (`mojo_cleanup_push_{dict,list,set}_stack`) so an exception unwinding
  past a stack-allocated candidate calls `_destroy`, never `_free`
  (which would `free()` a stack address). `gimple_gen_infra.py`'s
  `maybe_stack_alloc_owned_ctor` (called from the central `gen_stmt`
  dispatcher, before normal `VarDecl`/`AssignStmt` lowering) emits
  `{StructType} __name_storage; {init_fn}(&__name_storage); {CType}
  name; name = &__name_storage;` and skips normal lowering entirely for
  that one statement — every later use of `name` (subscript, method
  calls, ...) is unchanged, since it's just an ordinary `MojoDict *`-
  typed C variable from then on, oblivious to its stack-vs-heap origin.
  Verified `-fgimple` accepts this pattern (`gcc -fgimple -fsyntax-only`
  on the exact generated shape) BEFORE writing the codegen, given this
  project's own precedent of `-fgimple` rejecting address-taken locals
  in a different context (`_seed_addressed_locals`/the closure-capture
  fix) — confirmed safe specifically because Phase-3 candidates only
  ever live in plain top-level functions, which `gen_func` never
  `__GIMPLE`-tags (only struct methods and a couple of synthesized
  helpers get tagged, and Phase 3 computes zero candidates for methods
  — see `reset_no_candidates`). Real, measured performance win: a loop
  constructing+destroying 2,000,000 dict locals went from 0.647s (heap)
  to 0.357s (stack) — build-and-run both ways from the same source via
  stash/restore, not simulated. Correctness re-checked under
  `MallocScribble` for every existing repro in this doc PLUS two new
  ones targeting the exact risk this feature introduces: a candidate
  whose empty-literal construction is followed by escaping via a struct
  field assignment (correctly still excluded as a candidate at all, not
  stack-allocated-then-dangling), and the struct-method name-collision
  case from item 3's own fix (still correct with Phase 6 active). Full
  gate re-run clean (test suites, check-linkmode, check-selfhost, stdlib
  dylib rebuild 0 skips, `compile_stdlib.py` 664/664, `make bootstrap`
  180/180); `check-native-dumpfull` re-confirmed as the same pre-existing
  divergence via the same-worktree `--no-cache` A/B methodology (see
  that bug doc's newest entry — identical first-differing-byte offset,
  gap changed by only ~5KB, consistent with the new code itself).
- `read` borrows become truly zero-cost (already almost are, at the ABI
  level) once Phase 4's compile-time enforcement exists, since a `read`
  parameter can safely alias without any runtime check.
- Destructor calls inserted by Phase 3 can be devirtualized/inlined by
  GCC once emitted as direct calls at fixed points (they already will be,
  being plain C function calls) — no extra work needed here beyond what
  Phase 3 already does, but worth measuring.

## Cross-cutting concerns: EH, async/coroutines, Python interop, codegen

Asked directly and answered honestly, 2026-09-15: no, these were NOT fully
thought through before this point — Phase 1 (`ownership_check.py`, landed
this session) only incidentally touches one of the four (a real try/except
bug fixed during stress-testing, below), and the other three are real,
concrete, previously-undesigned gaps, not items being deferred out of
laziness. Each is written up here with what's ACTUALLY true in this
codebase today (verified by reading the real source, not assumed from how
Rust/real-Mojo generally handle it), because bolting ownership onto a
compiler with these four subsystems already at this scale wrong is exactly
how a "looks done, is actually unsound" design happens.

### Exception handling — a real, serious, previously-undiscovered blocker

Confirmed by reading `runtime/mojo_runtime.c:19-46`: this runtime's
exceptions are raw C `setjmp`/`longjmp` — `mojo_raise()` calls
`longjmp((void*)&_mojo_exc_stack[_mojo_exc_top], 1)` straight to the
enclosing `try`'s `setjmp` point. **`longjmp` does not run any of the C
statements between the raise site and the catch point** — no destructors,
no cleanup, nothing; it's a raw stack-pointer/register reset, by design
(this is not a bug in this runtime, it's what `setjmp`/`longjmp` IS).

This means Phase 3's plan as written — "emit a `mojo_*_free` call at every
return/fallthrough point a binding is still live and un-moved" — is
**silently void on every exception path**. A function that allocates a
`MojoDict`, then something three calls deep raises, unwinds via `longjmp`
straight past the dict's owning frame's free call without ever executing
it: that dict leaks, unconditionally, every time, on every exception path,
no matter how correct Phase 1-3's flow analysis is on the non-exceptional
path. Ordinary control flow (the only thing Phase 1's `_terminates`
logic and Phase 3's insertion points reason about) and `longjmp`-driven
unwinding are simply different mechanisms, and only one of them is where
compiler-inserted cleanup code can live.

This also isn't a brand new risk area for this runtime — memory already
recorded "exceptions runtime is broken (setjmp UB)" as a known open issue
independent of ownership work entirely (see
`mojo-reference-quality-gates` in project memory), so this finding adds a
second, ownership-specific reason on top of an already-known-shaky
foundation, not a first one.

Real options, roughly in order of how much they cost:
1. **Scope Phase 3's guarantee explicitly to the non-exceptional path**
   for now, document the exception-path leak as known and accepted, and
   revisit once/if the exceptions runtime itself is redesigned. Cheapest,
   honest, but a real functional gap (any program using exceptions in a
   hot loop still leaks under this scheme).
2. **A real per-frame cleanup registry**: before a `try` block's body
   runs, push a list of "cleanup thunks" (function-pointer + argument
   pairs) for owned locals as they're created inside that frame; catch
   in `mojo_raise()`/the try's landing point.  Deletes as the code walks
   the current stack of pushed thunks calling each — effectively a
   userland reimplementation of what a real unwinder's landing pads give
   you for free, but is buildable ON this exact `longjmp` substrate
   without replacing it. This IS more or less how the Itanium C++ ABI's
   personality function + landing pads work in spirit, just interpreted
   in C rather than table-driven.
3. **Replace `setjmp`/`longjmp` with real stack unwinding** (either hand
   an unwind table to `libunwind`, or migrate exceptions onto the same
   C++ exception mechanism the coroutine runtime already uses in
   `runtime/mojo_async_runtime.cpp` — this file is already compiled as
   C++, so real `throw`/`catch` with RAII destructors is not a foreign
   mechanism to introduce, just not the one `mojo_raise` currently uses).
   Most correct, most expensive — a project on its own, and it fixes the
   independently-known setjmp/UB issue as a side effect.
Recommend option 2 as the first real target once Phase 3 starts, with
option 3 flagged as the "if this project ever needs it to be fully
correct" answer — not attempted now.

### Async/coroutines — closure-capture machinery already exists; ownership doesn't hook into it yet

Checked `gimple_gen_coro.py`: this project already has substantial,
real closure-capture infrastructure for the coroutine backend —
`_capture_scan_body`, `_nested_async_capture_plan`,
`_apply_nested_async_capture` (~line 2000-2290) compute exactly which
outer-scope names a nested `async def` reads/writes and rewrite it to
capture them into the generated coroutine frame struct (this is the
heap-allocated frame the A3 stack-switch runtime suspends/resumes —
`doc/COROUTINE.html`). `^` already appears syntactically in this file too
(`_unwrap_transfer`, `_is_task_wait_call`'s `task^.wait()` pattern) but
purely for AST pattern-matching, not ownership — same no-op treatment as
`gimple_gen_exprs.py`'s general case.

The real interaction Phase 1-3 have NOT accounted for: a value captured
into a coroutine's frame is, by construction, alive across a SUSPENSION
point — its true lifetime is bounded by the coroutine frame's own
lifetime (when the task completes OR is cancelled/dropped early), not by
any single resumption's "straight-line function body" the way Phase 1's
per-function analysis assumes. Concretely:
- A container captured-by-value into the frame and never explicitly
  moved out needs freeing when the FRAME is destroyed, which Phase 1's
  existing move-tracking (scoped to one function's own body, explicitly
  treating a nested `async def`/closure as an opaque black box — see the
  module docstring's stated limitation) cannot see at all today — it
  would need to run over the ALREADY-CAPTURE-REWRITTEN body (post
  `_apply_nested_async_capture`) to have any chance of tracking it, and
  even then "the function's own body" isn't the right lifetime scope —
  "the frame's lifetime" is, which is a coroutine-runtime-level concept
  Phase 1 doesn't model.
- Task cancellation (dropping a suspended coroutine without ever
  resuming it to completion) is exactly real Rust's/real Mojo's hardest
  async-ownership case for a reason: whatever was captured must still be
  destroyed correctly even though the function body's own `return`
  points are never reached. Whether `mojo_coro.c`'s task-cancellation
  path (if this runtime has one — not yet checked in this pass) even
  calls back into anything resembling a destructor path is an open
  question, not confirmed either way here.
**UPDATE (2026-09-15, TODO item 2): read `runtime/mojo_coro.h`,
`mojo_coro.c`, and `mojo_coro_gen.c` in full this session — several things
above turn out to be more precise, and one is a correction of a real
mistake made while reasoning out loud in this same conversation:**

- **Correction, not a new finding — retracting a wrong claim rather than
  letting it stand:** while investigating this live, `__mojo_coro_destroy`
  (`mojo_coro.c:334-359`) was correctly read as freeing only the `MojoCoro`
  control struct and its stack, NOT `c->env` (documented in `mojo_coro.h`:
  "`env` is an opaque heap pointer the caller owns until _destroy"). This
  was then WRONGLY reported as "every generator/coroutine destroy leaks
  its whole captured-environment frame, guaranteed." Re-checked directly:
  `__mojo_gen_destroy` (`mojo_coro_gen.c:253-260`, the actual generator-
  level wrapper every compiled `{base}_destroy` trampoline calls — see
  `gimple_gen_coro.py`'s `_C_TRAMPOLINE_TMPL`) calls `__mojo_coro_destroy
  (g->coro)` and THEN `free(g)` — `g` IS `env` here (it's the pointer
  passed as `__mojo_coro_new`'s `env` argument in `mgen_new_impl`). So the
  top-level frame genuinely IS freed today; there is no separate frame-
  level leak bug. Flagging the correction explicitly, not quietly editing
  history, per this project's own standing feedback on accuracy.
- **The real remaining picture is narrower and more precise than "ownership
  across suspension is totally undesigned":** `mojo_coro.h` states plainly
  that a generator/async body's OWN local variables run on a REAL C stack
  (the A3 stack-switch mechanism), not in a separate heap frame with its
  own lifetime rules — `MojoGen` (`mojo_coro_gen.c:33-43`) only holds the
  function's CALL ARGUMENTS (`args[MOJO_GEN_MAX_ARGS]`, boxed scalars) and
  bookkeeping, not a generic capture frame for arbitrary body locals. A
  container `d = {}` declared directly inside an `async def`'s own body
  has the SAME kind of lifetime an ordinary function's local does — this
  wiring's existing exclusion of `is_async`/`is_generator` functions (see
  item 1 above) is about `return`/`yield` being lowered differently, not
  about some fundamentally different frame-lifetime model needing a
  separate design from scratch.
- **What actually IS still open, precisely:** (a) `return e` inside a
  coroutine body lowers to `__mojo_coro_set_return(...)` + fall-through
  (`mojo_coro.h`'s own comment), not the plain C `return` this wiring's
  `_gen_stmt_ReturnStmt` insertion point was built and validated against
  — needs its own, separate insertion point at THAT lowering site, not
  yet located; (b) MORE IMPORTANTLY, a suspended coroutine can be
  abandoned at a `yield`/`await` point without ever reaching ANY return —
  `__mojo_coro_destroy`'s cancellation path (`mojo_coro.c:338-357`)
  handles this by re-entering the body with a synthetic GeneratorExit
  raised AT the suspension point, specifically so `with`/`finally` cleanup
  still runs. That re-entry drives the exact same `mojo_raise`/`longjmp`
  exception machinery already flagged as broken for cleanup purposes in
  this doc's OWN exception-handling section above — so async/coroutine
  ownership's real dependency, precisely stated, is: **it cannot be done
  correctly before the exception-unwinding gap is fixed**, not because
  coroutines are independently mysterious, but because coroutine
  cancellation IS an exception-unwind scenario running through the same
  broken mechanism. This is a real, useful narrowing: one fix (the
  per-frame cleanup-thunk registry already proposed in that section)
  plausibly resolves both gaps' cancellation/interruption path at once,
  rather than needing two independent redesigns.

Recommendation, updated: don't design async/coroutine ownership as its own
from-scratch project — land the exception-unwinding fix first (still not
started, tracked separately below), then re-assess how much of the
async/coroutine gap it already closes before designing anything further
bespoke to coroutines specifically.

### Python interop — the boundary is real and already correct; don't let Phase 3 reach across it

Already covered under rule 8 above: `runtime/mojo_python.c` does real
`Py_INCREF`/`Py_DECREF` against CPython's own `ob_refcnt`. The one
NEW risk Phase 3 introduces that rule 8 didn't need to address yet: once
this compiler starts emitting real destructor calls at scope-exit
points, it must dispatch to the RIGHT destructor for a given local's
actual kind — `Py_DECREF` for a `PythonObject`-boxed handle,
`mojo_dict_free`/`_list_free`/`_set_free` for this runtime's own
containers, a struct's own `__del__` for a user struct, and NOTHING for
a plain scalar. Confirm (during Phase 3, not before — no code to check
yet) whether this compiler's own type inference already tags a
`PythonObject`-typed local distinctly enough from an ordinary boxed
`int64_t`/pointer to route it to `Py_DECREF` instead of blindly assuming
`mojo_dict_free` for anything pointer-shaped — the `_mojo_list_registry`-
style "guess the kind from a runtime set-membership probe" pattern this
doc's "explicit non-goal" section already flags as a shortcut to remove
would be actively WRONG here (`Py_DECREF`-ing a `MojoDict*` that
happened to collide, or `mojo_dict_free`-ing a real `PyObject*`, both
corrupt memory rather than merely leak it) — this is a second, concrete
reason (beyond that section's original one) that dispatch must become
real static-type-driven, not guessed, before Phase 3 emits anything.

### Codegen integration in general — Phase 1 is source-level only; nothing here has touched gimple_codegen.py

Worth stating plainly: everything landed this session
(`ownership_check.py`) is a standalone AST-level analysis pass that runs
BEFORE codegen and never calls into `gimple_gen_*.py`/`gimple_codegen.py`
at all. It has not been wired into `fire.py`'s build pipeline, doesn't run
as part of `make check`, and produces diagnostics nobody currently reads.
Phase 3 is where this stops being purely additive and starts requiring
real codegen surgery (inserting actual `mojo_*_free`/`__del__` calls at
points `gimple_gen_stmts.py`/`gimple_gen_funcs.py` currently just
fall through). That integration work hasn't been scoped in code yet,
only sketched narratively above — don't treat Phase 1 landing as evidence
Phase 3 is a small step from here; the analysis and the codegen surgery
are genuinely separate bodies of work that happen to share one data
model.

## Effort and risk, honestly

This is a multi-phase feature project on the scale of (likely larger
than) the coroutine A3 stack-switch project — that took multiple staged
commits across weeks (`doc/COROUTINE.html`; see also
`coroutine-a3-stackswitch-project` in memory). Do not attempt Phases 3+ in
one sitting; each phase above is meant to be its own reviewable
commit/PR, gated by this project's full quality gate (CLAUDE.md's
"Quality gate for gimple/codegen-affecting changes" — every phase past 0
touches `mojo_compiler.py` and/or `gimple_gen_*.py`, so all of it applies:
`make check-linkmode`, `make check-selfhost`, a from-scratch stdlib dylib
build, `compile_stdlib.py`, `make bootstrap`, `make check-native-dumpfull`).
Phases 1-2 are the safest to start with: pure diagnostics, zero risk of
silently miscompiling anything that compiles today, and they build the
exact data structure (per-binding move/lifetime info) every later phase
needs. Phase 3 is where real payoff (fixing the leak bugs correctly)
starts, and where the risk also starts — recommend treating it the way
the coroutine project treated its own riskiest layer: land behind
extensive fixture tests and the full gate before considering it done, and
be honest in the bug docs about partial progress rather than claiming
completion early.

## Relationship to other in-flight docs

- `bugs/CODEGEN_container_no_deallocation_unbounded_growth.md` and
  `bugs/CODEGEN_container_free_registry_dangling_entries.md` — the
  pragmatic short-term fix for the immediate leak; Phase 3 above is the
  correct long-term replacement for the first doc's ad hoc escape
  analysis. Keep both bug docs open and cross-referenced to this doc until
  Phase 3 actually lands.
- `doc/COROUTINE.html` — closest precedent in this codebase for how to
  stage a large semantic/codegen project safely.
- `msl-offload-longterm-goal` (memory) — Phase 6's stack-allocation payoff
  is a direct prerequisite for that goal, not a separate track.
