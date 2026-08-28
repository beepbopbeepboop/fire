# CODEGEN_generator_function: Lib/symtable.py

## Status (updated 2026-08-26, fresh independent re-derivation — confirmed unchanged)

Re-derived from scratch: isolated `compile_to_gimple_with_cpp(do_imports=
False)` on `Lib/symtable.py` alone compiles clean (its only generator,
`yield flagname`, unaffected — 0 errors attributable to symtable.py's own
source in any pass to date). Same conclusion as every prior pass,
independently re-confirmed: NOT a generator-codegen-cluster failure: the
remaining whole-program-build blocker is the transitively-imported
`argparse.py`/`typing.py`/`enum.py`/`pickle.py`/`_collections_abc.py`/
`traceback.py`/`threading.py` cascade, none of it in symtable.py's own code
and none of it generator-shaped. Genuinely out of scope for this file's own
cluster; not attempted. Doc stays open per convention.

## Status (updated 2026-08-26, worktree agent-ae936147a68675d97 — independently re-derived from scratch)

Re-derived fresh via own isolated `compile_to_gimple_with_cpp(do_imports=
False)` + real `g++ -fsyntax-only`: symtable.py's own generator (`yield
flagname`) compiles clean, 0 `.cpp` errors — confirms symtable.py's own
source remains unaffected. Concur with the already-established
classification: the file's own code is not the blocker; the remaining
failure is entirely the transitive `argparse`/`typing`/`enum`/`pickle`/
`_collections_abc`/`traceback`/`threading` cascade, already reconfirmed
same-day by a parallel session (246 errors, 0 attributable to
symtable.py). No code change made. Doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder17 — re-verified unchanged)

Fresh full `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
symtable.py` against this worktree (branched from master `1e0f3f2`,
`build/libmojostdlib.dylib` freshly rebuilt, 0 skips): 246 `error:`
lines total (previously 245, within normal noise), **0 errors
attributable to symtable.py's own source** (confirmed via `grep
"symtable.py:" ... | grep error:` — zero matches); its own generator
(`yield flagname`) still compiles clean. Dominant clusters unchanged:
`argparse.py`/`typing.py`/`enum.py`/`pickle.py`/`_collections_abc.py`/
`traceback.py`/`threading.py`. This session's own fixes (dynamic
exception-value re-raise; MemberExpr-receiver `.append()`/`.clear()`/
`.add()`) don't touch this cascade. Classification unchanged: NOT a
generator-codegen-cluster failure; doc stays open per convention (only
files that 100% compile clean end-to-end get removed).

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified unchanged)

Fresh re-verify against this worktree (branched from master `f65502d`):
isolated `compile_to_gimple_with_cpp(do_imports=False)` still succeeds
cleanly (its own generator, `yield flagname`, unaffected). A full
`python3 mojo.py build .../Lib/symtable.py`, run under the safety-rule
watcher, still fails 100% inside transitively-imported files (245
`error:` lines; `grep symtable.py ... | grep error:` returns ZERO —
confirmed 0 errors attributable to symtable.py's own source). Dominant
clusters this pass: `argparse.py`/`typing.py`/`enum.py`/`pickle.py`/
`_collections_abc.py`/`traceback.py`/`threading.py` — none
generator-codegen-shaped, none owned by this doc. Classification
unchanged: NOT a generator-codegen-cluster failure; doc stays open per
convention (only files that 100% compile clean end-to-end get removed).

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree: `compile_to_gimple_with_cpp
(do_imports=False)` on symtable.py still succeeds cleanly, its own
generator (`yield flagname`) unaffected. A real full build still fails
100% inside transitively-imported files (dominant: `Lib/enum.py`, 407
errors, tracked separately; plus smaller clusters in argparse.py/
codecs.py/pickle.py/inspect.py/... none inside symtable.py's own source,
none generator-codegen-shaped). Classification unchanged: NOT a
generator-codegen-cluster failure; doc stays open per convention (only
files that 100% compile clean end-to-end get removed).

## Status (updated 2026-08-24, worktree fix/gen-core — re-verified, unchanged; unaffected by this session's fixes)

Re-ran the isolated coroutine-path compile fresh, post-`fd909e9`
("refuse unresolved callees honestly") and post-this-session's own
`6e92df8` (class-body dunder-alias methods) — neither applies to this
file: `compile_to_gimple_with_cpp(do_imports=False)` on symtable.py
still succeeds cleanly (its own generator `yield flagname` unaffected
by either change, unlike `pickletools.py`/`weakref.py`/`tokenize.py` in
this same cluster, which turned out to have been relying on
now-corrected silent-miscompile behavior). Classification unchanged:
NOT a generator-codegen-cluster failure; blocked purely on the
already-documented transitive cascade. Doc stays open per convention.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — re-verified, unchanged)

Re-verified against current HEAD via a real `python3 mojo.py build
.../Lib/symtable.py`: **0 errors attributed to symtable.py's own source**
(both of the 2026-08-11 fixes below still hold; its own generator
`yield flagname` remains clean). The build still fails on the transitive
cascade only — `enum.py`/`codecs.py`/`argparse.py`/`pickle.py`/... this
pass. Classification unchanged: NOT a generator-codegen-cluster failure;
doc stays open per convention.

## Status (updated 2026-08-11, symtable.py's own 2 errors FIXED)

Both of symtable.py's own real errors (the 2026-08-07/09 passes below)
are now fixed via two real, gated fixes in `gimple_codegen.py`:

1. **`open(path, mode)` call-dispatch guard used a whole-program-shared
   `func_return_types` check instead of a per-module-scoped one.**
   `open`'s call-site dispatch (`_lower_named_call`, guarded at what
   used to be `fname_raw == 'open' and 'open' not in self.
   func_return_types`) fell through to the generic `BUILTIN_VALUE_MAP`
   path (`mojo_open_file`, the 1-argument form) whenever `func_return_
   types` — populated by scanning EVERY module in the whole-program
   transitive closure, not just this one — happened to contain an entry
   for the bare name `open`. `Lib/tokenize.py`'s own `def open
   (filename):` (transitively reachable from symtable.py, which imports
   `tokenize`) registers exactly that entry, even though symtable.py
   itself never imports or shadows `open` — so symtable.py's own `with
   open(filename, 'rb') as f:` (line 449) was wrongly routed to the
   1-arg `mojo_open_file`, not the 2-arg-aware `_lower_builtin_open`.
   Fixed by adding `GimpleGen._locally_binds_name(bare_name)`, which
   reuses the SAME three-tier per-module lookup `_func_qualifier`
   already trusts for the analogous free-function-mangling problem
   (this exact module's own top-level defs / its own lexical import-
   scope stack / its own `FromImportStmt` scan — deliberately
   EXCLUDING the whole-program-shared fallback tier), and routing
   `open`'s call-site guard through it instead of the raw global
   `func_return_types` membership check.
2. **`sys.getfilesystemencoding()`/`sys.getdefaultencoding()` had no
   real lowering** and fell through to the fully generic "unknown
   method on scalar receiver" stub, which passes the RECEIVER's
   placeholder type (`int64_t`, since a bare `sys` module reference
   resolves to that) through as the call's OWN result type — silently
   wrong for a call that's supposed to return a string. Added a narrow
   special case (mirroring the existing `sys.platform` comptime-
   constant special case) returning the fixed, faithful `"utf-8"`
   value both calls have on every host this compiler targets. This one
   wasn't needed to fix symtable.py's own two errors, but was found
   and fixed in the same pass — see `bugs/CODEGEN_generator_function_
   Lib_tarfile.md` for the file this was actually needed for (`tarfile.
   py`'s module-level `ENCODING = ... sys.getfilesystemencoding()`).

Verified via a real `python3 mojo.py build .../Lib/symtable.py` rebuild:
both of symtable.py's own errors (`mojo_open_file` arity mismatch at
line 449; the `textwrap.py`-transitive stray-backslash tokenizer issue
previously also attributed here no longer reproduces either — see
below) are GONE. `symtable.py`'s own generator (`yield flagname`, line
302) remains unaffected either way (still compiles cleanly, as every
prior pass already established).

**Not deleting this doc** — `mojo.py build .../Lib/symtable.py` still
exits non-zero end-to-end: the current error set (622 errors) is now
100% attributed to OTHER files transitively imported by symtable.py,
overwhelmingly `Lib/enum.py` (407 errors — see `bugs/CODEGEN_generator_
function_Lib_enum.md`, already tracked separately) plus smaller
clusters in `argparse.py`/`codecs.py`/`pickle.py`/`inspect.py`/
`traceback.py`/`tracemalloc.py`/`posixpath.py`/`typing.py`/`os.py`/
`contextlib.py`/`gettext.py`/`weakref.py`/`functools.py`/`dis.py`/
`tokenize.py`/`threading.py`/`operator.py`/`locale.py`/`copyreg.py` —
none of it inside symtable.py's own source, none of it generator-
codegen-shaped. Per this project's convention ("only files that 100%
compile clean get removed"), the doc stays open, now purely tracking
"symtable.py transitively pulls in other files' independent bugs",
which is out of scope for a dedicated symtable.py-specific fix.

Full mandatory gate run for these two `gimple_codegen.py` changes: `python3
test_gimple.py` 247 passed/0 failed; `python3 test_module_cache.py` 76
passed/0 failed; `make check-selfhost` clean; from-scratch
`libmojostdlib.dylib` rebuild — 0 `skip <module>:` lines; `python3
compile_stdlib.py` — 664/664 passed, 0 unexpected.

## Status (updated 2026-08-09, unchanged)

Re-re-verified against current master (real `mojo.py build` rebuild,
real `gcc-mp-15`/`g++-mp-15` per `build_config.py`). Exact same two
errors as the 2026-08-07 pass, byte-for-byte, confirming this doc is
still accurate and neither has been fixed nor regressed:

```
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:449:10: error: too many arguments to function 'mojo_open_file'; expected 1, have 2
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:576:46: error: stray '\' in program
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:576:47: error: missing terminating ' character
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:576:46: error: expected ';' before '_classattr_TextWrapper__letter'
```

symtable.py's only generator (`yield flagname`, line 302) still shows
zero signal of any problem (no "not eligible" refusal, does not appear
in the error list): **still NOT a generator-codegen-cluster failure.**

Both root causes remain unfixed and are confirmed non-generator,
recurring elsewhere in this same bug-doc family (not narrow, not
attempted here): the `mojo_open_file(char *path)` runtime helper
(`gimple_codegen.py` line ~5590/6505/14846/32669) only models the
1-argument `open(path)` call form — a 2-argument call (`open(path,
mode)`, as used at symtable.py:449) is emitted as a call with an extra
argument gcc then rejects; the same gap is independently hit by
`Lib/mailbox.py`, `Lib/ftplib.py`, and `Lib/gettext.py`'s current
re-diagnoses. The stray-backslash tokenizer issue is transitively from
`textwrap.py` (pulled in via the same import chain) and is
independently hit by `Lib/codecs.py`'s, `Lib/ipaddress.py`'s,
`Lib/weakref.py`'s, `Lib/typing.py`'s, `Lib/tempfile.py`'s, and
`Lib/gettext.py`'s current re-diagnoses — this is clearly a shared,
systemic gap (in the tokenizer's handling of some string-literal shape
in `textwrap.py`), not something to fix narrowly as part of a 3-bug
pass. Not deleting the doc — `symtable.py`'s build still fails
end-to-end.

## Status (updated 2026-08-07, failure point now pinned down)

Re-verified against current master with a real, complete rebuild
(previous pass's "zero hard errors visible" was incomplete triage, not
an actual clean build — the earlier grep evidently missed matches). The
build DOES have real errors, confirming the classification below:
**still NOT a generator-codegen-cluster failure** — symtable.py's only
generator (`yield flagname`, line 302) still shows zero signal of any
problem (no "not eligible" refusal, doesn't appear in the error list).
symtable.py's own 2 real errors:

```
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:449:10: error: too many arguments to function 'mojo_open_file'; expected 1, have 2
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:576:46: error: stray '\' in program
```

Both are already-known, unrelated-to-generators patterns recurring
elsewhere in this cluster this session: the `mojo_open_file` 2-arg-call
arity mismatch (also seen in `Lib/mailbox.py`'s and `Lib/ftplib.py`'s
current re-diagnoses) and the textwrap.py-transitive stray-backslash
tokenizer issue (also seen in `Lib/codecs.py`'s/`Lib/ipaddress.py`'s).
Not investigated further here — out of scope for this cluster.

Also noted in passing (not attributed to symtable.py specifically —
appears in the debug log without a file marker, likely from some OTHER
module in the transitive closure): `MOJO_DEBUG=1` prints occasional
`unknown expression lowered to 0: YieldExpr`/`YieldFromExpr` notes.
Flagged for whoever next investigates a real generator-shape gap to
check whether this indicates an actual silent-miscompile case (a
`yield`/`yield from` appearing somewhere this codegen's expression
lowering doesn't recognize as generator context, e.g. inside a nested
comprehension or lambda) — not chased down further in this pass since
it produced no attributable error for any file examined this session.

## Status (updated 2026-08-06, superseded above — this pass's "zero errors" was incomplete triage)

Re-diagnosed against current master (`2b0c4c5`) — the 2026-07-30
`'flagname' was not declared` .cpp error no longer reproduces.
`symtable.py` has one generator (`yield flagname`, line 302) — it does
NOT appear anywhere in a full `MOJO_DEBUG=1` build log (0 `error:` lines
in the entire ~144K-line output, only warnings; no "not eligible"
refusal naming it either): symtable.py's own generator appears to
compile cleanly through the coroutine path.

`mojo.py build` still exits non-zero, but the failure point wasn't
pinned down in this pass — the gcc/g++ compile stage(s) visible in the
log show zero hard errors, so the actual failure is presumably at a
LATER stage (link, or a companion-.cpp step not captured by this file's
grep-based triage) not yet isolated. This build is also unusually slow
(minutes) — consistent with the already-documented, unrelated
`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
perf issue for files with a moderately large transitive import graph,
not a new finding here.

**Classification: very likely NOT a generator-codegen-cluster failure**
(symtable.py's own generator shows zero signal of any problem), but the
true current failure point needs a cleaner re-run (e.g. capturing the
link step's own stderr separately) to state with full confidence. Left
open rather than marked fixed.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/symtable.py
