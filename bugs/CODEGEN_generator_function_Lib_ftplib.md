# CODEGEN_generator_function: Lib/ftplib.py

## Status (updated 2026-08-24 — `%`-format crash in `mlsd` FIXED; 4 unrelated errors remain, own-.cpp count 5 -> 4)

Re-verified via isolated compile (`GimpleGen(do_imports=False,
relaxed_imports=True)` + `gcc-mp-15`/`g++-mp-15 -fsyntax-only`): `.ci`
side clean. `.cpp` side, `FTP.mlsd`, previously 5 distinct errors, now 4:

**Fixed**: `cmd = "MLSD %s" % path` — the shared coroutine-body `%`-
format crash (see `bugs/CODEGEN_generator_function_Lib_ipaddress.md`'s
matching entry for the fix, `gimple_cpp_core.py`'s new
`_cpp_percent_format`). Confirmed gone from the isolated `.cpp`.

**Still open, 4 distinct, unrelated, all narrow feature gaps in the
coroutine-body expression emitter, none attempted here**:
1. `";".join(facts)` — `.join()` called on a STRING LITERAL (not a
   `MojoList *`/`MojoSet *` local) — `_cpp_expr` has no case for a
   string-literal receiver here (only a container-typed local's
   `.join`-equivalent call shapes are handled elsewhere).
2. `self.retrlines(cmd, lines.append)` — `lines.append` passed as a
   VALUE (a bound-method callback argument), not called — the same
   "compiled callable surface has no first-class value form in this
   scalar body model" class of gap `glob.py`'s doc documents for a
   generator method referenced as a plain value.
3. `facts_found[:-1].split(";")` iterated via `for fact in ...:` —
   `.split()`'s result (from a `mojo_cstr_slice(...)` char* expression)
   used directly as a `for`-loop iterable; no case recognizes a chained
   `.split()` call as a loop iterable here (only a bare declared
   `MojoList *` local is).
4. `fact.partition("=")` unpacked into `key, _, value` — same
   underlying issue as (1)/(3): `facts_found`/`fact`, sourced from an
   unannotated `path`/`facts` `FTP.mlsd(self, path="", facts=[])`
   parameter pair, get mis-typed further downstream (visible upstream
   as `(void)(0.partition(" "))` — `line.rstrip(CRLF).partition(' ')`'s
   LHS resolving to the integer literal `0` instead of a real `char *`)
   — very likely another instance of the already-tracked
   `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
   family (that hard bug's own doc explicitly flags itself as high-risk,
   shared, regression-prone machinery — NOT re-attempted here per this
   session's scope).

Full mandatory gate for the `%`-format fix: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skip lines. Commit `d3154a6`.

`ftplib.py` as a whole still does not build. Doc stays open.


## Status (updated 2026-08-23 — mlsd's body partially improved by shared coroutine-emitter work; remaining blockers enumerated precisely)

Re-triaged the isolated compile (ci_errors=0; cpp_errors=6 → 4 unique,
all inside `_mojogen_FTP_mlsd_impl`). Session progress that helps this
file: `lines = []` (mlsd's accumulator) now lowers to a REAL `MojoList *`
with typed appends instead of an int64_t local holding brace-init garbage
(one error gone), and defaulted-argument calls pad correctly. The four
REMAINING errors are independent, each its own narrow-but-real coroutine-
body expression-emitter gap (none generator-machinery-specific):
1. `";".join(facts)` — a str-LITERAL method call (`.join` on a
   `const char[2]`); the emitter has `.replace()` on char*-typed receivers
   but no join/split/rstrip family on literals.
2. `"MLSD %s" % path` — `%`-format-string on a literal + non-constant RHS
   (the long-standing dynamic-%-format gap, here reached via the .cpp path).
3. `FTP_retrlines(self, cmd, lines.append)` — a bound-method VALUE used as
   a callback argument (`lines.append` read without an immediate call); the
   emitter's bound-method-as-value support covers `self.<method>` and
   struct-pointer locals via `_CPP_CALLABLE_CTYPE`, not container members.
4. `line.rstrip(...)`/`fact.split(";")`/`key.lower()` — str-method calls on
   values whose element type this scalar model can't statically know
   (`line` comes from a list populated only at runtime by the callback in 3).
Each is feature-sized; fixing any one alone leaves mlsd blocked by the
others, so none was attempted piecemeal this pass. Doc kept open.


## Status (updated 2026-08-18 — the `Popen__close_pipe_fds`/`calendar.Month`/`Day` blocker below is FIXED, file still doesn't build for other unrelated reasons)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py`
after `bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_
on_ordinary_code.md` landed its fix (the over-eager "assume all
methods" `getattr(self, x)` dispatch-table fallback is now gated to
only fire when compiling this compiler's own self-hosting source, not
ordinary stdlib files like `subprocess.py`/`calendar.py`). Confirmed:
zero occurrences of `Popen__close_pipe_fds` or `calendar.Month`/`Day`
"undeclared here" errors anywhere in the build log now (grepped for
`-i undeclared` across the full output) — the exact blocker described
below is resolved.

**Still does not build end-to-end**, for other, unrelated,
already-documented-elsewhere reasons: undeclared-identifier errors in
`posixpath.py` (`_varsubb`/`_varsub`), `codecs.py` (`_t3`/`_t5`/`_t6`/
etc.), `inspect.py` (`_mojo_cb_formatannotation_repl`, several `_tNN`
temporaries), `reprlib.py` (`functools__make_key_0c85c9`), and
`functools.py` (`hits`/`misses`). None of these are the dispatch-table
mechanism this doc was blocked on; not investigated further here since
that's out of scope for this specific fix.

## Status (updated 2026-08-10, re-verified — this doc's OWN generator bug is FIXED, file still doesn't build for an unrelated reason)

