# CODEGEN_generator_function: Lib/subprocess.py

## Status (re-verified 2026-08-26, wtOpencode_genlib3): identical single own-source error confirmed

Fresh safety-wrapped `mojo.py build` against current master (f0f6e78):
rc=1, **115** total `error:` lines (down from 124), still EXACTLY ONE
attributed to subprocess.py itself — byte-identical:
`subprocess.py:1731:8: error: assignment to 'int64_t' from 'MojoList *'
makes integer from pointer without a cast` at `with self._
on_error_fd_closer() as err_close_fds:`. Everything in the 2026-08-26
(rest-remainder19c) entry below stands: correct support needs
`@contextlib.contextmanager` semantics over the compiled coroutine API
(resume-to-completion on normal exit + real exception injection
(`gen.throw()`) on exceptional exit so the body's `except:`-cleanup
runs) — a 5th coroutine API entry point + new WithStmt codegen,
feature-sized, deliberately not attempted (a type-only patch would
trade this hard error for silently-skipped fd cleanup on the error
path). Doc stays open.

## Status (re-verified 2026-08-26, worktree fix/rest-remainder19c — ONE real own-source error now present, at the already-documented `with self._on_error_fd_closer() as err_close_fds:` gap; not attempted, genuine feature-sized blocker)

Fresh safety-wrapped `mojo.py build`: rc=1, 124 total `error:` lines,
exactly ONE attributed to `subprocess.py`'s own source (down from many
more transitively-caused errors in unrelated files, which have shrunk
since the last check):

```
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py:1731:8: error: assignment
to 'int64_t' {aka 'long long int'} from 'MojoList *' makes integer from
pointer without a cast [-Wint-conversion]
```

