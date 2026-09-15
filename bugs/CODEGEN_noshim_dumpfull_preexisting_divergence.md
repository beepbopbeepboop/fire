# CODEGEN_noshim_dumpfull_preexisting_divergence: check-noshim-dumpfull fails on b00955c itself

## Status (2026-09-15, later still — re-confirmed pre-existing a third time, widening Phase 3 eligibility to try/except-containing functions)

Same gate failure a third time this session, now after widening
`_is_free_eligible_function` (`gimple_gen_infra.py`) to stop excluding a
function containing its own `try`/`except` — item 3's cleanup-thunk
registry (previous entry below) makes that safe. This run:
shim=36291056 bytes, no-shim=35761631 bytes, first differing byte still
at the SAME offset 21086, gap 529425 (~530KB, unchanged) — only a ~3KB
shift on each side from more functions now qualifying for the
push/cancel emission, not a new divergence source. Same standing
conclusion.

## Status (2026-09-15, later same day — re-confirmed pre-existing a second time, during the ownership-model exception-unwinding fix)

Hit this same gate failure again running the full CLAUDE.md gate for
doc/OWNERSHIP_MODEL.md's TODO item 3 (the cleanup-thunk-registry
exception-unwinding fix: `mojo_cleanup_push_dict/list/set`,
`mojo_cleanup_cancel_n`, `mojo_cleanup_checkpoint_save` in
`runtime/mojo_runtime.{c,h}`, wired from `gimple_gen_stmts.py`/
`gimple_gen_infra.py`). This run: shim=36288039 bytes,
no-shim=35758312 bytes, first differing byte at offset 21086 — same
~20800-21100 first-divergence window and same ~530KB
(36288039-35758312=529727) gap as the entry just below from earlier
today, both up by ~28KB on each side from this session's own added
code being dumped identically on both the shim and no-shim sides
(28177 / 28490 bytes respectively — consistent with new code being
counted, not new divergence). Confirms, independently of that entry's
own `git worktree` check, that this specific feature session isn't the
cause either. Not investigated further — same standing conclusion as
below.

## Status (2026-09-15 — re-confirmed pre-existing during an unrelated feature session; still failing, symptom shape changed again)