Re-ran `MOJO_DEBUG=1 python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/ftplib.py` against current master
(fast-forwarded to `9d93746`, which includes this session's earlier
real tuple-valued-`yield` support, commit `a7b71a0`/merge `09008e8`).

**`FTP.mlsd`'s tuple-yield refusal is GONE.** Grepped the full
`MOJO_DEBUG=1` log for every "not eligible for C++ coroutine path" line
naming `mlsd` — zero hits. The tuple-boxing fix (`yield (name, entry)`
now boxes into a real `MojoList *`, same mechanism this session used
to fix `dis.py`/`calendar.py`/etc.) resolves exactly the gap this doc's
2026-08-09 entry (below) diagnosed. This doc's own subject is fixed.

**The file still fails to build overall, but for a completely
different, non-generator reason in a transitively-imported module.**
`ftplib.py` pulls in `ssl.py` (for `FTP_TLS`), which pulls in
`subprocess.py`; the combined-module compile fails with dozens of
`error: 'Popen__close_pipe_fds' undeclared here (not in a function);
did you mean 'subprocess_Popen__close_pipe_fds'?` (and the same shape
for several `calendar.Month`/`calendar.Day` dunder methods) — a real
struct method exists under its MODULE-QUALIFIED C symbol
(`subprocess_Popen__close_pipe_fds`), but a generated dispatch-table
struct-literal initializer references it by its UNQUALIFIED name
(`Popen__close_pipe_fds`), which was never declared.

Root-caused this precisely: it's the SAME already-tracked mechanism as
`bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_on_
ordinary_code.md` (the `DispatchTable`/`_plan_dispatch_tables`
"assume all methods" fallback for an unrecognized `getattr(self, x)`
pattern), just a different symptom of it than that doc's own repro. The
fallback registers callees via `self.struct_methods[stmt.name]
[method.name]` (`gimple_codegen.py:758`), which is populated as the
UNQUALIFIED `f"{stmt.name}_{method.name}"`
(`gimple_codegen.py:756`) — this call-graph/dispatch-table analysis
pass was built before/independently of the module-qualified-C-symbol
scheme (see the "SB-1 mojo_abs symbol-collision fix" work) and was
never updated to match, so any struct this heuristic mis-fires on (any
class with an unrecognized `getattr(self, x)`-shaped method, per that
doc's root-cause writeup) gets a dispatch table full of dangling
unqualified symbol references whenever that struct's real methods
live in a NON-root, imported module (root-module structs' unqualified
and qualified names coincide, masking the bug there).

Not fixed here: out of scope for this doc (it's not a generator bug,
and not even in `ftplib.py` itself), and the existing hard-bug doc
already classifies this whole mechanism as "Moderate risk... any
change here must be verified against `make check-selfhost` FIRST and
foremost" — deserves its own dedicated pass, not a piggyback fix. Left
a matching note on that doc with this new symptom for whoever picks it
up next (module-qualification gap, not the malformed-self-type gap
that doc's `option 3` already fixed).

**This doc could be deleted (its own subject, `mlsd`'s tuple-yield
gap, is fixed) except that `python3 mojo.py build
Lib/ftplib.py` still does not succeed** — keeping it open, re-pointed
at the real current blocker, rather than deleting a doc for a file
that still doesn't build (which would look like false progress to a
future pass grepping `bugs/` for "does ftplib.py build yet").

## Status (updated 2026-08-09, re-verified — reproduces identically)

**STILL FAILING**, re-confirmed against current master (fast-forwarded
to `dd7c7c6`). Identical repro to the 2026-08-07 entry below:

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
[gimple_codegen] generator method FTP.'mlsd' not eligible for C++ coroutine path, falling back to honest refusal: mlsd: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
Error building: cannot compile module: function(s) mlsd (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: tuple-valued `yield`** — the well-known,
already-catalogued C++20-coroutine-promise scope boundary (the promise
only carries a single scalar `int64_t`/`double`/`_Bool`; there is no
representation for a tuple/struct value crossing a suspend point), same
family as `bugs/CODEGEN_generator_function_Lib_dis.md`'s
`_unpack_opargs`/`findlinestarts`/`_find_imports` case. `FTP.mlsd`'s
body does `yield (name, entry)` — a 2-tuple `(str, dict)` — and
`_gen_cpp_generator_unit`'s value-type check only accepts a single
scalar type across every `yield` in the function, so a tuple-yielding
generator is refused outright. Because this is ftplib.py's only
generator and it's module-level-reachable (an `FTP` instance method),
the refusal escalates to a fatal whole-module `RuntimeError` for the
CLI's `mojo.py build` path (the error text's claimed graceful fallback
isn't actually taken for the root file being built).

(Note: the sibling struct-typed-*parameter* refusal this doc's older
entries below cross-reference — `bugs/hard/CODEGEN_generator_struct_
typed_param_refused.md`, task #147 — is now fixed, commit `5d22b29`,
and that doc has since been removed per project convention. That fix
is unrelated to `mlsd`'s failure here, which is about the yielded
VALUE's type, not a parameter's.)

The previously-reported `test.__doc__` "invalid use of void expression"
error (line 926) was real at the time but is no longer what blocks this
file — `mlsd`'s refusal happens first, before that code is ever
reached. Not re-verified whether the `__doc__` issue is separately
fixed or still latent; moot until `mlsd`'s tuple-yield limitation is
addressed.

Not fixed here — this is the same genuine, already-assessed
feature-sized coroutine-codegen scope boundary as task #147
(`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`), which
this session's assignment explicitly holds back from further attempts.
Widening the C++20 coroutine promise type to carry a tuple/struct value
across suspend points (rather than a single scalar) is a real feature,
not a narrow bug fix.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
