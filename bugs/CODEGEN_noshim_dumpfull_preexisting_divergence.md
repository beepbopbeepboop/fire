# CODEGEN_noshim_dumpfull_preexisting_divergence: check-noshim-dumpfull fails on b00955c itself

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

## Followups (not fixed this session, worth a future audit)

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