Hit this gate failure while running the FULL CLAUDE.md quality gate for
the doc/OWNERSHIP_MODEL.md Phase 3 codegen-wiring work
(`gimple_gen_infra.py`'s `begin_function`/`emit_return_frees`/
`emit_fallthrough_frees`, `ownership_check.py`, `ownership_destruct.py` —
see that doc's TODO item 1). Before assuming the new feature caused it,
verified definitively via a clean `git worktree add /tmp/... HEAD` (no
uncommitted changes at all) rebuild of `mojoc`: the exact same class of
shim-vs-noshim divergence reproduces on an untouched checkout, confirming
(again, independently of the 2026-09-13/14 sessions below) that this is
not caused by that session's work either. Today's specific symptom:
`LayoutSolver` (`gimple_solvers.py`) — a struct whose only real instance
fields are `_struct_types`/`_ea` (see its `__init__`) — gets TWO EXTRA
struct members in the shim's build, `int64_t HEAP; int64_t STACK;`,
matching the class's own class-level string constants (`STACK = 'stack'`,
`HEAP = 'heap'`) being (incorrectly, in the shim's version) swept into the
instance struct layout; the no-shim/self-hosted build omits them. First
divergence around byte offset ~20800-21100, both today's clean-HEAD run
and the with-my-changes run — consistent with this being the SAME
systematic self-host struct-field-inference divergence this doc has
tracked since 2026-09-13, now presenting as a per-class extra/missing
FIELD PAIR rather than a whole dropped module. Byte-count gap this run:
shim=36259862, no-shim=35729822 (~530KB, shim larger) — same order of
magnitude as session 4's "~350KB, not yet zero" state below, consistent
with "still open," not a fresh regression.

**Confirms this doc's own standing conclusion still holds**: gate step 5
(`check-noshim-dumpfull`) should be expected to keep failing on this repo
until the work below (or its continuation) is finished — that is a
pre-existing, tracked condition of the gate itself, not something an
unrelated feature session should be blocked on or expected to fix as a
side effect. Do not spend further time chasing this from an unrelated
session without first reading this doc's full history below.

## Status (2026-09-14, session 4 — 7 more root causes fixed; diff narrowed ~3.8MB → ~350KB; NOT yet zero, 8th blocker precisely diagnosed and deferred)

See "## Session 4 final summary (2026-09-14)" near the end of this doc
for the complete accounting of this session's work: seven independent,
gate-verified fixes landed (commits `5cc83e5`, `078c103`, `972850f`,
following on from `585879c`/`dba69b8` in session 3), all downstream/gate
impact confirmed (a real external project, a GCC frontend vendoring this
compiler, went from 9944 gcc errors to 0), and the remaining gap is now
tied to a specific, already-tracked, separate deferred project
(`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`)
rather than being open-ended or unknown.

## Status (2026-09-13 — found, NOT fixed, confirmed pre-existing)

`make check-noshim-dumpfull` (`test_noshim_dumpfull.py`, added in commit
`b00955c` as DESIGN.html R6) fails:

```
✗ MOJO_NO_SHIM=1 ./mojoc output DIFFERS from the shim's own --dump-full
output: shim=32886825 bytes, no-shim=~27-28MB, first differing byte at
offset 2390 - the self-hosted binary is miscompiling itself even though
it exited 0
```

**Confirmed pre-existing, not caused by the same-day R3 cast-migration
session**: reproduced identically (same failure, same offset 2390) after
`git stash`-ing every R3-session change back to the exact `b00955c` tree
state and rebuilding `mojoc` from scratch (`rm -f mojoc && make mojoc`).
`b00955c`'s own commit message added this check but — per
`design-container-typing-audit` project memory — "Full gate NOT re-run
after b00955c — only syntax + one real do_imports=True compile check."
This check was added but never actually run to see if it passed; it
doesn't.

The failing byte offset (2390) is very early in the `--dump-full` output
and consistent across multiple independent rebuilds, suggesting a
systematic divergence (e.g. a preamble/header section or an early-defined
symbol) rather than something deep in per-function body codegen. The
overall size gap (~5MB, shim larger) matches the same shape as the
`selfhost-dump-full-module-drop` project memory's prior incident — some
whole section or set of modules is present in the shim's build but
missing from the self-hosted `mojoc`'s own compiled path.

## Root-cause investigation (2026-09-13, continued)

Diffed the actual `.ci` output at offset 2390: the self-hosted (no-shim)
build's forward-declaration list is missing `void
_gimple_gen_coro_toplevel(void);` entirely — present in the shim's output,
absent from the no-shim one. Confirmed this isn't just the declaration:
`grep -c "_gimple_gen_coro_" ` finds 380 occurrences in the shim's `.ci`
vs only 26 in the no-shim one — the self-hosted `mojoc` is dropping nearly
all of `gimple_gen_coro.py`'s own compiled content from its transitive
closure when compiling `mojo.py --dump-full`, matching the
`selfhost-dump-full-module-drop` project memory's prior incident shape
(a whole sibling module silently missing, exit code 0).

**Ruled out:**
- Not caused by this session's R3 work (see Status above — reproduces
  identically on the pristine `b00955c` tree).
- Not simply "imported without an `as alias`" (unlike its ~10 sibling
  `gimple_*` imports in `gimple_codegen.py`, `import gimple_gen_coro` has
  no alias) — built a minimal 2-module isolated repro (one aliased import,
  one bare) and both modules were fully compiled in both the shim and
  no-shim `--dump-full` output; the drop did not reproduce in isolation.

## Root-cause investigation (2026-09-13, continued further — two real findings)

Instrumented `_compile_imported_module`/`gen_module_impl` with temporary
`print()` tracing (env-var-gated at first, then a plain module-level
`bool` constant after `os.environ.get()` itself turned out to be
self-host-unreliable — see Finding 2 below) and rebuilt `mojoc` to trace
exactly what happens compiling `gimple_gen_coro.py`.

**Finding 1 (REAL BUG, FIXED, commit-worthy on its own)**: the trace
showed thousands of `vars: unavailable in compiled mode` messages fire
the instant `gimple_gen_coro.py`'s compile starts. Root cause:
`gimple_gen_coro.py` uses `for k, v in vars(node).items():` (10+ call
sites) to walk AST nodes generically, where `node`'s static type is
deliberately unknown (it needs to handle many different node types
uniformly). `_lower_call`'s `vars()` special case
(`gimple_gen_calls.py` ~line 1534) only routed through the real
`_mojo_dispatch_asdict` reflection helper `if gimple_exprtypes.
_struct_name_of(at) in gen.struct_field_types` (i.e. only when the
STATIC type happens to be known) — otherwise it fell through to the
generic "unresolved builtin" weak-stub path (print-and-return-0, a
no-op). But `_mojo_dispatch_asdict(void *obj)` (gimple_module_gen.py)
is ALREADY a fully general RUNTIME dispatcher — it reads the object's
own type tag via `mojo_read_type_tag_safe` and picks the matching
`_mojo_asdict_<struct>` at runtime, needing no static proof at all.
**FIXED**: removed the static-type gate entirely; `vars(x)` now always
routes through `_mojo_dispatch_asdict` (casting through `void *`).
Confirmed fixed: `vars:` print count in the `--dump-full` trace dropped
from thousands to exactly 0. `compile_stdlib.py` and the container-cast
counter both still pass after the fix (no regression). This means
`gimple_gen_coro.py`'s own generic AST-node introspection was silently
returning empty dicts instead of the node's real fields, throughout
the ENTIRE self-hosted build (not just for `gimple_gen_coro.py` itself)
— a separate, real correctness bug beyond just this gate's failure,
now fixed.

**Finding 2 (root cause of the module-drop, NOT fixed, needs careful
follow-up)**: even after Finding 1's fix, `gimple_gen_coro` still
compiles to `code_len=0` self-hosted. The trace (before the vars() fix
masked it with noise) showed the module-compile's `except Exception as
e:` handler in `gimple_gen_resolve.py` catching:
`AttributeError: environ` (a SEPARATE finding — see below) and, in an
earlier still-cleaner trace, exactly:
`zip() lowering needs a tuple loop target`
— the literal message `_gen_for_zip` (`gimple_gen_loops.py:1030`)
raises for `for (_n, a), pk in zip(real_params, param_kinds):`
(`gimple_gen_coro.py:2481` — a nested-tuple `zip()` target, an
explicitly-unsupported shape by design). This raise is SUPPOSED to be
caught locally by the `try/except` in `_gen_stmt_ForStmt`
(`gimple_gen_stmts.py` ~line 2731), which rolls back and falls through
to `_gen_for_iter(node)` — and does so successfully in the shim (the
shim's `--dump-full` contains gimple_gen_coro's full compiled content).
Self-hosted, the exact same exception is instead caught only by the
much-outer MODULE-level handler, meaning the intended LOCAL catch is
being skipped somehow. **Root cause not yet isolated** — ruled out
"try/except doesn't work at all self-hosted" (a standalone 2-level
nested try/except repro, built and RUN as an ordinary compiled target
program via `mojo.py build`, correctly caught a `ValueError` raised
from a helper two calls deep), and ruled out "only one unprotected call
site" (`_gen_for_zip` has exactly one caller, and it IS wrapped in
try/except). The exact mechanism by which THIS SPECIFIC try/except
fails to catch, only when the code compiling it is itself running
self-hosted, is still unknown.

**Finding 3 (separate, real, worth its own follow-up)**: `os.environ.get(...)`
itself raises `AttributeError: environ` in some self-hosted contexts
(discovered as an artifact of debug instrumentation — do not assume
`os.environ` is safe to use in this codegen's own source without
testing first).

**Important operational lesson learned the hard way**: setting a
debug-tracing module-level constant to `True` (to make the trace
`print()`s active) — even though it's a plain Python `bool` with no
apparent relationship to codegen logic — broke `make mojoc`'s own
SHIM-compiled build entirely (`error: invalid use of undefined type
'struct _gimple_gen_coro_toplev'`, `'struct _reflect_toplev'`). This
compiler does WHOLE-FUNCTION type unification (already documented
elsewhere in this codebase re: the `_mn`/`module_name` loop-variable
gotcha in this exact function) — adding new code to a self-hosted
function, even genuinely dead/inert-at-runtime code behind an `if
False:`-shaped guard, can still shift how OTHER variables in that same
function get statically type-inferred by THIS compiler's own
self-compilation, breaking things that had nothing to do with the
change. All temporary debug instrumentation for Findings 2/3 was
reverted (`git checkout --`) rather than left in the tree, even
disabled — confirmed `make mojoc` rebuilds clean (0 errors) again
afterward. **Any further debugging here should default to gdb on the
actual `mojoc` binary (per `HOW-TO-DEBUG.html`) rather than adding new
source-level tracing to the compiler's own self-hosted functions**,
given this demonstrated fragility.

## Root cause of Finding 2, FOUND AND FIXED (2026-09-13, same day, via lldb)

Used `tools/gdbtool` (lldb) directly on the `mojoc` binary rather than
more source instrumentation, per the lesson above. Set a conditional
breakpoint on `mojo_exc_msg_set` (`strstr(msg, "tuple loop target")`)
and walked the backtrace at each hit:

- First hit: inside `_gen_for_zip_ba2192` called from
  `_gen_stmt_ForStmt_ba2192`'s try block (`gimple_gen_stmts.py:2732`) —
  watched `_mojo_exc_top` (7 → 6 via `mojo_exc_pop`) and confirmed
  `mojo_raise()`'s `longjmp` correctly returned control to the `except`
  block at line 2736. This occurrence (compiling `mojo_compiler.py` as
  a nested import) is caught CORRECTLY self-hosted — the try/except
  mechanism itself is not broken in general.
- Second hit: same raise, but frame #1 was `__mojo_coro_yield`, called
  from `__mgco__iter_ast_body` (`gimple_gen_stmts.py:254`, the compiled
  coroutine for `_iter_ast` — see Finding 1's sibling function) —
  i.e. the raise fired WHILE a compiled coroutine (`_iter_ast`) was
  suspended mid-`yield` on the call stack. A `try/except`'s `setjmp`
  captured on the ORIGINAL (resuming) stack, longjmp'd to FROM CODE
  RUNNING ON THE GENERATOR'S OWN SEPARATE FIBER STACK, is undefined
  behavior — exactly the documented coroutine/setjmp hazard, now hit in
  a new combination (a try/except elsewhere in the pipeline, racing
  against an unrelated coroutine walk on the stack at raise time).

**Fixed**: converted `_iter_ast` (`gimple_gen_stmts.py`) and its sibling
`_walk` (`gimple_gen_coro.py`, confirmed via a second lldb session to be
the OTHER offender specifically for `gimple_gen_coro.py`'s own module
compile — the `__mgco__walk_body` coroutine caught suspended at the
exact same raise) from `yield`-based generators to plain iterative
list-building functions (see the commit landing this fix for the full
diffs). Verified via `test_noshim_dumpfull.py`: the shim-vs-noshim size
gap dropped from ~4MB to ~196KB, and the failing byte offset moved from
2390 (`gimple_gen_coro` almost entirely missing) to 2894 (`myinterpreter`
module missing instead — see Finding 4 below). `gimple_gen_coro` is now
byte-for-byte present in both builds.

## Finding 4 (a THIRD, separate divergence — isolated, NOT fixed)

With Findings 1/2 fixed, the next (and much smaller) divergence is the
`myinterpreter` module dropping to `code_len=0` self-hosted, with:

```
cannot coerce MojoList * to MojoDict * (incompatible container kinds)
at myinterpreter.py: value='_t32' dest='_t33'
```

Backtraced via lldb (conditional breakpoint on `mojo_exc_msg_set` for
"cannot coerce") to `_lower_dict_method` (`gimple_gen_methods.py:3043`,
the `dict.update()` handling) called with `ov` statically typed
`MojoDict *`. The real source line is `myinterpreter.py:3326`:
`from_base.update(base_cls.methods.keys())` inside
`execute_StructDef`, where **`from_base = set()`** is declared
unambiguously three lines earlier (line 3314) and used consistently as
a set everywhere (`.update()`, `in`, `.discard()`). The compiler
mis-infers `from_base`'s declared type as `MojoDict *` instead of
`MojoSet *` — self-hosted only; the shim compiles this function
correctly.

**Precisely bisected the trigger** (repeatedly truncating a copy of the
real `myinterpreter.py` and re-running `MOJO_NO_SHIM=1 ./mojoc <file>
--dump-full`, ~15s per iteration, no `mojoc` rebuild needed since only
the INPUT file changes): the mistyping requires the LITERAL PRESENCE,
anywhere later in the same file/class, of a `self.<attr>.update(...)`
call — specifically the METHOD NAME `"update"` on a `self.` attribute.
Confirmed via direct substitution experiments:
- Removing `self.global_vars.update(node.names)` (replacing with `pass`)
  → bug disappears.
- Changing the ARGUMENT (`node.names` → `set(node.names)`, a `MojoSet *`
  instead of `MojoList *`) → bug still present (argument type is
  irrelevant).
- Changing the METHOD NAME (`.update(...)` → `.add('x')`) → bug
  disappears (method name specifically matters, not just "any call on
  a self attribute").

This means an UNRELATED method (`execute_GlobalStmt`, ~700 lines later
in the file) merely CONTAINING a `self.X.update(...)` call corrupts a
completely different method's (`execute_StructDef`) local variable
inference. **Root cause NOT found** despite substantial further
effort: ruled out `_infer_param_types`/`is_dict_method` (scoped to
function PARAMETERS only — `from_base` is a local, not a parameter, so
this code path doesn't apply); ruled out `_SELFHOST_MODGLOBAL_CACHE`
(keyed only by genuine MODULE-LEVEL globals, and `from_base` is not a
module-level name anywhere in this codebase); ruled out a declared-type
conflict for the `self.global_vars` field itself (all 3 real usages
treat it consistently as a set); read `_infer_local_var_types`
(`gimple_gen_resolve.py:2234`) end-to-end — its `gen.var_types`
save/restore is `try/finally`-protected (safe), and a single `from_base
= set()` assignment should join trivially to `MojoSet *` via
`_quick_type`'s `_BUILTIN_CTORS` table. The likely remaining suspect is
the per-class-method loop that calls `_infer_local_var_types(m)` once
per method (`gimple_module_gen.py:5268-5272`,
`for s in all_structs_for_methods: for m in s.methods: ... self.
_infer_local_var_types(m)`) — matching this codebase's own frequently-
documented "loop variable doesn't get a fresh type per self-hosted
iteration" bug class — but this was NOT confirmed; an attempted lldb
watchpoint on `mojo_dict_set_str` (conditioned on `key == "from_base"`)
to catch every write to that name live did not hit within a bounded
wait (there may be MANY unrelated `MojoDict *` instances with string
keys throughout a self-hosted compile — string-interning tables,
memoization caches — making this specific breakpoint too broad/slow to
be practical without a more targeted address or call-site condition).

## Next steps (not attempted this pass)

- Root-cause Finding 4: either (a) set a breakpoint scoped to the
  SPECIFIC `MojoDict *` instance backing `gen.var_types` (need to find
  its address/identity first, e.g. by breaking inside
  `_infer_local_var_types`'s own compiled body and reading `gen`'s
  `var_types` field directly), or (b) bisect the compiler's OWN logic
  the same way the input file was bisected here — comment out
  candidate inference paths in `gimple_module_gen.py`'s per-method loop
  and rebuild `mojoc` (slower: full self-host rebuild per iteration,
  ~2-3 min, vs. the ~15s per-iteration cost of bisecting the INPUT file
  used for Finding 4's isolation) until the corruption stops.
- Investigate Finding 3 (`os.environ` self-host reliability) separately
  — check whether it's a general lowering gap or context-specific.
- This is genuinely open-ended (matches the multi-day effort shape of
  prior instances of this bug class per project memory). Findings 1 and
  2 are real, complete, verified fixes landed this session, closing
  ~95% of the original divergence (shim/no-shim size gap: ~5MB → ~196KB).
  Finding 4 is precisely isolated but not yet root-caused.

## Finding 4 — actually TWO bugs, 2 of 3 fixed, 1 remains (session 2)

Continued via lldb on a real -O0 `mojoc_dbg2` build (Makefile's stage2
recipe doesn't pass `-O`, so gcc defaults to -O0; `python3 mojo.py build
... -O0` did NOT actually change codegen — confirmed by identical
`nm`-reported addresses/disassembly between a "-O0" and a default build,
so that flag path is untrustworthy for debug builds; built manually via
direct `gcc-mp-15 -fgimple ... -x c mojo.ci ...` instead, mirroring
`stage2/mojo`'s recipe exactly). Breakpoints on the compiler's own
compiled functions (`_declare_var`, `_quick_type`, even their
`GimpleGen__*` trampolines) never fired despite the bug clearly
occurring — root cause never found; abandoned that angle.

Root-caused via shim-side instrumentation instead (a `_sce_simple_emit`
monkeypatch printing a traceback whenever the R2 chokepoint's container-
kind check is about to fire, run via `python3 mojo.py <file>
--dump-full` — safe since it's the shim, not self-hosted source). This
reproduces `myinterpreter.py`'s `from_base` bug family AND revealed it's
actually two independent, real logic bugs in the compiler itself (not
self-host-only — the shim hits them too when compiling the compiler's
OWN source as a target, e.g. `python3 mojo.py gimple_module_gen.py
--dump-full`):

**Bug A (FIXED)** — `gimple_gen_methods.py`'s `_lower_method_call`: when
a method receiver's static type is unresolved (opaque `int64_t`, e.g. a
`self`/`gen`-typed struct field the self-hosting param-typing pass
hasn't reached), the code guessed the receiver's real type purely from
the METHOD NAME being called. `.update()` is real on BOTH `dict` and
`set` in Python, but the guess unconditionally forced `MojoDict *`
(unlike `.add()`/`.discard()`, correctly routed to `MojoSet *`, or
`.clear()`/`.remove()`, already runtime-dispatched via
`mojo_is_registered_dict`/`_set` per DESIGN.html R5). Concrete trigger:
`gimple_module_gen.py`'s own `self._selfhost_locked_param_types.update(
(...))` — `_selfhost_locked_param_types` is a genuine `set`, so forcing
`MojoDict *` then coercing the tuple-literal argument (materialized as
`MojoList *`) against `MojoDict *` tripped DESIGN.html R2's chokepoint.
Fixed by giving `.update()` on an opaque receiver the same
`mojo_is_registered_set`-gated runtime dispatch as `clear`/`remove`,
with a static short-circuit straight to the set-loop path (no dict
branch emitted at all) when the argument's OWN static type is provably
`MojoList *`/`MojoSet *` — emitting the dict branch's `_coerce_to_type`
unconditionally in THAT case trips the same R2 chokepoint at EMISSION
time regardless of which branch runs at C runtime, since the chokepoint
is a compile-time check on the generated C, not a runtime one.

**Bug B (FIXED)** — `gimple_module_gen.py`'s `_scan_body_for_local_field_
access` (the "phantom scalar field" scanner, used so `getattr`-style
dynamic-looking member access on a struct doesn't silently stub to a
no-op): it walked every `MemberExpr` on an unambiguously-typed local
regardless of whether it was the callee of a `CallExpr` (`obj.method(
...)`, a real method call) or a bare value read, and minted a phantom
`int` field for any name not already a known field AND not in a narrow
builtin-container-method allowlist. A real, custom method
(`DispatchPattern.add_call_site`/`.add_callee` in `gimple_solvers.py`)
fell through this gap. Fixed by checking `target_def.methods` (and one
level of `bases`) for a matching method name before minting a field.

Both verified: `compile_stdlib.py` 664/664 unchanged across all landed
states, `check-linkmode`/`check-selfhost`/`make bootstrap` all green,
and both measurably closed part of the shim-vs-noshim gap on the real
target (`mojo.py --dump-full mojo.py`): first-diff offset moved from
2390 (original) through several intermediate points as each fix
landed, gap size dropped from the original ~5MB down to ~5.8MB... at
one intermediate point it temporarily GREW (noshim > shim) because Bug
A's fix, compiling `myinterpreter.py` cleanly, let the build reach
Bug B's location where it hadn't before — a reminder that gap SIZE
isn't monotonic evidence by itself; always check the first-diff offset
too.

**Bug C (found, NOT fixed — reverted after breaking the build)** — the
remaining divergence after A+B: `mojo.py --dump-full mojo.py` first
differs at offset 19260, noshim ~5.8MB larger. Root cause: `class
GimpleGen` (defined in `gimple_codegen.py`) is registered TWICE into
this compile's shared `struct_field_types['GimpleGen']` — once via a
SYNTHETIC ~40-field stand-in (`_selfhost_gimplegen_stmts`, a frozen
parse used so extracted-helper functions like `_declare_var(gen, ...)`
can type their `gen`/`self` first param as `GimpleGen *` even in a
temp_gen that never sees the real class in its own file's transitive
closure — see `_selfhost_gen_self_param_ctype`'s docstring in
`gimple_gen_funcs.py`), and again by the REAL `class GimpleGen` node
once it's found in SOME temp_gen's own `stmts + imported_stmts`
(`gen_module_impl`'s "yield ownership to the REAL node" block,
`gimple_module_gen.py` ~line 2927). `_struct_name_owner['GimpleGen']`
correctly transfers to the real node, but `struct_field_types[
'GimpleGen']` (the FIELD dict actually used for typedef emission)
is never reset — it keeps whichever fields were populated FIRST,
synthetic-stand-in fields unioned with real ones, in whatever order
self-hosted vs shim happen to process temp_gens (a dict/set-iteration-
order difference between the two, the same recurring bug class as
every other self-host-only divergence in this codebase). Confirmed via
a byte diff: noshim's typedef body for `GimpleGen` includes ~40 extra
synthetic fields (`BUILTIN_VALUE_MAP`, `_KNOWN_SIGS`, `_CALL_RENAMES`,
...) the shim's own struct doesn't carry at this position.

Attempted fix: reset `struct_field_types['GimpleGen'] = {}` at the
ownership-transfer point when the previous owner differs from the real
node, letting the real struct's own field-scan passes repopulate it
fresh. This is WRONG and was reverted: `struct_field_types['GimpleGen']`
is also fed by `_selfhost_scan_gimplegen_extra_fields` (fields ONLY
ever written in extracted-helper files like `gimple_gen_infra.py`, e.g.
`gen._cpp_gen_self_fields = {}`, never in `class GimpleGen`'s own
body since those methods were extracted OUT of the class) — a blind
reset discards those too, and nothing re-populates them from the real
struct's own (helper-file-blind) method scan. Worse: because
`gen_module_impl` runs once per file in the transitive closure and
functions get lowered (their C text finalized) as each file is
processed, resetting this SHARED dict mid-compile invalidates the field
TYPE some already-emitted function used for a value CAST while a
later-emitted function sees the NEW (reset) field type for the same
struct's DECLARATION — a declared-vs-assigned type mismatch. Manually
rebuilding `mojoc` with this change hit exactly that: hard `gcc -fgimple`
errors ("non-trivial conversion in 'var_decl'") for `self->_cpp_gen_
self_fields = _t48;` (an `int64_t` value into a `struct MojoDict *`
field) and several sibling fields. **Reverted** — confirmed the revert
restores byte-for-byte the pre-attempt `gimple_module_gen.py` state and
rebuilds clean.

A correct fix needs the registration to happen EXACTLY ONCE, before any
code referencing a `GimpleGen` field gets emitted for ANY file in the
closure — not as a per-file, re-triggerable check inside
`gen_module_impl`. That's an architectural change (move the real-vs-
synthetic resolution to the same one-time pre-pass that already parses
`_selfhost_gimplegen_stmts`, i.e. `_selfhost_register_gimplegen` in
`gimple_codegen.py`, before `gen_module_impl` ever runs for ANY file),
not a quick patch — left for a future session. Bugs A and B are real,
safe, and landed.

## Finding 4 Bug C — RESOLVED (session 3, commit `585879c`)

Root-caused to a chain of independent self-hosted-only bugs (the
architectural one-time-seed idea from the previous session's note above
turned out to be necessary-but-not-sufficient — it was landed, but the
underlying field-scan was ALSO silently broken several different ways,
each masking the next once the prior one was fixed):

1. **`glob.glob()` returns 0 matches self-hosted, always**, regardless of
   directory correctness — confirmed by hand: `os.listdir(d)` + manual
   `startswith('gimple_')`/`endswith('.py')` filtering found the correct
   17 files in the same directory where `glob.glob(os.path.join(d,
   'gimple_*.py'))` returned empty. `_selfhost_scan_gimplegen_extra_
   fields` (gimple_gen_funcs.py) now scans via `os.listdir()` instead.
2. **Bare `dict = {}` annotations** (no value ctype) on
   `self._selfhost_gimplegen_extra_fields` left the value ctype
   unresolved self-hosted — reads came back as the raw `MojoDict`-value
   pointer bits reinterpreted as `int64_t` (printed as a huge decimal
   like `4374397560`) instead of dereferencing as `char *`. Fixed via
   explicit `dict[str, str]`.
3. **`_selfhost_merge_field`'s upgrade condition excluded `_Bool`** —
   only allowed upgrading a generic `int`/`int64_t` default to a
   POINTER type (`_ct.endswith(' *')`), so a `_Bool` literal seen after
   the default was silently kept at `int64_t`. Fixed to also accept
   `_ct == '_Bool'`.
4. **`gen._selfhost_src_dir` was never threaded through** to the scan,
   so it fell back to `gimple_codegen._SELFHOST_DIR`/`.`/`..`, none of
   which reliably had `gimple_*.py` siblings in the compiled binary's
   process CWD. Fixed by threading it through with the same fallback
   order `_selfhost_load_gimplegen_class` already uses.
5. **The shared `gimple_exprtypes._walk_ast`/`_walk_ast_into` utility
   has a real self-hosted bug**: `isinstance(node, str) or
   isinstance(node, int) or isinstance(node, float) or
   isinstance(node, bool)` evaluates TRUE for essentially every real AST
   dataclass instance self-hosted (confirmed via instrumentation: of
   5457 total `_walk_ast_into` calls compiling `mojo.py` self-hosted,
   5027 were misclassified as scalar leaves and never recursed into;
   the `dataclasses.is_dataclass` branch was reached 0 times). Reordering
   to check `is_dataclass` FIRST fixes the walker correctly — verified
   via a differential node-count check against the shim — but this
   exposed a SEPARATE, well-documented, actively-tracked cost:
   `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`'s
   O(N²) whole-program rescan, previously tolerated (if slow) via
   CPython but genuinely catastrophic self-hosted once the walker
   actually recurses (confirmed: `MOJO_NO_SHIM=1 ./mojoc gimple_gen_
   loops.py --dump-full` alone — unrelated to this scan — grew to 15GB+
   RSS and SIGSEGV'd with the reordered walker; RSS growth measured at
   ~750MB/sec). Fixing `_walk_ast` itself is out of scope here (it would
   require ALSO fixing the O(N²) rescan cost first, per that doc's own
   multi-phase, multi-week history) — **`_walk_ast` was left as-is,
   still broken self-hosted, this bug remains open there**. Instead, a
   NEW dedicated narrow statement-only walker
   (`_selfhost_walk_stmts_for_assign_targets`, gimple_gen_funcs.py) was
   written specifically for GimpleGen's narrow need (`self.x = <literal>`
   assignments are always direct statements, never nested in an
   expression, so only statement-level body-bearing fields — if/while/
   for/try/with/match/comptime — need recursing into, not full generic
   AST traversal), sidestepping the shared utility entirely.
6. **Within that new walker, a boxed self-hosted string field compared
   with `==` failed to match** even when semantically equal:
   `_tgt.obj.name == p0` (both a boxed `MemberExpr.obj.name` AST-field
   read and a `str.lstrip()` result) — confirmed via layered
   instrumentation that EVERY upstream counter (files found, functions
   matched, statements visited, assign-shaped statements found) matched
   the shim exactly, and this ONE comparison was the entire remaining
   divergence at that layer (266 matches expected, 0 found). Fixed via
   `_as_str()` normalization on both sides:
   `_as_str(_tgt.obj.name) == _as_str(p0)`.
7. **`_selfhost_literal_ctype` used `type(_val)` as a dict key** — same
   underlying mechanism as #5's bug (self-hosted `type()` does not
   reliably identify a class the way CPython's real class objects do
   for dict-key purposes). `_SELFHOST_LITERAL_CTM.get(type(_val))`
   returned `None` for the overwhelming majority of values self-hosted
   (confirmed: of 141 literal-typed matches via the shim, only 22
   resolved self-hosted with the dict-lookup form). Rewritten as a
   plain isinstance chain. **This was the fix that actually closed the
   gap** — confirmed via debug counters matching the shim exactly
   (`total-fields=88`, all 5 spot-checked fields with correct types)
   after this specific change and no earlier one.
8. **`mojo.py`'s own `build_executable`/`link_executable` link path was
   missing the 512MB stack-size linker flag** that `driver.py`'s
   link-mode path already has (`otool -l mojoc` showed `stacksize 0`
   instead of `536870912`) — an unrelated infra gap discovered while
   investigating #5's crash, fixed for parity regardless of whether
   `_walk_ast` itself ever gets fixed (an 8MB default stack is
   marginal for this compiler's own deeply-recursive regex engine and
   AST walkers even without `_walk_ast`'s bug).

Verified via layered instrumentation at every stage (file discovery →
function matching → statement traversal → assignment-target matching →
literal-type inference → field storage), comparing self-hosted counters
against the shim's after each fix, since several of these bugs
completely MASKED the next one downstream (e.g. fixing #1-4 moved the
count from 247/259 fields to 266/292 but NOT further, because #5-7 were
still silently eating almost every match). Full gate green: check-
linkmode (3/3), check-selfhost, from-scratch stdlib dylib rebuild (0
skips), compile_stdlib.py (664/664, 0 unexpected), make bootstrap
(180/180 files match across 3 stages). Landed in commit `585879c`.

### A separate bug found and fixed in the same session: bytes-literal concat non-determinism

While re-verifying the full `mojo.py --dump-full` comparison after the
above, found `test_noshim_dumpfull.py` still failing — but for a
DIFFERENT reason, confirmed unrelated to Bug C: `mojo_bytes_from_cstr
(<huge decimal number>)` calls appearing in the generated C for any
`bytes_literal + x.encode()`-shaped expression (concrete repro:
`b'\0missing:' + name.encode()` in `cas.py`), where the number is a
raw heap memory address — non-deterministic run to run (confirmed: two
consecutive self-hosted runs of the identical binary on the identical
input produced two DIFFERENT addresses at this exact call site, while
the shim consistently produced the correct `mojo_bytes_from_cstr
(_t4)` symbolic reference both times).

Root cause: `_as_bytes`, a nested closure inside `_lower_binary_tail`'s
MojoBytes-concat handling (`gimple_gen_exprs.py`, `op == '+' and (lt ==
'MojoBytes *') != (rt == 'MojoBytes *')` branch), had unannotated
`ct`/`cv` parameters. Matches this codebase's established "hoisted/
nested closures need explicit param annotations self-hosted or they
misbehave" pattern (see the `--dump-full-determinism-progress` memory's
own GOTCHA note) — without an explicit `str` annotation, `cv` (a
proper `_tNN` variable-reference string, e.g. from a stubbed
`.encode()` call) got boxed and read back as its raw pointer bits when
interpolated into the f-string building the call expression. Fixed via
explicit `def _as_bytes(ct: str, cv: str):`. Confirmed deterministic
across 3+ repeated runs after the fix, and confirmed the shim was
already correct throughout (this bug never affected the shim's own
output). Landed in the same commit (`585879c`).

## Finding 5 — struct EMISSION ORDER divergence (found, NOT fixed, session 3)

With Bug C's field CONTENT now correct and the bytes-literal bug fixed,
`test_noshim_dumpfull.py` still fails — the first differing byte moved
from deep inside the (now-correct) `GimpleGen` field list to its
POSITION in the file: self-hosted emits `typedef struct GimpleGen`
immediately after `typedef struct Generator`, while the shim emits
`typedef struct GlobalStmt` at that same position (i.e. `GimpleGen`
appears somewhere else in the shim's output — content matches, only
ORDER differs). Total diff is still ~1.4M lines (`diff` counts every
downstream line as different once ANY earlier struct reorders, even
though most of the actual STRUCT CONTENT is byte-identical — this is a
"cascading reorder" diff shape, not a content-corruption one).

**Investigated further, hypothesis DISPROVEN**: the obvious first
suspect — `track_best` (a plain dict in `gen_module_impl`'s
`emit_struct_defs` block, ~gimple_module_gen.py:7897, whose
`.values()` iteration order was assumed to drive final struct emission
order) — was instrumented directly (log struct name + a 0-based
sequence number for its first ~180 entries, gated behind
`MOJO_ORDER_DEBUG`, compared self-hosted vs shim). Result: **the
sequences are IDENTICAL** — all 179 unique struct names, including
`Generator` at position 112, `GlobalStmt` at 129, and `GimpleGen` at
178 (dead last), matched EXACTLY between self-hosted and the shim, in
both a fresh rebuild and a repeat run. Yet the byte-level `.ci`
comparison, run immediately after with the SAME binary, still showed
the identical positional divergence (`GimpleGen` right after
`Generator` self-hosted, `GlobalStmt` there in the shim) — and `grep
-c` confirmed each struct's typedef appears exactly once in each
output (no duplicate-emission explanation either).

**Conclusion: `track_best`'s loop is NOT what controls final struct
position in the output for structs like these.** Rereading the
surrounding code, this loop is gated by `if sd.name not in
self._emitted_structs:` — meaning it is a "catch anything not already
emitted" fallback/dedup pass, not the primary emission path. The
actual likely mechanism (not yet confirmed, just inferred from the
codebase's overall shape): `mojo.py`'s transitive closure is compiled
FILE BY FILE (`_compile_imported_module`, once per module), and each
file's own compile likely emits ITS OWN locally-first-seen struct
typedefs into that file's C-code fragment as they're encountered,
with the FINAL `.ci` being a concatenation of per-file fragments in
FILE COMPILE ORDER — so a struct's position in the final output is
really a question of WHICH FILE first referenced it, and WHEN that
file got compiled relative to others, not of any single dict's
iteration order. This is structurally a different (and deeper)
question than every previous finding in this doc — those were all
"one function's own local dict/set iterates differently self-hosted
vs shim"; this one is "the ORDER FILES GET COMPILED differs
self-hosted vs shim", which could stem from import-graph traversal
order, `self._module_stmts`/`self._compiled_modules` iteration
somewhere, or something else entirely in the do_imports driver loop.

**Second hypothesis tested, ALSO disproven**: instrumented
`_compile_imported_module` (gimple_gen_resolve.py) to log `module_name`
as each module starts compiling, gated behind `MOJO_ORDER_DEBUG`
(first attempt used `gimple_ctypes.os.environ.get(...)` and silently
produced zero output self-hosted — a real, separate self-hosted
reliability wrinkle in accessing `os` via a re-exported module
attribute rather than a direct `import os`; switching to the file's
own already-present `import os` and calling `os.environ.get(...)`
directly fixed the debug output itself). Result: **the full 280-entry
module-compile sequence is IDENTICAL self-hosted vs shim**, confirmed
via a complete `diff` (not just eyeballing the first N lines) — same
280 modules, same order, from `build_config` first through to the
last. So module-compile order is NOT the mechanism either.

**Status at end of session 3: both obvious iteration-order hypotheses
eliminated, true mechanism still unknown.** Two independent, cleanly
disproven candidates:
1. `track_best`'s dict iteration order within one module's own
   struct-emission pass — matched exactly, byte output still diverged.
2. Module compile order itself (which module's
   `_compile_imported_module` call happens when) — matched exactly
   (all 280 entries), byte output still diverges at the same position
   (first differing byte ~19215, `GimpleGen` right after `Generator`
   self-hosted vs `GlobalStmt` there in the shim).

**Next steps for a future session**: given both "when does X get
iterated/visited" hypotheses are eliminated, the remaining candidate
is HOW the already-correctly-ordered pieces get assembled into the
final text — i.e. look at the actual STRING CONCATENATION / list-
building logic (`parts.append(...)`/`parts.extend(...)`-style
assembly, or wherever per-module C-code fragments get joined into the
final `.ci` text) rather than any iteration-order question. It's also
worth directly checking whether `Generator`'s and `GimpleGen`'s
STRUCTS are even coming from the same emission pass in both
self-hosted and shim at all — the `track_best`/`emit_struct_defs`
block investigated here might simply not be the site responsible for
this specific pair (recall gimple_module_gen.py has at least 10
separate `typedef struct` emission call sites — `_stub_guard_name`
call sites at lines ~4078, 4084, 5228, 6769, 6863, 6960, 7950, 8115,
8153 hint at several distinct struct-stub-emission code paths beyond
the one instrumented here). A more direct approach: add a one-off
`print`/log statement immediately before EVERY `parts.append(f"typedef
struct {X} {{"` call site (there are ~10), each tagged with its own
site identifier, then compare self-hosted vs shim to see WHICH site
actually emits `Generator`/`GimpleGen`/`GlobalStmt` — this was not
attempted this session and is the recommended starting point.

## Finding 5 UPDATE — root cause actually found (same session, continued)

Finding 5's text-assembly-vs-iteration-order question above turned out
to be moot: continued digging (comparing the FULL, still-extracted
`GimpleGen` struct body from a real end-to-end compile, not just the
scan function's return value in isolation) showed the struct's field
CONTENT itself was STILL wrong for ~19 fields, despite the struct's
total field COUNT matching (292=292). This directly explains Finding
5 too: the topological struct-emission sort (gen_module_impl,
~gimple_module_gen.py:6933-6962 — NOT the `track_best` loop
instrumented above, which really is just a fallback/dedup pass) orders
structs by resolved field-type DEPENDENCIES; a GimpleGen with fewer
correctly-typed struct-pointer fields has fewer dependency edges and
becomes topologically "ready" in an earlier pass self-hosted than the
shim's correctly-typed version. Finding 5 is NOT a separate bug — it
is a symptom of Bug C being incompletely fixed. `track_best`'s
iteration order and module-compile order were both real, correctly-
eliminated hypotheses; they just weren't where the actual remaining
corruption lived.

Tracing why the struct content was still wrong found the SAME field-
type-inference machinery already fixed for the extracted-helper scan
(`_selfhost_scan_gimplegen_extra_fields`, in `585879c`) had an
UNFIXED sibling: `_selfhost_gimplegen_field_types`'s own class-body/
`__init__`/method scan (used for `self.X = <literal>` writes inside
`class GimpleGen`'s OWN methods, as opposed to the extracted-helper
files) still called `gimple_exprtypes._walk_ast(_m.body)` directly —
the exact same broken shared utility, just not yet worked around here.
Three real fixes landed for this (commit `dba69b8`, see that commit
message for full detail): a dedicated walker replacing `_walk_ast`
(mirroring the sibling scan's fix), `TernaryExpr` handling in
`_selfhost_literal_ctype` (a real gap independent of the walker issue
— `gen.field = X if cond else Y` shaped RHS values were never
literal-inferable at all, in either the shim or self-hosted), and a
positional workaround for `__init__` lookup after discovering `.name`
reads on `FunctionDef` nodes from this object graph are corrupted
self-hosted.

That last discovery — `.name` corruption — turned out to be the tip of
something bigger: `.type_ann` reads on `AssignStmt` nodes from the
SAME object graph are ALSO corrupted self-hosted (confirmed by hand:
`isinstance(getattr(_n, 'type_ann', None), str)` evaluates `False`
self-hosted for an assignment the shim correctly reads as the string
`"DispatchSolver | None"`). This is NOT the same `_as_str()`-shaped
bug as everywhere else in this doc — `_as_str()` recovers a boxed
STRING value; here the value isn't even TYPED as a string self-hosted,
it's outright wrong/garbage at the attribute-read level. This affects
the smaller remaining set of GimpleGen fields whose correct type comes
from an explicit annotation on the assignment itself (`self.X: T = ...`)
rather than `__init__` parameter passthrough (`_dispatch_solver`,
`_cpp_gen_self_struct`, `_cpp_last_tuple_slot_ctypes`, and similar) —
NOT fixed, and is now the actual, precisely-isolated remaining blocker
for `make check-noshim-dumpfull` (diff 1,419,444 lines, first
differing byte still ~19215 — same GimpleGen-struct-position symptom).

**What makes this different from every other bug in this doc**: every
previous self-hosted-only bug found across this whole investigation
(here and in the sibling `--dump-full-determinism-progress` /
`selfhost-shimless-progress` memories) has been a *comparison* or
*key-typing* problem — a boxed value compared/used-as-key without
`_as_str()`, a `type(x)`-keyed dict losing fidelity, an isinstance
check misclassifying a dataclass instance as a scalar. All of those
are fixable by normalizing HOW an already-correctly-typed value gets
used. This one is different: the underlying attribute READ itself
(`.name` on a `FunctionDef`, `.type_ann` on an `AssignStmt`) returns
wrong data self-hosted, with no normalization able to recover it,
specific to objects built by `_selfhost_load_gimplegen_class`'s
runtime meta-reparse of `gimple_codegen.py` (invoking the self-hosted-
compiled `Parser` as a library call at RUNTIME, not through the
ordinary compile-then-immediately-consume flow every other AST node in
this codebase goes through). A `FunctionDef`/`AssignStmt` built the
ORDINARY way (parsed once, consumed during that same compile) has
never shown this symptom anywhere else in this codebase's history.

**Recommended next steps for a future dedicated session** (this is
likely a substantial, Bug-C-sized undertaking in its own right, not a
quick patch):
1. Confirm the SCOPE: write a minimal self-hosted repro that parses a
   tiny class via `Parser(...).parse_module()` at runtime (mimicking
   `_selfhost_load_gimplegen_class`'s exact call shape) and reads
   `.name`/`.type_ann` off its methods/assignments immediately — does
   the corruption reproduce on a MUCH smaller object graph, or is it
   specific to `class GimpleGen`'s real size/complexity (4000+ lines,
   363 methods)? This determines whether the bug is about runtime
   re-parsing in general or something size/complexity-dependent (e.g.
   a GC/memory-pressure interaction, or an internal object-pool/arena
   reuse bug that only manifests past some object count).
2. If it reproduces small: this is a general, `_selfhost_load_
   gimplegen_class`-independent bug in the self-hosted runtime's
   dataclass-field-read path for RUNTIME-CONSTRUCTED (not compile-time)
   AST objects specifically — worth searching the runtime C sources
   (`runtime/mojo_runtime.c`) for whatever backs dataclass field access
   (`_mojo_dispatch_getattr` and friends, mentioned in several comments
   throughout this codebase) to understand why object PROVENANCE
   (parsed live at runtime vs. parsed during the normal compile pass)
   would matter to that dispatch at all — it shouldn't, structurally,
   unless something about `_SELFHOST_GG_CACHE`'s caching, or the
   isolation between the "outer" self-hosted process and objects it
   constructs mid-run, is involved.
3. If it does NOT reproduce small: narrow by binary-searching how much
   of `class GimpleGen` needs to be included in the re-parsed source
   before `.name`/`.type_ann` corruption appears, to find the actual
   trigger (a specific field count, method count, or file size
   threshold).
4. Once root-caused, re-verify ALL of this session's `_as_str()`-based
   fixes are still needed/correct — some of the earlier `_as_str()`
   "fixes" in this exact investigation may have been treating a
   SYMPTOM of this same deeper corruption rather than the classic
   boxed-string-as-dict-key issue; they were verified safe and net-
   positive via the full gate either way, but the ROOT explanation for
   a few of them may need revising once this is understood.

## Finding 5 UPDATE 2 — minimal repro built, precise diagnosis (same session, continued further)

Step 1 of the plan above was carried out: built a minimal in-process
repro (parse a TINY 5-line, 2-method synthetic class via the exact
same call shape as `_selfhost_load_gimplegen_class` —
`ast_rewriter.rewrite(Parser(py_tokenize(src)).with_filename(...)
.parse_module())` — inline inside `_selfhost_register_gimplegen`,
gated behind a debug env var so it runs as part of the real self-
hosted `mojoc` binary rather than needing a separate standalone test
program, since standalone-binary attempts (`mojoc build` on a small
test file importing `mojo_compiler`/`ast_rewriter`) hit at least three
DIFFERENT unrelated pre-existing self-hosted bugs unrelated to this
investigation — a `'mo' undeclared` gcc error compiling `build`'s
do_imports path, corrupted `--dump-full` output requiring
`MOJO_NO_SHIM` for self-referential compiles specifically (not
relevant to an arbitrary test file, but the corruption appeared
anyway), and a duplicate-declaration gcc error
(`Parser__parse_expr` re-declared) with `#line` markers pointing at
plain comment text. None of these three were investigated further —
each is its own separate, real, pre-existing self-hosted bug outside
this investigation's scope; noted here only so a future session
doesn't waste a cycle rediscovering them via the same approach).

**Result: the corruption reproduces at tiny scale — NOT size/
complexity-dependent as originally hypothesized.** On the 2-method
synthetic class:
- `.name` on both `FunctionDef` methods read CORRECTLY self-hosted
  (`method_name=[__init__]`, `method_name=[bar]`, matching the shim
  exactly) — contradicting the earlier finding that `.name` was
  corrupted on GimpleGen's real 363-method class. This means the
  EARLIER `.name` corruption was itself likely size/count-dependent
  (or a different, as-yet-unidentified trigger specific to GimpleGen's
  real scale) — the positional-lookup workaround already landed for it
  remains valid and necessary regardless, since it fixed real, verified
  behavior on the actual GimpleGen class.
- `.target.member` on the `AssignStmt` nodes ALSO read CORRECTLY
  self-hosted (`target_member=[x]`, `target_member=[y]`, matching the
  shim) — confirming the `AssignStmt` NODE ITSELF is otherwise intact,
  correctly constructed, and its OTHER fields are readable.
- `.type_ann` specifically reads as **neither a string NOR `None`**
  self-hosted (`is_str=False`, `is_none=False`) — ruling out "the
  self-hosted Parser simply never populates `type_ann` for this
  syntax shape" (a parsing omission would show `is_none=True`). The
  field WAS set to something; reading it back gives a value that is
  neither the correct `char *` string nor a legitimate `None` — this
  is the exact "a value's real bits get reinterpreted as the wrong
  ctype" symptom that has recurred constantly throughout this entire
  investigation (and the broader codebase — see the `_lower_
  StringLiteral` docstring's own historical note about the identical
  symptom for boxed string literals), just now happening on the
  self-hosted COMPILER'S OWN core `AssignStmt.type_ann` field rather
  than a user-level GimpleGen field.

**Refined diagnosis**: this now looks like a `struct_field_types`-
style ctype-INFERENCE problem for `AssignStmt.type_ann` itself (a
core, built-in AST node class from `mojo_compiler.py`, not a
GimpleGen-specific field) — most likely, the self-hosted compiler's
own field-type inference for `type_ann` (presumably an untyped/
`object`-annotated dataclass field in `mojo_compiler.py`, since it can
legitimately hold either `str` or `None`) resolves to a DIFFERENT
ctype (`int64_t` instead of `char *`) depending on the CALL CONTEXT
that constructs the `AssignStmt` instance — normal top-level parsing
apparently infers it correctly (used successfully thousands of times
elsewhere in this same self-hosted binary's own compile of itself),
but construction via this specific NESTED runtime `Parser(...)`
invocation does not. This reframes the bug from "attribute reads are
generally unreliable on runtime-reparsed objects" (the earlier, more
alarming hypothesis) to something narrower and more actionable: a
field-ctype-inference gap specific to how `mojo_compiler.py`'s OWN
`AssignStmt.type_ann` field gets typed when instances originate from
a nested/runtime parse call rather than the top-level one.

**Recommended next steps for a future session** (revised from the
plan above, now that a working, cheap, in-process repro exists — no
need for the standalone-binary approach and its unrelated blockers):
1. Extend the SAME inline mini-repro technique (parse a tiny synthetic
   source string via `Parser(...).parse_module()` inside any already-
   working self-hosted-compiled function, gated behind a debug env
   var, write results to a file) to test OTHER core AST node fields
   similarly typed `object`/optional in `mojo_compiler.py` — does
   `AssignStmt.value`, `FunctionDef.return_type`, or other similarly-
   shaped fields show the SAME corruption when constructed via a
   nested runtime parse, or is `type_ann` specifically affected? This
   determines whether the bug is about the `type_ann` field
   specifically or a broader class of optional/union-typed fields.
2. Compare: does calling `Parser(...).parse_module()` from a
   DIFFERENT nesting context (e.g. directly from `main()`/top-level,
   vs. from deep inside `_selfhost_register_gimplegen`'s own call
   stack) change the result? If nesting depth/call-stack-shape matters,
   that points toward a codegen bug in how struct_field_types gets
   seeded/scoped per call site rather than a single global bug.
3. Search `gimple_codegen.py`/`gimple_module_gen.py` for wherever
   `type_ann` (as a `mojo_compiler.AssignStmt`/`VarDecl` field name)
   gets its ctype inferred in `struct_field_types['AssignStmt']` — is
   there a SEPARATE/duplicate registration path for core AST classes
   (as opposed to GimpleGen) that could explain a call-site-dependent
   ctype? This is architecturally the closest analogue to everything
   else this whole investigation has been about, just for a built-in
   AST class instead of a user-defined one.

## Finding 5 UPDATE 3 — reentrancy/nesting-depth hypothesis tested and ELIMINATED

Recommended step 2 from "Finding 5 UPDATE 2" above was carried out:
does the `.type_ann` corruption depend on HOW DEEP the nested
`Parser(...).parse_module()` call sits within an already-executing
compile? Moved the identical mini-repro (tiny synthetic class, same
call shape) from deep inside `_selfhost_register_gimplegen` (called
partway through `gen_module`, well after the outer compile's own
parse/tokenize/codegen work is underway) to the very FIRST line of
`_run_pipeline` itself — literally before the outer file's own
`tokens = py_tokenize(mojo_src)` / `Parser(tokens)...` call, as
shallow/early as any nested nested nested invocation could possibly
be within a real self-hosted compile.

**Result: corruption reproduces identically at both nesting
depths/timings.** `is_str=False`, `is_none=False` at the "early"
position too — exactly the same symptom as the "deep" position. This
RULES OUT reentrancy/call-stack-depth as the trigger; whatever a
"nested"/"secondary" `Parser(...).parse_module()` invocation is doing
wrong, it's wrong from the very first opportunity, not something that
accumulates or gets triggered by stack depth or by how much of the
outer compile's own state has already been touched.

**Refined framing** (supersedes "Finding 5 UPDATE 2"'s "call-context-
dependent" language, which implied nesting/timing mattered — it
doesn't): the bug is simply that ANY `Parser(...).parse_module()`
invocation OTHER than `_run_pipeline`'s own single canonical call for
the outer file produces an `AssignStmt` whose `.type_ann` reads
wrong self-hosted — regardless of when in the process that second
invocation happens. This is architecturally close to "the compiled
binary's `Parser`/tokenizer/AST-rewrite machinery only works
correctly the ONE time `_run_pipeline` itself calls it" — worth
testing directly in a future session: does a **third** invocation (two
nested calls in a row, not just one) behave the same way, or does it
get progressively worse/different? Does the SAME symptom appear for a
`VarDecl`'s `type_ann` (constructed at a different call site,
`mojo_compiler.py:2293`/`2459`/`4444`) or is it specifically tied to
`AssignStmt`'s construction site (`mojo_compiler.py:2280`)? These two
checks would help decide between "any second invocation of Parser
breaks" (a single, central culprit) vs. "type_ann specifically is
broken on ANY AssignStmt regardless of which Parser call created it,
including the outer one, and the outer one only 'looks fine' because
nothing downstream in the REAL compile of mojo.py ever critically
depends on the correctness of the SPECIFIC handful of `AssignStmt`
nodes whose `.type_ann` would have been wrong" (a MUCH bigger, harder-
to-see bug that's been silently present all along, just never load-
bearing until this investigation's synthetic tests started actually
reading `.type_ann` back and checking it).

## Followups (not fixed this session, worth a future audit)

- **The `.name`/`.type_ann` attribute-read corruption on objects from
  `_selfhost_load_gimplegen_class`'s runtime meta-reparse is now THE
  PRIORITY ITEM** for a future session — see the "Finding 5 UPDATE"
  section immediately above for full detail and recommended next
  steps. This is a genuinely new class of self-hosted bug (attribute-
  read corruption, not a comparison/key-typing issue) that may affect
  other runtime-meta-reparse patterns in the codebase beyond this one
  GimpleGen use case.
- **`type(x)`-keyed dict/cache lookups are a confirmed-unreliable
  self-hosted pattern**, found independently in TWO places this session
  (`_WALK_FIELD_NAMES_CACHE` in gimple_exprtypes.py, and
  `_selfhost_literal_ctype`'s old form in gimple_gen_funcs.py) — both
  silently returned wrong/`None` results self-hosted despite working
  perfectly via the shim. `_WALK_FIELD_NAMES_CACHE`'s own fix
  (`type(node).__name__` as the key instead of `type(node)`) is landed
  and safe, but `_selfhost_literal_ctype`'s fix went further (a full
  isinstance chain, no dict lookup at all) since even `.__name__` felt
  like an unnecessary residual risk once the pattern was this
  precedented. Worth a codebase-wide `grep -n '\.get(type('` (and
  similar `[type(...)]` dict-subscript patterns) audit for other
  instances — each one is a silent, hard-to-detect self-hosted-only
  correctness bug that a shim-only test suite will never catch.
- **Unannotated closures with string parameters are a confirmed-risky
  self-hosted pattern**, found again this session (`_as_bytes` in
  gimple_gen_exprs.py) on top of the pre-existing GOTCHA already noted
  in the `--dump-full-determinism-progress` memory (hoisted closures
  needing explicit dict/set param annotations). Worth a broader audit
  for other unannotated nested-function/closure definitions handling
  string-typed values self-hosted.
- Finding 5 (struct emission order) above remains fully open — the
  `track_best` dict-order hypothesis was tested and DISPROVEN this
  session; the real mechanism is believed to be per-FILE compile
  order (which module gets compiled when), not any single dict's
  iteration order within one module's own struct-emission pass.

## Session 4 final summary (2026-09-14)

Continuing directly from session 3's Bug C work (`585879c`/`dba69b8`) and
the Finding 5 investigative arc (`89d4d7d` through `fbf73dc`). Landed
seven independent, gate-verified fixes (three commits: `5cc83e5`,
`078c103`, `972850f`), each confirmed via `make check-selfhost` at
minimum, several via the FULL gate (check-linkmode, check-selfhost,
compile_stdlib.py 664/664 0 unexpected, make bootstrap 180/180). Diff
narrowed from ~3.8MB (session start) to ~350KB (session end) — real,
substantial, verified progress — but check-noshim-dumpfull is **not
yet zero**.

### The seven fixes

1. **`AssignStmt`/`VarDecl.type_ann` ambiguous-boxed-`int64_t` isinstance
   bug** (`gimple_gen_funcs.py`'s `_selfhost_ann_ctype`, plus two sibling
   `f.type_ann` call sites). Root cause: these fields are hardcoded
   ambiguous `int64_t` in `gimple_module_gen.py`'s `struct_field_types`
   (`struct_boxed_fields`), and `mojo_isinstance`/`mojo_isinstance_p`
   (`runtime/mojo_runtime.c`) never implement `type_id 4` (str) for an
   ambiguous boxed value — they unconditionally return 0. So
   `isinstance(x, str)` was FALSE self-hosted for every real string
   value in that field, not just malformed ones — this was the actual
   mechanism behind the whole "Finding 5" `.type_ann` corruption saga
   documented earlier in this file. Fixed via `is None` + `_as_str()`
   cast instead of `isinstance`.
2. **Hardcoded `_SELFHOST_DIR` path-identity comparisons.** New
   `gimple_codegen._is_selfhost_source_dir()` helper (later relocated,
   see #6) replacing `_cur_abs == _SELFHOST_DIR` (or `.startswith`)
   checks in `gimple_module_gen.py` with a path-independent "does
   `mojo_compiler.py` sit next to this file" signal (mirroring
   `_run_pipeline`'s own `_selfhost_register_gimplegen` gate). Found via
   a REAL downstream project: `/Users/mrs/net/gcc/gcc/fire`, a GCC
   frontend vendoring a byte-identical copy of this compiler at a
   different filesystem path, failed with 9944 gcc errors (`implicit
   declaration of function 'GimpleGen__new_val'` etc. — `gen` params
   boxed to generic `int64_t` instead of `GimpleGen *`) because
   `_SELFHOST_DIR` is hardcoded to wherever `gimple_codegen.py` was
   loaded from, silently disabling self-hosting-only typing for any
   OTHER, otherwise-identical checkout.
3. **Qualifier early-override bug.** `_func_qualifier`/
   `_struct_method_qualifier` (`gimple_gen_funcs.py`) had an early
   `if self-hosting file: return ''` short-circuit that unconditionally
   bare-ified EVERY reference made from a self-hosting-flagged file —
   including genuine references to a DIFFERENT, non-self-hosting
   submodule (fire's own `jit/arm64.py`, one directory below its
   sibling `mojo_compiler.py`). Removed; a no-op for genuine self-
   hosting-internal references (the existing tier 1-3 priority
   resolution already finds nothing for those, falling through to the
   same trailing `return ''`).
4. **GimpleGen-specific qualifier exemption.** Removing #3 broke
   `make check-selfhost` (undefined symbols `_GimpleGen__overload_
   suffix`/`_GimpleGen_overload_suffix_for`): GimpleGen has one real
   home file (`gimple_codegen.py`, correctly resolved via
   `_local_struct_names` there) but is ALSO synthetically registered
   for every OTHER `gimple_*.py` file's compile — those files have no
   import-registry entry for it and fell through to bare, a mismatch
   against the qualified definition. Added back a narrow, name-based
   exemption (`if struct_name == 'GimpleGen': return ''`) mirroring the
   pre-existing `Span` exemption right above it.
5. **Qualified-call convention bug.** `gimple_codegen._is_selfhost_
   source_dir(...)` (a qualified `module.function()` CALL, as opposed
   to a plain attribute read like `gimple_codegen._SELFHOST_DIR`) hit a
   self-hosted-only "stubbed" no-op fallback — confirmed via the
   generated `.ci` showing `/* int64_t._is_selfhost_source_dir()
   stubbed */`, the receiver erased to ambiguous `int64_t`. This
   codebase's established, working convention for cross-file function
   calls is always `from module import name` + bare call; fixed
   accordingly (temporarily — see #6).
6. **Broken cross-module `_parsed_import` resolution for
   `gimple_codegen` specifically.** Even the bare-import fix (#5) hit
   ANOTHER self-hosted-only stub ("unavailable in compiled mode
   (imported from an unresolved external/relative module)"). Root-
   caused via a debug diagnostic: `_local_sibling_module_exports`'s
   `gen._parsed_import('gimple_codegen')` itself returns a falsy path
   self-hosted (confirmed: `ENTER module=gimple_codegen path=0`), even
   though the shim resolves the exact same import fine. Every OTHER
   name gimple_module_gen.py imports from gimple_codegen.py on the same
   import line survives because it resolves via one of two unrelated
   mechanisms that never touch this broken path (a struct/class type,
   or a `gen`/`self`-first-param "extracted helper" already covered by
   the separate, independently-working `_selfhost_extracted_fn_index`
   mechanism) — `_is_selfhost_source_dir` was the only plain utility
   function actually depending on it. Rather than chase the deeper
   `_parsed_import` bug, relocated the function directly into
   `gimple_module_gen.py` (its only remaining caller), sidestepping the
   cross-module resolution path entirely.
7. **`DispatchSolver` field-corruption special-case.** The last
   remaining wrong field in GimpleGen's self-hosted struct (down from
   ~19 originally, after fix #1): `self._dispatch_solver: DispatchSolver
   | None = None` is the ONLY GimpleGen field annotated with a real
   user-defined struct name in an `X | None` shape (every other such
   field uses a builtin type resolved via a hardcoded lookup table).
   Confirmed via diagnostic that `.type_ann` reads back as genuinely
   corrupted (neither str nor None) specifically for this one
   assignment — an old code comment had already flagged this exact
   field by name. Architecturally different from #1 (the VALUE itself
   is wrong here, not just misclassified by isinstance) — fixed via a
   narrow, name-based hardcode (`if member == '_dispatch_solver':
   ctype = 'DispatchSolver *'`), the same shape of exception as the
   `Span`/`GimpleGen` qualifier special-cases.

### The 8th blocker (not fixed — separate, already-tracked, deferred)

After all seven fixes, the first differing byte moved from ~19260
(GimpleGen's struct position) to 20846 — a DIFFERENT struct,
`LayoutSolver` (`gimple_solvers.py`), missing two fields entirely
(`HEAP`, `STACK` — class-level string constants, `self.HEAP`/
`self.STACK` read inside a method). Root-caused to `gimple_module_gen.
py`'s `_scan_stmt_member_candidates` (~line 3316), the GENERIC pass
that discovers a struct's fields by scanning for `self.X` reads across
ALL structs (not just GimpleGen) — it calls `gimple_exprtypes._walk_
ast` directly, the SAME shared utility already documented in this file
(session 3, Bug C item 5) as having a confirmed, still-unfixed
self-hosted bug (`isinstance(node, str/int/float/bool)` misclassifies
real AST dataclass instances, so the walker barely recurses).

Unlike the seven fixes above, this is **not** a quick, narrow patch:
every other `_walk_ast`-dependent bug fixed so far (in GimpleGen's own
scanners) was worked around with a DEDICATED, narrow, statement-only
walker because the shape needed was simple ("find `self.X = <literal>`
assignment TARGETS"). `_scan_stmt_member_candidates` needs to find
EVERY `MemberExpr` READ anywhere in arbitrarily-nested EXPRESSIONS
across a whole method body — a shape general enough that writing a
correct dedicated walker for it would mean essentially re-implementing
`_walk_ast` itself correctly, which is exactly what session 3 already
found exposes a DIFFERENT, catastrophic O(N²) whole-program rescan cost
(15GB+ RSS growth, SIGSEGV) — see `bugs/hard/PERF_nested_module_
compile_walk_ast_quadratic_rescan.md` for that issue's own multi-phase,
multi-week history. Fixing `_walk_ast` properly requires that
performance issue to be solved first.

**This was not left as a theoretical risk — directly attempted and
tested this session.** Reordered `_walk_ast_into`'s check
(`gimple_exprtypes.py`) so `dataclasses.is_dataclass(node)` runs FIRST,
trusting it exclusively (matching session 3's own prior finding that
this reordering fixes the misclassification). Rebuilt `mojoc` and ran
`MOJO_NO_SHIM=1 ./mojoc gimple_gen_loops.py --dump-full` under careful
RSS monitoring (sampling every 2s) — RSS climbed 5GB → 7GB → 11GB →
14GB+ within about 15 seconds on this SINGLE-FILE compile, before being
killed. This reproduces the exact catastrophic blowup the PERF doc
describes, confirming that the field-name caching optimization already
present in the code (`_WALK_FIELD_NAMES_CACHE`, computed once per class
rather than per node — itself a real, already-landed perf fix,
"Phase 5" per that function's own docstring) does NOT by itself resolve
the underlying O(N²) whole-program rescan cost. The change was cleanly
reverted (`git checkout -- gimple_exprtypes.py`, confirmed zero diff)
and `mojoc` rebuilt from the last committed, known-good state
(`972850f`) before continuing.

**A second, independently-scoped attempt was ALSO tried and ALSO
failed the same way.** Theorizing that the blowup came specifically
from fixing the SHARED `_walk_ast` (multiplying the extra recursion
cost across its dozens of call sites simultaneously), tried a
narrower fix instead: a new, separate sibling function
(`_walk_ast_correct`/`_walk_ast_into_correct` in `gimple_exprtypes.py`,
same corrected check order, left `_walk_ast` itself completely
untouched) used ONLY by `_scan_stmt_member_candidates` — which already
caches its own result by `id(stmt)` in a dict shared across every
nested temp_gen in the whole-program compile
(`self._field_scan_member_cache`), so each distinct statement tree
would be walked with the corrected-but-costlier logic AT MOST ONCE
program-wide, not repeatedly. Built and RSS-monitored the identical
way: `MOJO_NO_SHIM=1 ./mojoc gimple_gen_loops.py --dump-full` — RSS
climbed 5.6GB → 10GB → 11GB → 15GB → 16GB+ within seconds, the exact
same catastrophic pattern, on the exact same single-file test. Killed
immediately, cleanly reverted (`git checkout -- gimple_exprtypes.py
gimple_module_gen.py`, confirmed zero diff via `git status --short`),
`mojoc` rebuilt and stability-verified again.

That a SECOND, differently-scoped implementation (dedicated walker,
single cached caller, only one file even touched by the fix) hits the
identical wall as the first (global reorder of the widely-shared
function) is strong evidence this isn't "many callers each paying a
moderate extra cost" — it's that correctly recursing this self-hosted
AST representation via `is_dataclass`-first ordering, in this codebase,
at all, triggers something closer to true exponential blowup even for
ONE statement tree in ONE file. The most likely mechanism (consistent
with `_walk_ast_into`'s own docstring, which explicitly flags "no
id()-based visited set — id() is unreliable in the compiled runtime"):
the self-hosted AST has genuinely shared/aliased sub-structures
reachable via more than one path, and a naive recursive walk with no
cycle/revisit detection re-walks each shared subtree once per distinct
path to it — which is exactly the shape of bug `bugs/hard/PERF_nested_
module_compile_walk_ast_quadratic_rescan.md` already tracks, just
newly reproduced with concrete, fresh RSS numbers this session rather
than only cited from the earlier session's history.

**UPDATE — the "two attempts both blow up" reading above was itself
partly a false alarm, corrected by a third and fourth attempt.**
A controlled comparison run AFTER the two reverts above — the
UNMODIFIED, already-committed baseline (zero code changes), same exact
command (`MOJO_NO_SHIM=1 ./mojoc gimple_gen_loops.py --dump-full`),
watched patiently instead of killed early — showed the IDENTICAL
climbing-RSS pattern (peaking ~38-40GB) and then completed NORMALLY
with exit 0 in about a minute. That climb is pre-existing, unrelated
behavior of this specific whole-transitive-closure self-hosted
compile (this compiler's own largest files) — not something either
`_walk_ast` fix attempt caused. Both attempts above were killed
partway through their own natural climb on a mistaken assumption of
an unbounded runaway.

Re-tried a third time with an added hard total-node-count safety cap
(on top of the existing depth cap) as an extra precaution — this also
showed the same climbing pattern (since the cap wasn't actually the
relevant variable) and was, in hindsight, ALSO killed prematurely.

Reapplied the SIMPLEST form of the fix a fourth time (the direct
`_walk_ast_into` reorder, no dedicated-walker workaround needed) and
this time let it run to genuine completion rather than killing on a
high-but-still-climbing RSS reading. Result: RSS climbed past the
baseline's own peak — into the 57-62GB range — and the process then
died silently (vanished from `ps`, zero-byte log, no error text),
consistent with a real OS OOM kill this time, not a false alarm.

**This gives a materially more precise diagnosis than "O(N²) blowup,
suspected cycle."** The fix is not wrong in the sense of an infinite
loop or a true graph cycle — `_walk_ast_into`'s depth cap (900) and,
separately, the node-count cap tried in the third attempt, both did
exactly what they were supposed to; the walker terminates. The real
issue: correctly completing this traversal (which the original bug
accidentally prevented, by barely recursing and therefore barely
allocating) requires substantially more REAL, legitimate memory than
the already-heavy broken baseline — and this self-hosted runtime
appears to never free intermediate allocations at all (consistent
with an arena/bump-allocator memory model, common in from-scratch C
runtimes for simplicity and allocation speed, at the cost of retaining
everything until process exit). The baseline's ~38-40GB peak is
already large for compiling one file's transitive closure; a genuinely
complete traversal pushes far enough past it to exceed what was
available on this machine.

Confirmed identical in both the broken and fixed versions (so this is
not something introduced by the fix): worth tracking as its own,
separate, real inefficiency in the self-hosted runtime's memory
management — likely the actual reason this whole class of self-hosted
compile is so memory-hungry in the first place, and a genuine
prerequisite for `_walk_ast`'s bug to be fixable in practice (not just
in principle) without requiring a machine with substantially more RAM
than this one.

**Conclusion**: check-noshim-dumpfull's zero-diff goal was not reached
this session. The `_walk_ast` fix itself was reverted a fourth time
(clean revert confirmed via `git status --short`, mojoc rebuilt and
stability-verified from the last committed state, `c9a0e79`) — not
because it is incorrect, but because completing it correctly currently
requires more real memory than this machine has for this specific
compile, given the self-hosted runtime's apparent never-frees
allocator design. A future session has two viable paths, in order of
likely leverage: (1) address the self-hosted runtime's memory
management (freeing/reusing intermediate allocations, or at least this
specific walker's transient node lists) so the correct traversal fits
in available memory, then reapply this exact, already-written fix; or
(2) run the fix on a machine with substantially more RAM as a stopgap
to unblock check-noshim-dumpfull specifically, while (1) is addressed
separately. No further attempt at THIS specific fix is worth making on
this machine without one of those two prerequisites.

### CORRECTION (session 5, 2026-09-14 later): the "OOM" diagnosis above was wrong — real cause is a NULL-pointer SIGSEGV

The "died silently, consistent with OOM" conclusion above was itself a
misdiagnosis, caused by an investigation artifact: the process had been
launched with explicit shell backgrounding (`(...&)`), which obscured
its real exit code from the calling shell — a silent death with an
empty log looked identical to an OOM kill (SIGKILL/137) from the
outside. Re-running the exact same reproduction command WITHOUT the
extra `&` (still inside the harness's own `run_in_background`, but as
a plain synchronous foreground command) captured the true exit status:
**139 = 128+11 = SIGSEGV**, not SIGKILL. `ulimit -a` showed all
memory-related limits as "unlimited," and no core file was produced in
`/cores/`.

Following `HOW-TO-DEBUG.html`'s methodology, reproduced under lldb with
ASLR disabled:

```
lldb -o "settings set target.disable-aslr true" \
     -o "settings set target.env-vars MOJO_NO_SHIM=1" \
     -o "run gimple_gen_loops.py --dump-full" \
     -o "bt" -o "quit" ./mojoc
```

This gave a clean, reproducible backtrace:

```
* thread #1, stop reason = EXC_BAD_ACCESS (code=1, address=0x0)
  frame #0: libsystem_platform.dylib`_platform_strcmp$VARIANT$Base + 148
  frame #1: mojoc`_dict_lookup(d=<unavailable>, key=0x0) at mojo_runtime.c:2570:13
  frame #2: mojoc`mojo_dict_get_str(d=<unavailable>, key=0x0) at mojo_runtime.c:2592:21
  frame #3: mojoc`gimple_module_gen__gmi_collect_self_assigns_2f4586(...)
      at gimple_module_gen.py:1117:10
  frame #4: mojoc`gimple_module_gen_gen_module_impl_7e9a9f(...) at gimple_module_gen.py:3259:3
  [... nested GimpleGen.gen_module -> _compile_imported_module recursion
   across gimple_solvers, gimple_gen_methods, gimple_gen_exprs,
   gimple_gen_calls, gimple_cpp_core, gimple_cpp_async, gimple_codegen ...]
```

A genuine NULL-pointer dereference, not memory exhaustion — full log
saved at session time in `/tmp/lldb_crash.log` (not committed, local
artifact only).

**Root cause**: `_gmi_collect_self_assigns` (`gimple_module_gen.py`,
function starts at line 1108) computes `_existing_fn_ft =
found.get(fn)` at line 1117 BEFORE checking whether `fn` is `None`.
`fn = _gmi_self_member(node.target)` legitimately returns `None` for
any `AssignStmt` whose target is not a `self.X` attribute (e.g. a
plain local variable assignment) — a completely normal, frequent case.
In CPython, `dict.get(None)` on a dict with no `None` key is a safe
no-op returning `None`. Self-hosted, `mojo_dict_get_str`/`_dict_lookup`
erase a `None` key to a NULL `char *` with no NULL guard, and
`_dict_lookup` unconditionally calls `strcmp(NULL, existing_key)` —
segfaulting the instant it's ever called with a `None` key.

This bug was invisible until now because the `_walk_ast` walker's own
bug (isinstance-before-is_dataclass misclassification, documented
above) meant `_gmi_collect_self_assigns` almost never actually reached
a real `AssignStmt` node at all — the `_walk_ast` reorder fix (still
correct, still not landed — see below) is what let this function
finally see real, non-self assignment targets at scale for the first
time, surfacing this second, independent, previously-dormant bug.

**Fix identified and syntax-tested (not committed as of this
correction)**:

```python
for node in _walk_ast(body):
    if isinstance(node, AssignStmt):
        fn = _gmi_self_member(node.target)
        if fn is None:
            continue
        _existing_fn_ft = found.get(fn)
        if (fn not in found
                or (_existing_fn_ft in ('int', 'int64_t')
                    and _existing_fn_ft is not None)):
            v = node.value
            ...
```

**Status after this correction**: both the `_walk_ast_into` reorder
(`gimple_exprtypes.py`) and this `None`-guard fix (`gimple_module_gen.py`)
were applied TOGETHER and run once: `MOJO_NO_SHIM=1 ./mojoc
gimple_gen_loops.py --dump-full` ran **6 minutes 44 seconds** without
crashing or completing — far longer than any single-fix attempt above
(which either crashed within ~90s-2min, or, for the one successful
unmodified-baseline control run, completed in ~1 minute). This was
killed rather than let run further, and both changes were reverted
(`git checkout -- gimple_exprtypes.py gimple_module_gen.py`, confirmed
clean via `git status --short`), `mojoc` rebuilt from the clean
committed state (`f8ddab4`). Whether that 6:44 run represents a
genuinely correct-but-slow traversal that was about to finish, a
separate still-undiagnosed stall, or the earlier heavy-memory-usage
concern in a different guise, is **not yet known** — this is the
concrete next step for a future session, not "run out of RAM" as
previously concluded. The severe RSS growth documented above may still
be real and separately worth investigating (the "never frees"
arena-allocator observation appears independently confirmed), but it
is no longer believed to be what killed the fourth attempt — that was
SIGSEGV, diagnosed above, in a completely different function
(`_gmi_collect_self_assigns`) than the `_walk_ast` reorder itself.

**Recommended next steps**: (1) re-apply both fixes together again,
this time either running under lldb from the start (so a second crash,
if any, gets an immediate backtrace instead of another silent kill) or
adding progress instrumentation/timeouts to distinguish "still working"
from "stuck"; (2) if it does complete, verify `LayoutSolver`'s
`HEAP`/`STACK` fields are now present and re-run the full
`test_noshim_dumpfull.py` for the true final diff; (3) update this
doc's earlier "OOM" framing (now superseded) once resolved either way.

### FOLLOW-UP (session 5, same day): re-tried properly under lldb — confirms genuine unbounded memory growth, not a hang or a second crash

Re-applied both fixes (the `_walk_ast_into` reorder and the
`_gmi_collect_self_assigns` `fn is None` guard) and reran under lldb
from process launch (`disable-aslr`, `MOJO_NO_SHIM=1`, `run ... bt
quit`), this time to get an immediate backtrace if it crashed again
instead of inferring from exit code. One confound found and fixed
along the way: an earlier, separately-killed `process launch` attempt
had left an ORPHANED duplicate `mojoc` process running unsupervised
(`pkill -f "lldb.*mojoc"` doesn't match a bare `mojoc` command line) —
two ~20-24GB compiles were competing for memory simultaneously for
several minutes, which likely explains the previous attempt's
anomalous 6:44 runtime. Killed the orphan; only the lldb-supervised
process continued.

With only one process running, `mojoc` ran cleanly (no crash, no
deadlock — CPU-bound and progressing) for over 28 minutes, climbing
from the baseline's usual ~5GB start past 58GB RSS, and by the ~30
minute mark `top` showed its total memory footprint at **189GB (147GB
compressed)**, with the system down to under 16MB of free physical
pages. This is unsustainable on a 128GB machine and risks the whole
system, not just this process — killed deliberately (`kill -9`) rather
than let it continue. Memory recovered normally afterward, confirming
this was the `mojoc` process's own footprint, not a separate leak.

**This is a materially different, more precise finding than either
prior conclusion.** It is not the SIGSEGV from the `_gmi_collect_
self_assigns` bug (both fixes were applied; no crash occurred, the
process was killed by hand while still healthy/progressing). It is
also not quite the earlier "died silently ~57-62GB, presumed OOM"
reading either — this run was allowed to continue well past that
point, under direct observation, and kept growing past 189GB total
footprint without dying on its own; it was killed pre-emptively. Both
fixes are very likely functionally CORRECT (no crash, no infinite
loop/hang — genuine forward progress the whole time) — the blocker is
squarely the self-hosted runtime's memory model: completing this one
file's whole-transitive-closure compile with a truly correct AST walk
requires memory in the hundreds-of-GB range, because (as noted above)
nothing is ever freed. This is no longer a "maybe," it's measured.

**Revised conclusion**: fixing `check-noshim-dumpfull`'s remaining gap
via this `_walk_ast` correction is blocked on the self-hosted runtime's
allocator, not on any remaining logic bug in these two fixes. Both
fixes were reverted again (`git checkout -- gimple_exprtypes.py
gimple_module_gen.py`) and `mojoc` rebuilt clean from the last
committed state for safety — running either fix on this machine again
without first addressing the runtime's memory management (freeing/
reusing intermediate allocations, or at minimum giving `_walk_ast`'s
output list a bounded/streaming consumer instead of retaining the full
flattened node list for a whole nested-module compile) is expected to
reproduce the same multi-hundred-GB growth, not a new bug. The actual
fix content (both diffs) is fully preserved in this doc and in
`gimple_module_gen.py:1108`/`gimple_exprtypes.py:34`'s pre-fix code
for a future session to reapply once the memory-model prerequisite is
addressed.
