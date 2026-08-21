# CODEGEN_generator_function: Lib/subprocess.py

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
