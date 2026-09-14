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
