# COMPILE_FAIL: Mac/BuildScript/build-installer.py

Source file: `/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-08-23): re-verified — STILL-OPEN, byte-identical errors.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`): the same
three diagnostics reproduce unchanged (`build-installer.py:704:17: invalid
operands to binary + (have 'char *' and 'MojoList *')`, and `1447:17`/
`1456:17: invalid operands to binary % (have 'int64_t' and 'MojoDict *')`).
Both root causes below remain structural and unattempted.

## Status (updated 2026-08-09, historical — superseded header only; both root causes now confirmed structural — not fixed)

Re-ran fresh against current master (after merging in the recent
`logging/handlers.py` transitive-closure and other same-day fixes — no
change to this file's outcome). The exact same two errors from the
2026-08-06 note below still reproduce byte-for-byte:

```
$ python3 mojo.py build /Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py
.../build-installer.py:704:17: error: invalid operands to binary + (have 'char *' and 'MojoList *')
.../build-installer.py:1447:17: error: invalid operands to binary % (have 'int64_t' {aka 'long long int'} and 'MojoDict *')
.../build-installer.py:1456:17: error: invalid operands to binary % (have 'int64_t' {aka 'long long int'} and 'MojoDict *')
```

Root-caused both precisely this session (previous note below had only
sketched them). Both are genuinely structural/systemic — not attempted,
per this project's documented history of narrow-looking fixes to shared
global/local type-inference machinery causing broad silent regressions
across the 664-file stdlib corpus (see CLAUDE.md's quality-gate section
and `bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_bare_
annotation.md`'s own "Risk" section, which flags this exact `gen_module`
Phase 1.7 pass as having "already produced one real regression-shaped
scare earlier this session").

### Root cause 1 (line 704): global reassigned to a structurally
different type inside a function, module-scope initial value never
reconciled

`Mac/BuildScript/build-installer.py:112`:
```python
FW_VERSION_PREFIX = "--undefined--" # initialized in parseOptions
```
is a module-level `StringLiteral` — `gen_module`'s Phase 1.7 global
pre-scan (`gimple_codegen.py`, `_phase17_infer_global_type` /
`_gscan_declare_global`) types `FW_VERSION_PREFIX` as `char *` purely
from this one assignment. Inside `parseOptions()` (line 637), after a
`global FW_VERSION_PREFIX` declaration, line 703 reassigns it to a real
LIST value: `FW_VERSION_PREFIX = FW_PREFIX[:] + ["Versions",
getVersion()]`. Neither Phase 1.7 nor the struct-field-declaration pass
(`_gscan_declare_global`) scans function bodies for `global`-declared
reassignments at all — both only ever walk top-level module statements
(by design; see `_gscan_declare_global`'s own doc comment on why
`imported_stmts` is deliberately excluded from that scan). So
`_global_var_types['FW_VERSION_PREFIX']` stays `char *` forever, and the
VERY NEXT LINE (704), `FW_SSL_DIRECTORY = FW_VERSION_PREFIX[:] +
["etc", "openssl"]`, reads `FW_VERSION_PREFIX` back with the stale
`char *` type: `[:]` lowers as a STRING slice (producing another `char
*`), then `+` between that and a list literal (`MojoList *`) is invalid
C — exactly the reported error, one line downstream of the actual
mistyped write.

A real fix would need to extend the SAME Phase 1.7 pre-scan machinery
that already required two previous incident-driven fixes this session
(the `IfStmt`-flattening fix, commit `fd29316`, and the `TryStmt`-join
fix, part of the "all three parts fixed" work in
`bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_bare_annotation.md`)
to ALSO descend into every function body, find `global X` declarations,
locate every reassignment to `X` within that function, and
`TypeLattice.join` those types against whatever the module-level scan
found — mirroring the TryStmt-branch-join logic already added, but for
a structurally different scope (cross-function, not cross-branch) and
needing new bookkeeping for `global`-statement discovery that doesn't
exist anywhere in Phase 1.7 today. Doable in principle, but it directly
widens the exact pass CLAUDE.md's quality gate section and the sibling
hard-bug doc both call out as high-risk, evidenced by requiring the
full 5-part gate (`test_gimple.py`, `test_module_cache.py`,
`check-selfhost`, from-scratch stdlib dylib rebuild, `compile_stdlib.py
-j8` 664/664) to be genuinely trustworthy — not attempted in this
session given the file has a SECOND, independent structural gap (below)
that would still leave it broken even with this one fixed.

### Root cause 2 (lines 1447/1456): dict-keyed (`%(name)s`) runtime
`%`-string-formatting is an unimplemented feature, not a type-inference
bug

`packageFromRecipe()` (line 1427):
```python
readme = textwrap.dedent(recipe['readme'])   # line 1437
...
textvars = dict(VER=getVersion(), FULLVER=getFullVersion())  # line 1443
readme = readme % textvars                    # line 1447
...
srcdir = os.path.join(WORKDIR, '_root', srcdir[1:])  # line 1455
srcdir = srcdir % textvars                     # line 1456
```
Several `recipe['readme']` values earlier in the file (e.g. lines
424/434/449/462/473/491) are literal triple-quoted strings containing
`%(VER)s`/`%(FULLVER)s`-style DICT-keyed format specifiers (Python's
`"...%(name)s..." % {...}` idiom), not the positional `%s`/tuple form.

Two compounding problems, confirmed by reading `gimple_codegen.py`'s
`_lower_percent`/`_lower_percent_format` (~line 10239) and the generic
`_quick_type` fallback (~line 7023):

1. **`_lower_percent` only special-cases a LITERAL format string
   (`isinstance(node.left, StringLiteral)`)** — by the time execution
   reaches `readme % textvars`, `readme` is a plain `IdentExpr` (a
   variable whose value happens to have originated, several statements
   earlier, from a string literal via `recipe['readme']` →
   `textwrap.dedent(...)`), not a `StringLiteral` AST node. There is no
   data-flow/constant-propagation in this codegen that could recover
   "this variable's value is known at compile time to be this literal
   template" across an intervening dict-index + function call. So the
   dict-keyed-format special case never fires for this shape at all —
   it can only ever work for `"literal %(x)s" % some_dict` written
   in-line as one expression, a narrower case than real Python supports
   and than this file actually uses.
2. **Even granting a genuinely dynamic (non-compile-time-known) format
   string, this codebase has NO runtime `%`-format implementation at
   all** — `_lower_percent_format`'s existing machinery parses the
   format text at COMPILE TIME (splitting literal/`%spec` parts,
   emitting per-part `sprintf`/`mojo_str_cat` calls) and only supports
   POSITIONAL args (a tuple or single RHS value), never named/dict
   lookups. Supporting `fmt % {dict}` in general — where `fmt` is only
   known at runtime — needs a genuinely new C runtime primitive (e.g. a
   `mojo_str_format_dict(char *fmt, MojoDict *vals)` that parses
   `%(key)conv` specs and `%conv` specs against a `MojoDict *` AT
   RUNTIME) that doesn't exist anywhere in `runtime/*.c` today. That's
   a new feature, not a missing branch in an existing dispatcher.

Separately (visible in the error text but not the blocking issue): `lt`
for `readme`/`srcdir` reports as `int64_t`, not even `char *` — both are
function-LOCAL variables whose declared type comes from
`textwrap.dedent(...)`'s and `os.path.join(...)`'s return values, and
neither is in the small hardcoded stdlib-function return-type tables
`_quick_type`'s `CallExpr`/`MemberExpr` branches consult, so both fall
through to the universal "unknown call return type" `int64_t` default —
the SAME pervasive, foundational fallback used for every unresolved
call across the whole compiler (not specific to this file). Adding
table entries for `textwrap.dedent`/`os.path.join` would fix the
reported type in isolation, but does nothing for root cause 2 above
(the actual blocker) since even a correctly-typed `char *` LHS still
has no code path to reach a dynamic, dict-keyed `%`-format at runtime.

### Why not fixed here

Both gaps are structural: (1) widens the Phase 1.7 global-type-inference
pass that has already caused two real regressions this session and is
explicitly flagged as high-risk by both CLAUDE.md and a sibling
`bugs/hard/` doc; (2) requires designing and implementing a new runtime
string-formatting primitive (dict-keyed `%`-format against a dynamic
template) that doesn't exist in this codebase in any form yet — a real
feature addition, not a stub/branch fix. Per this session's guidance,
leaving both documented here rather than forcing either through.

## Status (updated 2026-08-06, historical — superseded by the more precise write-up above)

Re-ran; current errors, two distinct root causes:

```
error: invalid operands to binary + (have 'char *' and 'MojoList *')
error: invalid operands to binary % (have 'int64_t' and 'MojoDict *')  (x2)
```

1. `FW_VERSION_PREFIX = "--undefined--"` at module scope (a STRING
   placeholder, "initialized in parseOptions" per its own comment),
   later reassigned inside a function to a real LIST value:
   `FW_VERSION_PREFIX = FW_PREFIX[:] + ["Versions", getVersion()]`.
   `gen_module`'s Phase 1.7 global prescan types a global from
   whichever assignment it encounters (here: the module-level
   `StringLiteral` → `char *`), with no reconciliation for a LATER
   reassignment to a structurally different type inside a function —
   a placeholder-then-real-type-reassignment idiom, related to (but a
   distinct trigger shape from) `bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_bare_annotation.md`
   and `bugs/hard/CODEGEN_reset_func_wipes_global_container_type_inference.md`
   (both already document other Phase-1.7-adjacent global-typing gaps
   found this session).

2. `readme = readme % textvars` / `srcdir = srcdir % textvars` — old-
   style `"..." % {dict}` string formatting where the LHS `readme`/
   `srcdir` (both function parameters, presumably `str`) resolve to
   `int64_t` instead of `char *`, and `%` against a `MojoDict *` RHS
   isn't specially handled at all (the `%` operator lowering likely
   only recognizes tuple-style `%` formatting, not dict-style). Not
   investigated further.

Neither fixed here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
   90 |     if _cache_getVersion is None:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:95:11: warning: unused variable '_tag' [-Wunused-variable]
   95 | def getVersionMajorMinor():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:110:11: warning: unused variable '_tag' [-Wunused-variable]
  110 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:119:13: warning: unused variable '_tag' [-Wunused-variable]
  119 | # else if you don't want to re-fetch required libraries every time.
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'shellQuote_0c85c9':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:694:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  694 |         else:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:692:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  692 |                 raise NotImplementedError(v)
      |          ^  
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:688:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  688 |                     # Select alternate default deployment
      |          ^  
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'grepValue_d01dc0':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:88:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   88 | def getVersion():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:76:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   76 |     QUOTED_VALUE='quotes'    -> str('quotes')
      |          ^~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'getFullVersion':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:112:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  112 | FW_VERSION_PREFIX = "--undefined--" # initialized in parseOptions
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py: In function 'tweak_tcl_build_1ce6ce':
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:280:11: warning: variable '_t62' set but not used [-Wunused-but-set-variable]
  280 |               buildDir="unix",
      |           ^   
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:276:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
  276 |           dict(
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py:268:7: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
... (1375 more lines)
```

Exit code: 1
Elapsed: 13.33s