Line 1731 is `with self._on_error_fd_closer() as err_close_fds:` inside
`Popen._get_handles`. This is EXACTLY the already-diagnosed, still-open
gap this doc's 2026-08-20 entry documented in detail: `_gen_stmt_WithStmt`
has no case for a context-manager expression whose lowered type is
`MojoGenerator *` (a compiled generator-method call), so it falls
through to generic `__enter__`/`__exit__` struct-method lookup, finds
neither, and the `as`-bound local (`err_close_fds`) defaults to
`int64_t` instead of the real yielded type (`MojoList *`, from
`_on_error_fd_closer`'s `to_close = []; yield to_close`). Previously
that entry predicted this would show up as either silently wrong
runtime behavior OR a downstream type-mismatch compile error — it is
now confirmed to be the latter, and it is now this file's ONLY own-
source blocker (the transitive cascade elsewhere has shrunk enough that
this is the single remaining thing standing between subprocess.py and
a clean build of its own code).

Re-confirmed the real fix is feature-sized, not narrow: `_on_error_fd_
closer`'s body wraps its `yield to_close` in `try: ... except: <cleanup
using to_close>; raise`, i.e. real `@contextlib.contextmanager`
semantics — on exceptional exit from the `with` block, Python re-enters
the generator via `throw()` so its `except:` clause runs. The compiled
generator coroutine API (`_gen_cpp_generator_unit`'s `_start/_resume/
_value/_destroy` surface) has no exception-injection entry point at
all, so even a narrow fix that correctly types `err_close_fds` as
`MojoList *` and calls `_start`/first `_resume` for entry would still
silently skip the `except:`-block fd-cleanup path on exceptional exit —
a real correctness gap, not just a compile error, so a narrow type-only
patch would trade a hard error for silent wrong behavior on the error
path. Declining to attempt either the narrow mistyped-local patch or
the full feature per campaign guidance (large speculative feature
project, not a bounded bug). Left for whoever picks up real
`@contextlib.contextmanager`-over-generator support (would also fix the
sibling instance this doc's own 2026-08-20 entry left as a "flagged,
not yet a dedicated doc" note).

subprocess.py still does not build end-to-end. Doc stays open.

## Status (re-verified 2026-08-25, wtOpencode_group3): unchanged — zero own-source errors, transitive cascade remains the only blocker

Fresh safety-wrapped `mojo.py build`: rc=1 with **138 total `error:`
lines, ZERO attributed to subprocess.py's own source** (`grep
'subprocess\.py.*error:'` empty). Matches the 2026-08-24 finding
exactly; this session's shared fixes elsewhere (coroutine-body
isinstance semantics, str split-family in generator bodies,
statement-level fnptr-call guard) don't touch and aren't touched by
this file's situation. The file remains blocked purely by the
already-documented transitive cascade in other modules. Doc stays open
per convention; no code change.

## Status (updated 2026-08-24, worktree fix/rest-remainder6 — the `signal.SIGTERM` bug from the entry below is FIXED for real; subprocess.py's own source now contributes ZERO errors)

The entry immediately below this one root-caused `self.send_signal(
signal.SIGTERM)`/`signal.SIGKILL` emitting an invalid `mojo_signal ()`
call, attempted a fix, and reverted it after it regressed 2 of
`test_module_cache.py`'s SB-1 per-scope-import tests. That regression
is now understood and fixed for real: the prior attempt guarded
`_lower_MemberExpr`'s zero-arg-function fallback on plain `gen.
imported_symbols` membership, but `imported_symbols` ALSO holds every
ordinary `from X import name` value/function binding (not just genuine
`import X` namespace markers) — including, critically, `std/gpu/
primitives/id.mojo`'s `block_idx`/`thread_idx` (real zero-arg GPU
accessor functions, pulled into the always-present builtin prelude but
never resolved to a real signature), which register with the EXACT
SAME `{'module': ..., 'return_type': ...}` shape a genuine `signal`-
style namespace marker uses. The broadened guard wrongly excluded the
real `block_idx.x`/`thread_idx.x` GPU-intrinsic accessor shape this
fallback exists for, crashing those 2 SB-1 tests at runtime (`dyld:
symbol not found ... '_block_idx'`) — which is exactly why the first
attempt had to be reverted.

Fixed with a precise discriminator: `gimple_codegen.py` gained a new
`gen._module_alias_names` set, populated ONLY by the two real
`import`-statement registration sites (`_gen_stmt_ImportStmt`, and its
module-level pre-scan mirrors in `gen_module` — one of which is the
`ca242a6` top-level-import-alias fix) plus the `from PKG import
submod`-names-a-real-submodule-file branch of `_gen_stmt_
FromImportStmt` — never by an ordinary `from X import name` value/
function binding, so it has no ambiguity with `block_idx`-style
unresolved imported functions. `_lower_MemberExpr`'s fallback (`gimple_
gen_exprs.py`) now excludes `node.obj.name in gen._module_alias_names`
instead of the broader `imported_symbols` check.

**Verified end-to-end**: a real `python3 mojo.py build .../Lib/
subprocess.py` now attributes **ZERO `error:` lines to subprocess.py's
own source** (132 total build errors remain, all in transitively-
imported files — dominated by `argparse.py` (44) and `_collections_
abc.py` (22), the same already-documented cascade every other doc in
this cluster hits). Isolated repro (`gcc-mp-15 -fgimple -fsyntax-only`)
confirms the `mojo_signal ()`/`unexpected RHS for assignment` errors
are fully gone. Full quality gate: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76 (including all 4 SB-1 per-scope-import
tests, confirming no regression this time), `make check-selfhost`
clean, from-scratch stdlib dylib rebuild 0 skips. Commit `0f6b59e`.

subprocess.py still does not build end-to-end — the file remains
blocked purely by the already-documented transitive cascade
(`argparse.py`/`_collections_abc.py`/...), not by anything of its own.
Doc stays open per this project's convention (only files that 100%
compile clean get removed), but subprocess.py's own real blocker is
now fully resolved.

## Status (updated 2026-08-24, worktree fix/gen-core — the doc's own previously-documented real blocker is now fixed upstream (deleted `bugs/hard/CODEGEN_generator_function_symbol_not_module_qualified.md`); a NEW own-code bug found, root-caused, a fix attempted and REVERTED after it regressed a real test)

`bugs/hard/CODEGEN_generator_function_symbol_not_module_qualified.md`
(this doc's previously-cited real blocker, the threading/os bare-name
generator-symbol collision) is gone from `bugs/` — resolved and deleted
by commit `2c9fe02` ("codegen: module-qualify + cross-module hint
compiled generator symbols"), already on this branch. A fresh full
`python3 mojo.py build .../Lib/subprocess.py` no longer shows that
error at all.

**A different, real own-code bug surfaced in its place**: 3 `error:`
lines now attributed to `subprocess.py` itself, at real in-range lines
(2252, 2257 — the file is 2257 lines): `` implicit declaration of
function 'mojo_signal' `` + `` unexpected RHS for assignment `` on
`Popen.terminate`'s `self.send_signal(signal.SIGTERM)` and
`Popen.kill`'s `self.send_signal(signal.SIGKILL)`.

Root cause: `signal` (the imported module, `subprocess.py:49`'s plain
`import signal`) collides with `signal` the C standard library function
name (`gimple_ctypes._C_RESERVED_FUNCS`) AND, independently, with
`Lib/signal.py`'s own top-level `def signal(signalnum, handler):` — so
`'signal' in gen.func_return_types` is true once `signal.py` is
transitively inlined. `_lower_MemberExpr`'s "zero-arg function used in
member-access context" fallback (`gimple_gen_exprs.py`, the same
fallback the already-fixed `Parameter.ATTR`/`enum.py` "Mechanism 4" bug
in `bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md` guards against for PascalCase imports) has no equivalent
guard for a lowercase MODULE name that happens to also be a real
function name — so `signal.SIGTERM` gets misread as "call the
zero-arg function `signal()`, then read `.SIGTERM` off the result",
emitting the invalid `mojo_signal ()` call.

**A fix was attempted and reverted.** Added a guard excluding
`node.obj.name` from the fallback whenever it's a known module import
(`gen.imported_symbols.get(name, {}).get('module')` truthy) — the same
shape as the existing PascalCase guard, just broadened to real module
markers regardless of case. `test_gimple.py` stayed 252/252, but
`test_module_cache.py` regressed 74/76 (2 new failures, both the SB-1
per-scope-import cross-module miscompile-regression test — "the
compiled binary gets BOTH distinct, correct values ... the shape that
used to silently miscompile"). Investigating why `gen.imported_symbols`
turned out NOT to contain `'signal'` (or even `'os'`/`'sys'`) when
inspected post-hoc after a full `do_imports=True` compile suggests this
dict's state during live `_lower_MemberExpr` calls doesn't match what a
simple membership check assumes — likely bound up with the same
per-lexical-scope import-tracking machinery `test_module_cache.py`'s
SB-1 tests specifically exist to guard (`gimple_solvers.py`'s
`DispatchSolver` / per-scope import resolution). Reverted immediately
(clean revert, `git diff` empty) rather than dig further into this
shared, regression-prone machinery under this session's time budget —
matches this project's own documented precedent (`bugs/hard/
CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md`'s
Mechanism 4 section: an analogous cross-module resolution-ordering fix
passed the full gate clean and still had to be reverted after a
corpus-wide regression). Left as a known, root-caused, NOT-fixed bug —
worth a dedicated, careful pass with the per-scope-import machinery in
view, not a quick follow-up.

subprocess.py still does not build end-to-end (127 total `error:`
lines on a fresh build, dominated by `argparse.py` (44) and
`_collections_abc.py` (22) — the same already-documented transitive
cascade every other doc in this cluster hits). Doc stays open.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — re-verified, unchanged)

Re-verified against current HEAD (post f7cf084/53b1aaa/65706f3) via a real
`python3 mojo.py build .../Lib/subprocess.py`: **0 errors attributed to
subprocess.py's own source**, and no "not eligible" refusal for any of its
generators (`_on_error_fd_closer` included — it compiles through the
coroutine path). The build still fails on the transitively-imported
cascade (`codecs.py`/`argparse.py` dominant this pass). subprocess.py's own
real, already-documented blocker remains `bugs/hard/
CODEGEN_generator_function_symbol_not_module_qualified.md`'s threading/os
bare-name generator-symbol collision, deliberately deferred per that doc.
Classification unchanged: NOT a generator-codegen-cluster failure.

## Status (updated 2026-08-20, later same session — found + fixed the REAL mechanism behind the reported `Popen__on_error_fd_closer` undeclared-symbol error; a third, distinct code path from both entries below)

The 2026-08-20 entry immediately below this one investigated the same
reported error shape and could not reproduce it via a real `mojo.py
build`/absolute-path `compile_to_gimple` call — correctly, as far as it
went. But the report's suggested repro (`compile_to_gimple(...,
filename='subprocess.py')`, a **relative** filename) turned out to be
the accidental key to reproducing it for real: a relative filename
resolves (via `os.path.abspath`) to `<cwd>/subprocess.py`, and running
that repro from this repo's own root makes `_is_selfhost_file` (the
path-based self-hosting gate, `gimple_codegen.py` ~line 33210)
incorrectly evaluate `True` — enabling `DispatchSolver`'s
`allow_assume_all_methods` fallback (meant ONLY for this compiler's own
`Interpreter.execute`-style `getattr(self, f'execute_{...}')` dispatch
idiom) for an ordinary stdlib file it was never meant to fire for. That
mislabeling is itself just a testing artifact (a real `mojo.py build`
or `compile_stdlib.py`-style invocation always passes an absolute path
to the real file location, so `_is_selfhost_file` is correctly `False`
for `subprocess.py` in every real build path — confirmed: an isolated
`compile_to_gimple(..., do_imports=False, filename=<abs path>)` and a
real `python3 mojo.py build .../Lib/subprocess.py` both produce zero
`popen_fds_dispatch`/`on_error_fd_closer`-undeclared output).

**But the underlying codegen gap the mislabeling exposed is real and
distinct from both other entries in this doc**: `DispatchSolver.
_plan_dispatch_tables` (`gimple_codegen.py` ~line 1018), when
`allow_assume_all_methods` fires, sweeps every method of the enclosing
struct (except `__init__`/`execute`) into a planned `FUNC_POINTER`
dispatch-table struct literal — including, in this repro, `Popen.
_on_error_fd_closer`, a real `@contextlib.contextmanager`-decorated
GENERATOR method (subprocess.py:1327). `DispatchTable.emit_table_init`
then unconditionally emits `._on_error_fd_closer = (void (*)(Popen
*self))Popen__on_error_fd_closer,` — a struct-initializer field
referencing the bare, unmangled `Popen__on_error_fd_closer` C symbol as
a function-pointer VALUE. But a generator method's only real emitted
callable surface is its `<base>_start/_resume/_value/_destroy`
coroutine API (`_gen_cpp_generator_unit`); `gen_module`'s Phase 2a
never emits an ordinary `Popen__on_error_fd_closer` C function for it
at all — hence "undeclared here (not in a function)" at `-fgimple`
compile time. This is the SAME root problem as `bugs/CODEGEN_
generator_function_Lib_glob.md`'s Bug 1 (`_lower_bound_method_value`'s
fix for `f = self.gen_method`), but in a DIFFERENT code path: a whole-
program dispatch-table/vtable initializer, not a single bound-method-
value reference site.

**Fix** (`gimple_codegen.py`): `DispatchSolver.__init__` now accepts a
`generator_method_api` dict (the caller passes `GimpleGen`'s own
`self._generator_method_api`, keyed `(struct_name, method_name)` —
reusing the EXACT registry `_lower_bound_method_value` already
consults, per this project's "consolidate duplicates" convention rather
than reimplementing the detection). `_plan_dispatch_tables` now checks,
for each callee about to be added to a planned table, whether
`(owner_struct, method_name) in self.generator_method_api`, and if so
`continue`s past it — dropping just that one callee from the table
(same shape as the existing `_self_type_unresolved: continue` a few
lines below, whose own comment already establishes this pattern is
safe: this whole dispatch-table-inference machinery is a heuristic, and
— confirmed while tracing this — the table it builds is never actually
consulted at any real call site in the compiled output (`self.
_dispatch_tables`/`get_dispatch_tables()` are only read by the typedef-
emission and table-init-emission passes, never by `emit_dispatch_call`
or any call-site lowering), so omitting an entry changes no compiled
program behavior, only the emitted (dead) struct literal's shape.
`self._dispatch_solver = DispatchSolver(...)` (gen_module, ~line 36815)
now passes `generator_method_api=self._generator_method_api` — this
runs well after Milestone C step 3's generator-method-detection pass
(~line 36195-36265), so the registry is fully populated by the time
`DispatchSolver.analyze` runs.

**Verification**:
1. The `filename='subprocess.py'` (relative-path, `_is_selfhost_file`-
   triggering) repro: before the fix, `popen_fds_dispatch_t`'s table
   init referenced the undeclared `Popen__on_error_fd_closer` symbol,
   confirmed via `gcc-mp-15 -fgimple -fsyntax-only` producing the exact
   reported "undeclared here (not in a function)" error. After the fix,
   the field is cleanly absent from both the typedef and the table
   init (both come from the same `DispatchTable.methods`/`struct_
   fields`, populated together by `add_method`) — `gcc-mp-15 -fgimple
   -fsyntax-only` now passes with zero errors.
2. Real corpus: `Lib/subprocess.py` was never blocked by this bug in
   any real build path to begin with (per the entry below); a fresh
   `mojo.py build .../Lib/subprocess.py` continues to fail for its own
   real, already-documented, unrelated reasons (`bugs/hard/CODEGEN_
   generator_function_symbol_not_module_qualified.md`'s `threading.py`
   bare-name `walk` collision) — this fix changes nothing about that
   file's overall build status, as expected.
3. Regression (ordinary, non-generator case of the SAME dispatch-table
   mechanism): constructed a synthetic self-hosted-path repro (a struct
   with two ordinary methods, one generator method, and a `getattr(self,
   method_name)` dispatch method feeding `allow_assume_all_methods`).
   After the fix: the planned table/typedef still correctly includes
   both ordinary methods with their correct signatures; only the
   generator method is dropped; `gcc-mp-15 -fgimple -fsyntax-only`
   passes clean. The ordinary case (this compiler's own real use of
   this mechanism — `Interpreter.execute`'s dispatch idiom in
   `myinterpreter.py`) is unaffected: `Interpreter` has no generator
   methods, so this fix is a no-op for it, and `make check-selfhost`
   stays green.
4. Quality gate: `test_gimple.py` 248/248, `test_module_cache.py`
   76/76, `make check-selfhost` clean, and a from-scratch stdlib dylib
   rebuild produced a byte-identical build log to an unmodified-master
   baseline build (0 `skip <module>:` lines in both, same 160 lines of
   output, `diff` clean) — no regression.

Not deleting this doc — `subprocess.py`'s own real blocker (below,
unaffected by this fix) remains open.

## Status (updated 2026-08-20 — investigated a specifically-reported `Popen__on_error_fd_closer` undeclared-symbol error; could NOT reproduce against current master; found a real, different, related gap instead)

Investigated a reported error of this exact shape (paired with, and
same mechanism class as, the glob.py `select_exists` bug fixed this
same pass — see that doc):
```
subprocess.py:1219:49: error: 'Popen__on_error_fd_closer' undeclared here (not in a function)
```
(line 1219 is, per the report, a suspected stale `#line`-attribution;
the real candidate is `Popen._on_error_fd_closer`, a real
`@contextlib.contextmanager`-decorated generator method defined at
subprocess.py:1327, `with`-invoked at lines 1361/1730.)

