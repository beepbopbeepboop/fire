# CODEGEN_generator_function: Lib/test/test_support.py

## Status (updated 2026-08-19)

The 2026-08-09 status below classified this doc's ONE own-file error
(`TESTFN = os_helper.TESTFN`, line 26 — `from test.support import
os_helper` binding a real SUBMODULE FILE, then a module-level global
read off it) as "real, confirmed, but NOT narrow enough to safely fix
in this pass" and flagged it for a dedicated pass. That pass happened.

**Fixed.** `_gen_stmt_FromImportStmt` (gimple_codegen.py) now
distinguishes `from PKG import NAME` where `NAME` is a real submodule
FILE from `NAME` being an ordinary symbol defined inside `PKG`'s own
source (`_from_import_name_is_submodule`, reusing `_parsed_import` and
a new `_submodule_source_path`/`_module_candidate_paths` — the same
search-path resolution `_compile_imported_module` already used, just
factored out so an existence check doesn't need a full compile). When
`NAME` is a submodule, it's registered as a genuine module marker
(mirroring `_gen_stmt_ImportStmt`'s shape) instead of an ordinary
function/class symbol. The identical check was also added to the
TOP-LEVEL "Process imports" pre-pass (`gen_module`'s `_register_sym`
closure and its module-load-failure fallback) — top-level `from X
import Y` statements are skipped entirely by the function-body
statement-lowering path (`gen_module`'s Phase 2a explicitly `pass`es
on `FromImportStmt`), so the fix needed both a function-body-scoped
and a module-scoped registration site. A matching case was added to
`_lower_MemberExpr` (reads the submodule's real global directly via
the existing `_{module}_globals.<field>` struct-field mechanism,
keyed by `_global_to_module`/`_global_var_types` — the same machinery
a bare imported-symbol global read already used) and to BOTH of this
codegen's independent global-type-inference tables (`_phase17_value_
type`, Phase 1.7's pre-scan, and `_gscan_declare_global`, the later
pass that actually emits the struct-field C type and — being later —
would otherwise silently overwrite Phase 1.7's correct inference back
to a bogus default) so `TESTFN`'s OWN declared type resolves to the
real `char *` instead of defaulting to `int64_t` and boxing/unboxing
the pointer incorrectly.

Verified via a real isolated `do_imports=True` build, compiled and
RUN end-to-end (gcc-mp-15, not just `-fsyntax-only`): a package with
`from pkg import submod` then `submod.SOME_VALUE` used inside `main()`
now runs and prints the real value (was previously a NULL-pointer
runtime dispatch). A closer, exact structural mirror of THIS file's
own shape (`from test.support import os_helper` then a MODULE-LEVEL
`X = os_helper.TESTFN` read at top level, matching this doc's own
line-26 repro) also compiles and runs correctly end-to-end, printing
the real string, PROVIDED the outer global's own name doesn't
collide with a same-named global already claimed by a DIFFERENT
transitively-compiled module — see caveat below.

Direct re-verification against the real corpus: a `gcc -fsyntax-only`
pass over this exact file's own `do_imports=True` output no longer
shows ANY error at `test_support.py:26` (or anywhere else in
`test_support.py` itself). The remaining 9 errors are ALL still
inside the separately-tracked, transitively-imported `test/support/`
package (`__init__.py`/`import_helper.py`'s own unrelated bugs) —
exactly the "common cross-file blocker flagged elsewhere" the
2026-08-09 note already carved out as out of scope for this doc.
**This doc's own file-scoped bug is closed; the file as a whole is
still blocked by that separate package's own errors, unrelated to
generators or this fix.**

**One real caveat found and left open (out of scope for this fix,
architecturally separate):** `_global_to_module` is a single,
whole-transitive-closure-shared, first-writer-wins dict keyed by BARE
global name (documented at length at its own declaration) — if the
ROOT module and a transitively-imported submodule both happen to
define a module-level global with the IDENTICAL bare name (which
`TESTFN = os_helper.TESTFN` invites by construction — it deliberately
re-exports the submodule's `TESTFN` under the SAME name), the
submodule's own `TESTFN` claims ownership first (compiled earlier, in
Phase 0), and the root's later same-named global's later BARE reads
(e.g. `print(TESTFN)` elsewhere in the file) can silently resolve to
the wrong module's globals-struct field, or the placeholder. Confirmed
via an exact-name reproduction of this doc's own shape: a bare-name
collision between the root's own `TESTFN` and `os_helper`'s `TESTFN`
reproduces a (different, pre-existing) silent-wrong-value bug
unrelated to the submodule-marker gap this pass fixed — this exists
independent of submodule imports entirely (any two modules with a
same-named global collide the same way) and was NOT introduced by
this fix. Not investigated further here; flagged for a separate, dedicated pass
on `_global_to_module`'s bare-name-only ownership model. This doc's
own real `test_support.py` line 26 itself (`TESTFN = os_helper.
TESTFN`) resolves correctly regardless — that specific read goes
through `_lower_MemberExpr`'s member-access path, which doesn't
depend on `_global_to_module` ownership at all — but the file DOES
also re-read the bare name `TESTFN` later, inside several test
methods (e.g. line 107 `open(TESTFN, ...)`), which WOULD go through
the collision-prone bare-identifier path; not confirmed end-to-end
either way since the file as a whole still can't build far enough to
test this (blocked by the separate `test/support/` package errors
above) — flagged, not verified, for whoever picks up the
`_global_to_module` ownership-model pass.

## Status (updated 2026-08-09)

Re-verified against current master (98e5aa3) with a real `MOJO_DEBUG=1
python3 mojo.py build` rebuild using the real gcc-mp-15/g++-mp-15
toolchain. **Confirmed NOT a generator-codegen-cluster issue.**
`test_support.py`'s own generator (`_caplog`, `@contextlib.contextmanager`
def at line 43, `yield handler` at line 49) shows zero "not eligible"
refusal anywhere in the debug log — it compiles cleanly through the C++
coroutine path (used at 6 call sites, e.g. `with warnings_helper.
check_warnings() as recorder, _caplog() as caplog:`). The previously
documented `MojoGenerator` incomplete-type errors and `component_ref`
non-trivial-conversion errors are BOTH gone (superseded, not
reproducible).

Item 1 (`save_restore_warnings_filters`, the non-plain-assignment-target
hard bug) still reproduces exactly as before — confirmed again via
`MOJO_DEBUG=1` output (`generator 'save_restore_warnings_filters' not
eligible ... only a plain identifier assignment target is supported`).
This function lives in the transitively-imported `Lib/test/support/
warnings_helper.py`, not in `test_support.py` itself. No change to
`bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md`'s
status needed.

**Current build failure (31 errors total) is dominated by the
transitively-imported `test/support/` PACKAGE** (`test/support/
__init__.py`: 7 errors, `os_helper.py`: 21 errors, `import_helper.py`: 1
error) — reached via this file's own `from test import support` / `from
test.support import os_helper` / `import_helper` / `script_helper` /
`socket_helper` / `warnings_helper` lines. This is exactly the common
cross-file blocker flagged elsewhere this session (cascading import-time
errors in that DIFFERENT `Lib/test/support/__init__.py` package, distinct
from this top-level `Lib/test/test_support.py` module) — none of those 29
errors are generator-related and none are this file's own code; not
investigated further here (out of scope for this doc's own file).

**Exactly ONE error is in `test_support.py` itself, and it is real,
root-caused, and NOT generator-related:**
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_support.py:26:24: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes pointer from integer without a cast [-Wint-conversion]
```
Source: `TESTFN = os_helper.TESTFN` (module-level global, initialized
from a cross-module attribute read; `os_helper` is bound via `from
test.support import os_helper`). Traced to the generated `.ci`
(`_t1 = (int64_t)0; /* ct param or undeclared: os_helper */` followed by
a `_mojo_dispatch_getattr` call on that NULL placeholder): `os_helper`
itself never resolves as a recognized module marker at this use site.
Root cause: `_gen_stmt_FromImportStmt` (gimple_codegen.py ~line 20170)
treats every `from X import Y` identically as importing an ordinary
function/class SYMBOL defined in module X (registering `Y` in
`self.imported_symbols` with `{'module': X, 'return_type': ...}`), with
NO disambiguation for the case where `Y` is itself a SUBMODULE of package
X (`from test.support import os_helper`, where `os_helper` names
`test/support/os_helper.py`, not a symbol inside `test/support/
__init__.py`). Because `os_helper` is never registered as a genuine
module marker (the way plain `import os_helper` would via
`_gen_stmt_ImportStmt`'s `_declare_var(local_name, 'int64_t')` + marker
assignment), `_lower_MemberExpr`'s module-attribute-access special cases
(gimple_codegen.py ~8822-8987, all gated on recognizing `module_name` as
a known module/import marker) never match `os_helper.TESTFN`, and
`os_helper` falls through to `_lower_IdentExpr`'s terminal "unknown
identifier" placeholder (`(int64_t)0`) — so `os_helper.TESTFN` becomes a
runtime `_mojo_dispatch_getattr` call on a NULL pointer, force-cast to
`char *` at the store despite the target global's `_quick_type`-inferred
declared field being `int64_t`.

**Classification: real bug, confirmed, but NOT narrow enough to safely
fix in this pass.** `_gen_stmt_FromImportStmt` is shared machinery used
for every `from X import Y` statement in the entire compiler; correctly
distinguishing "Y is a symbol in X" from "Y is a submodule of package X"
needs cross-referencing the whole-transitive-closure module registry
(order-sensitive: has `test.support.os_helper` already been compiled/
registered as its own module by the time this statement is scanned?),
which is a materially bigger and riskier change than a single missing
stub case — exactly the kind of shared-machinery change CLAUDE.md warns
produced past regressions. Only 1 occurrence found in this whole file
(every other `os_helper.foo(...)` / `import_helper.foo(...)` usage in
this file is a CALL, which goes through the separate, already-working
`_lower_call` member-call path, not this one). Not attempted here;
flagged for a dedicated, carefully-scoped pass — genuinely out of scope
for this generator-codegen-focused doc either way (no generator/coroutine
involvement at all).

## Status (updated 2026-08-07, superseded above)

Item 1's hard-bug doc (`bugs/hard/CODEGEN_generator_non_plain_
assignment_target_refused.md`, task #150) is now PARTIALLY fixed —
tuple/list-pattern-unpack targets no longer refuse; non-`self`
attribute-assignment targets still do. Re-running `MOJO_DEBUG=1`
against this file's current source no longer shows the "only a plain
identifier assignment target is supported" message at all (nor any
`save_restore_warnings_filters` mention — that name wasn't found in
this checkout's `Lib/test/test_support.py`, possibly moved/renamed
since this doc's original 2026-08-06 pass, or reached via a different
transitively-imported file not independently re-checked here).

Item 3's hard-bug doc (`bugs/hard/CODEGEN_comprehension_return_type_
defaults_int64.md`, task #145) is fixed in general (`_quick_type`
gained a `Comprehension` case), but a real rebuild confirms this
file's OWN item-3 occurrence is a DIFFERENT, still-open gap — the
`'component_ref'` GIMPLE-node errors at lines 112/159/323/337 are
**still present, unchanged**:
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_support.py:112:1: error: non-trivial conversion in 'component_ref'
/Users/mrs/net/Python-3.14.6/Lib/test/test_support.py:159:1: error: non-trivial conversion in 'component_ref'
/Users/mrs/net/Python-3.14.6/Lib/test/test_support.py:323:1: error: non-trivial conversion in 'component_ref'
/Users/mrs/net/Python-3.14.6/Lib/test/test_support.py:337:1: error: non-trivial conversion in 'component_ref'
```
The original 2026-08-06 note already correctly hedged this as only a
"same general family, different GIMPLE node" match, not a confirmed
instance of task #145's exact `Comprehension`-return shape — that
hedge holds up: whatever produces a `'component_ref'` (rather than
`'integer_cst'`/`'var_decl'`) non-trivial-conversion is a distinct
decl/body type mismatch, not addressed by the `Comprehension` case
added for task #145. Not root-caused further here (out of scope: not
one of this file's own generators either way).

Item 2 (the `MojoGenerator` incomplete-type error, lines 227/300/320)
is unrelated to either bug and still reproduces unchanged; not
re-investigated in this pass.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'LogCaptureHandler' was not declared` .cpp error no longer
reproduces. `test_support.py`'s own generator (`yield handler`, line 49)
does not appear in the current error list.

**Classification: mixed.**
1. `save_restore_warnings_filters`: `bugs/hard/CODEGEN_generator_non_
   plain_assignment_target_refused.md` (5th confirmed occurrence).
2. **New gap, not yet investigated to full root cause:** `error: invalid
   use of incomplete typedef 'MojoGenerator'` at lines 227/300/320,
   paired each time with `error: expected expression before ';' token`
   at the same line — looks like a generator OBJECT (not yet resolved to
   its concrete per-generator type) being used somewhere its type needs
   to be complete (e.g. a variable declared/dereferenced before the
   specific generator's real type is known). Source context at those
   lines didn't show an obvious generator-related expression in a quick
   read — flagged for a closer look rather than fully traced here.
3. The recurring comprehension/`_quick_type`-family "non-trivial
   conversion in 'component_ref'" pattern at lines 112/159/323/337 (a
   variant error message from the same general family documented in
   `bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md`, here
   `'component_ref'` instead of `'integer_cst'`/`'var_decl'` — same
   underlying decl/body type-mismatch shape, different specific GIMPLE
   node).

Not fixed here.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_support.py