**Could not reproduce.** Re-verified against current master (`f0bdc29`)
three ways: (1) isolated `compile_to_gimple(..., do_imports=False)` on
subprocess.py alone; (2) `compile_to_gimple(..., do_imports=True)` (the
full transitive whole-program path) fed through `gcc-mp-15 -fgimple
-fsyntax-only`; (3) a real `python3 mojo.py build
.../Lib/subprocess.py`. None produced any `on_error_fd_closer`-related
error — every occurrence in the build log is either the method's own
`def` line or the `with self._on_error_fd_closer() as err_close_fds:`
call site, both showing only an unrelated `-Wunused-but-set-variable`
warning, never an "undeclared" error. Also confirmed via
`compile_to_gimple` with the same-file transitive closure glob.py pulls
in (subprocess.py IS transitively reachable from glob.py's own import
graph, per this doc's own earlier cross-reference) — still no
`on_error_fd_closer` error anywhere in that build log either. `MOJO_DEBUG=1`
shows zero "not eligible" refusal for `_on_error_fd_closer` — it
compiles cleanly via the C++20-coroutine path.

Traced WHY it doesn't reproduce: `_lower_method_call` (gimple_codegen.py,
~line 12981) already has a dedicated case for exactly this shape —
"compiled generator METHOD on obj's struct type
(`self._generator_method_api`)" — checked BEFORE the ordinary
`StructName_method(...)` mangled-symbol lowering, so
`self._on_error_fd_closer()` (a CALL, unlike glob.py's bare
value-reference `self.select_exists`) already correctly resolves
through `<base>_start(self, args...)` and returns a real
`MojoGenerator *`, never touching the undeclared-symbol code path at
all. This appears to already be a genuine, working fix for the CALLED
case (as opposed to `_lower_bound_method_value`'s VALUE-reference case,
which this pass's glob.py fix addresses separately) — whether it
predates this session or was added earlier in this project's history
wasn't traced further; either way, it is correct and present on current
master.

**A real, different, currently-open gap found while tracing this**:
`_gen_stmt_WithStmt` (the `with` statement's own lowering) has NO
special case for a context-manager expression whose lowered type is
`MojoGenerator *` (i.e., a call to a compiled generator method, exactly
what `self._on_error_fd_closer()` now correctly produces). It falls
through to the generic "look up `__enter__`/`__exit__` on this value's
struct type" logic, finds neither (a `MojoGenerator *` has no `__enter__`
struct method registered anywhere), and silently degrades to a no-op
`/* with: __enter__ (MojoGenerator) */` comment — the `as` alias
(`err_close_fds`) ends up bound to the raw, not-yet-resumed
`MojoGenerator *` coroutine HANDLE itself, not to the value the real
Python generator actually `yield`s (`to_close`, a plain list) the way
`@contextlib.contextmanager` semantics require. This produces silently
WRONG runtime behavior (or a downstream type-mismatch compile error
wherever `err_close_fds` is later used, e.g. `err_close_fds.append(fd)`
at subprocess.py:1305), not the "undeclared symbol" crash originally
reported — so it's a plausible, different mechanism that COULD produce
some other confusing failure in a broader whole-program build, but not
this exact symptom. Correctly supporting `with <call to a generator
method> as x:` needs real `@contextlib.contextmanager` semantics: call
`<base>_start`+`_resume` to get the first yielded value for `x`, and on
scope exit either `_resume` again (normal exit) or inject the pending
exception back into the generator body so its `except:`/`finally:`
cleanup runs (real Python's `gen.throw()` — the coroutine calling
convention documented in `_gen_cpp_generator_unit`'s docstring has no
such "throw" entry point at all, only `_start/_resume/_value/_destroy`).
This is a genuine feature addition (a 5th coroutine API function plus
new `WithStmt` codegen), not a narrow fix — not attempted here, and not
folded into a new bug doc yet since only this one instance has been
traced end-to-end (flagged here for whoever next hits a generator-
method value actually being iterated/consumed through a `with`
statement to fold into a dedicated doc once 2-3 more instances turn
up).

Not deleting this doc — subprocess.py's own real, already-documented
blocker (the `threading.py`-dominated `walk` bare-name generator-symbol
collision, `bugs/hard/CODEGEN_generator_function_symbol_not_module_
qualified.md`) is unaffected by any of the above and remains open; a
fresh `mojo.py build` continues to fail on it, unchanged from the
2026-08-11 entry below.

## Status (updated 2026-08-11, re-verified; unrelated fixes landed this pass, subprocess.py's own blocker unchanged)

Re-verified against current master with a real `mojo.py build` rebuild.
Classification unchanged: **NOT a generator-codegen-cluster failure** —
`subprocess.py`'s one generator (`Popen.__enter__`-adjacent `yield
to_close`) still shows zero signal of any problem, and `subprocess.py`
itself contributes ZERO of the build's errors (confirmed via `grep
'subprocess\.py.*error:'` against a fresh error log — no matches).

Two real, unrelated `gimple_codegen.py` fixes landed in this session's
pass (see `bugs/CODEGEN_generator_function_Lib_symtable.md`/`bugs/
CODEGEN_generator_function_Lib_tarfile.md` for the full writeups — a
per-module-scoped `open(path, mode)` call-dispatch fix, and a `sys.
getfilesystemencoding()`/`sys.getdefaultencoding()` lowering); both are
gated clean (`test_gimple.py` 247/247, `test_module_cache.py` 76/76,
`make check-selfhost` clean, dylib rebuild 0 skips, `compile_stdlib.py`
664/664). Effect on this file: total build error count dropped 488 ->
486 via a fresh rebuild — neither fix targets subprocess.py's own real
blocker.

**subprocess.py's real blocker is unchanged**: the build is still
completely dominated by `Lib/threading.py` (297 of 486 errors — mostly
`'StrEnum_<method>' undeclared here ... did you mean 'enum_StrEnum_
<method>'?`, i.e. an unqualified symbol reference expecting a module-
qualified one, plus a smaller cluster of unrelated parse/struct-access
errors). This is `bugs/hard/CODEGEN_generator_function_symbol_not_
module_qualified.md` — already fully diagnosed (two DIFFERENT generator
functions sharing the bare name `walk`, one in `os.py` one in `threading
.py`, colliding at the C-symbol level once transitively pulled into one
whole-program compile) and DELIBERATELY left unfixed pending a dedicated
session, per that doc's own explicit reasoning: the analogous ordinary-
function fix (`bf96f55`/SB-1) required two follow-up regression fixes to
get right, and this generator-specific variant has additional correctness-
sensitive seams (the `.c`/`.cpp` split, the bare-name-keyed `_generator_
api`/`_supported_generators` dicts) that doc's own "What a real fix
needs" section lays out in detail. Not re-attempted here — this pass's
own investigation (tracing tarfile.py's separate `ENCODING` global-type
collision, see that doc) independently reconfirmed the same underlying
architectural pattern (whole-program-shared, bare-name-keyed lookup
dicts) is the recurring root cause across THREE different codegen
subsystems now (free functions, structs, and — newly confirmed this
pass — module-level globals), reinforcing that doc's own conclusion
that this needs a dedicated, careful session rather than a fix folded
into an unrelated pass.

Not deleting the doc — subprocess.py's full build still fails end-to-
end (only files that 100% compile clean get removed per this project's
convention).

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs, this file included (the 2026-08-06 entry below —
already noted fixed as of 2026-08-07, `bugs/hard/COMPILE_FAIL_module_
toplev_struct_never_fully_defined.md`'s mechanism-1/mechanism-2
fixes). Confirmed via fresh rebuild: zero occurrences now, unaffected
either way. While tracing the mechanism, found+fixed a closely related
residual bug (`_gen_struct_method`/`_gen_lifted_closure` never setting
`self._current_module_ctx`, misrouting a `global`-statement write
inside a class method to the wrong module's struct — see that hard-bug
doc's history and this session's commit) plus a related `_safe_coerce_
emit` `.`-access gap. Effect on this file: total build error count
dropped 487 -> 485 via a fresh rebuild. The `threading.py`-dominated
cluster below is unaffected and remains this file's real blocker.

## Status (updated 2026-08-09)

Re-re-verified against current master (real `mojo.py build` rebuild,
real `gcc-mp-15`/`g++-mp-15` per `build_config.py`). Classification
unchanged: **NOT a generator-codegen-cluster failure.** The
`Popen.__enter__`-adjacent `yield to_close` generator still shows zero
signal of any problem (no "not eligible" refusal, no error attributed
to `subprocess.py` itself — 0 occurrences). Total build errors keep
dropping: 495 now (down from 785, then 720, in the 2026-08-07 pass),
still 100% in transitively-imported files. The dominant cluster has
shifted again — it's now `Lib/threading.py` (297 errors, e.g.
`request for member '__suppress_context__' in something not a
structure or union`, `expected expression before
'_DeleteDummyThreadOnDel'`, several `expected ';', ',' or ')' before
'default'`), not the `argparse.py`/`typing.py`/`enum.py`/`gettext.py`
cluster this doc previously pointed at (that cluster still contributes
45/20/12/6 errors respectively, but is no longer dominant).
`threading.py`'s errors look unrelated to generator codegen (parameter
defaults, exception-attribute struct access, a straightforward
undeclared-symbol parse error) and are not chased down further here —
out of scope for this generator-codegen cluster; see
`bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md` for the still-open part of the previously-identified
cluster. Not deleting the doc since `subprocess.py`'s full build still
fails end-to-end (only files that 100% compile clean get removed per
this project's convention).

## Status (updated 2026-08-07, superseded above)

`bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`'s
`os.py` `'relpath' is ambiguous` follow-up fix landed, clearing the
`_genericpath_toplev`/`_posixpath_toplev` cluster this doc previously
pointed at. Re-running `python3 mojo.py build .../Lib/subprocess.py`
now surfaces a different, much larger cluster (785 errors, dominated by
`Lib/argparse.py`/`Lib/typing.py`/`Lib/enum.py`/`Lib/gettext.py`) — see
`bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md` for the full investigation. Three of that cluster's root
causes were fixed there (785 -> 720 errors); `subprocess.py` itself
still does not fully build — see that doc's "Not fixed" section for
what remains (argparse.py's excluded `**kwargs` bug, a dynamic-%-format
gap already scoped out by design, and an unresolved `weakref.py`
line-attribution + literal-type-name mystery).

## Status (updated 2026-08-06, STALE — see above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `cast from 'Popen*' to 'int'` .cpp error no longer reproduces.
`subprocess.py` has one generator, `Popen.__enter__`-adjacent `yield
to_close` (line 1331) — it does NOT appear in the current error list,
and `MOJO_DEBUG=1` shows no "not eligible" refusal naming it:
subprocess.py's own generator body now appears to compile cleanly
through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Every current error is `bugs/hard/COMPILE_FAIL_module_toplev_struct_
never_fully_defined.md` — an unrelated, non-generator gap where
`genericpath`/`posixpath` module-attribute access
(`genericpath.something`, `os.path.something` resolving through
`posixpath`) hits an incomplete, never-fully-defined opaque struct:

```
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py:615:29: error: invalid use of undefined type 'struct _genericpath_toplev'
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py:1175:28: error: invalid use of undefined type 'struct _posixpath_toplev'
```
Not investigated further here — out of scope for this generator-codegen
cluster; see the hard-bug doc for the shared root-cause writeup (this
file is one of its 4 confirmed occurrences).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/subprocess.py
