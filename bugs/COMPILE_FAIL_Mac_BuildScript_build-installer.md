# COMPILE_FAIL: Mac/BuildScript/build-installer.py

## Status 2026-10-01 — root cause 1 only, unchanged; the accumulated re-verification history is gone

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py`
on this tree: **exit 1, exactly one own-file error**, byte-identical to every
prior measurement:

```
build-installer.py:704:17: error: invalid operands to binary + (have 'char *' and 'MojoList *')
```

Root cause 2 (dict-keyed `%`-format) stays fixed. Root cause 1 — Phase 1.7's
global pre-scan being blind to a cross-function `global` reassignment — is
unchanged, and the 2026-09-27 entry below still has the best analysis of it,
including the three re-derivation sites and why an implementation was
rejected. **Read that entry rather than re-deriving it.**

The eight "re-verified, byte-identical, unchanged, no code change" entries
that used to sit above it have been removed: they cost a future session real
time to re-read and change nothing, which is exactly what CLAUDE.md says a
`bugs/` entry should stop being.

### One correction to that entry, from measuring it again

It records that a guard placed in `_gscan_declare_global` was measured to be a
no-op because `gname` is already in `_declared_globals` by then, and that
`global_decls` "is not emitted at all", and it concludes the real field
emitter is still unidentified. The site IS identifiable now, and it is not
`_gscan_declare_global`:

`_declared_globals` feeds the field-freeze loop at `module_gen.py`'s
`for gname in sorted(_declared_globals):`, whose `_own_t =
self._own_overlay_global_ctype(gname)` is the authoritative resolution — the
same `_own_overlay_global_ctype` the assignment sites use through
`_global_dst_ctype`. Its result is appended as the `(name, ctype, mtype)`
triple in `self._module_globals[current_mod_name]`, and THAT list is what
`_mg_list`/`globals_struct_lines` turns into the actual
`typedef struct _root_toplev { ... }` text (`  {_ct} {_c_field_name(_gn)};`).

So the reconciliation does not need a fourth site: there are two, this one and
`_gscan_declare_global`, and they must agree because both already route
through `_own_overlay_global_ctype`. `_own_global_var_types` is the overlay
`_own_overlay_global_ctype` reads, which is why the rejected attempt's
`_phase17_scan_global_reassignments` pass was the right shape and the wrong
place to put the conclusion.

## Status (2026-09-27 — root cause 1 re-derived in detail and an implementation ATTEMPTED AND REJECTED; the doc's own diagnosis is confirmed correct, and the blocker is now narrower than "high-risk shared machinery")

The doc's analysis below is **confirmed accurate**, re-measured on this tree.
`python3 fire.py build /Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py`
still produces **exactly one** own-file error, byte-identical to every prior
re-verification:

```
build-installer.py:704:17: error: invalid operands to binary +
                             (have 'char *' and 'MojoList *')
```

No code change is landed. An implementation was written, measured, and
**deliberately reverted** — the reasoning is recorded here because it is the
expensive part and the next session should not re-derive it.

### What was confirmed

The two-pass structure the doc describes is real and both halves were found:

1. **Phase 1.7's global pre-scan** (`_phase17_infer_global_type` /
   `_gscan_declare_global`, both in `mojo/backend_gimple/module_gen.py`)
   walks TOP-LEVEL module statements only. `FW_VERSION_PREFIX` is therefore
   typed `char *` from its module-level `"--undefined--"` sentinel
   (`:112`) forever, and the reassignment at `:703` inside `parseOptions()`
   (which declares `global FW_VERSION_PREFIX` at `:643`) is invisible to it.
2. **`_phase17_value_type`, the pure RHS-type table Phase 1.7 shares with
   its branch-join scanners, has no `BinaryOp` row at all.** The `:703` RHS
   is `FW_PREFIX[:] + ["Versions", getVersion()]` — a `BinaryOp('+')` whose
   left operand `_quick_type`s to `int64_t` (a slice of an untyped global)
   and right to `MojoList *`. With no row, it fell to the generic fallback
   and returned `int64_t`, so the table reports NO container evidence even
   once the function bodies are scanned. This is a second, independent
   prerequisite the doc did not name: **scanning function bodies is not
   sufficient on its own.**

### Why the attempt was rejected

The first working version (a `_phase17_scan_global_reassignments` pass
joining each `global`-declared name's body-assignment types against the
module-level type, plus the `BinaryOp '+'` row) DID make `fire.py build`
succeed with zero errors. It was then rejected for two measured reasons:

- **The inline path never agreed.** `--dump-full` (do_imports=True) still
  declared `char * FW_VERSION_PREFIX;` in `struct _root_toplev` and cast a
  `MojoList *` into it at the reassignment. That LINKS — both are
  pointer-sized — so nothing reports it, while
  `root__mojo_global_get_FW_VERSION_PREFIX` returns `char *` for a list. A
  silent miscompile, and precisely the "link mode and inline generated C
  must agree" bar.
- **Making it agree regressed link mode from 1 error to 10.** Adding the
  `BinaryOp` row (needed for the container evidence) changes what
  `_phase17_value_type` reports for `+` for EVERY caller, not just the new
  one, and the link-mode field type and the assignment-site coercion
  (`_global_dst_ctype` -> `_own_overlay_global_ctype`, which prefers a
  scalar own-overlay conclusion unconditionally) then disagreed.

The unresolved mechanism, for whoever picks this up: **three separate sites
re-derive this global's type** — Phase 1.7, `_gscan_declare_global`, and the
`_<mod>_toplev` struct emitter — and they run in an order that lets the
later ones overwrite the earlier conclusion. A guard placed in
`_gscan_declare_global` was measured to be a **no-op** (it never fires:
`gname` is already in `_declared_globals` by then), so the site that
actually emits `struct _root_toplev`'s field text is still unidentified.
`global_decls` — the list `_gscan_declare_global` appends to — is **not
emitted at all** (`module_gen.py:7281`: "kept for compatibility, but won't
be emitted"), which is why patching it changed nothing.

**Next step:** find the real `_root_toplev` field emitter (it is NOT
`global_decls`; `_module_globals` at `module_gen.py:7085/7167` builds OTHER
modules' structs, so the root's own has its own site) and reconcile ALL the
re-derivation sites against one conclusion, rather than adding a fourth.
Doing that without regressing link mode is the actual work; the analysis
above is what makes it tractable.

The attempted implementation is preserved in `stash@{0}` ("WIP on master")
and as `/tmp/module_gen_item4_attempt.patch` (ephemeral). It is **not**
landed and should not be popped as-is — it needs the third site too.

Source file: `/Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-26, worktree fix/opencode-misc1 @ `e1e12bb` — ROOT CAUSE 2 FIXED in shared source; only the excluded high-risk root cause 1 remains)

Fresh safety-wrapped `fire.py build`: of the three long-standing
diagnostics, **the two `%`-format errors (`1447:17` / `1456:17`,
`int64_t % MojoDict *`) are GONE.** Fixed by commit `e1e12bb`:

- New runtime primitive `mojo_str_format_dict(char *fmt, MojoDict
  *vals)` (runtime/mojo_runtime.c) implementing Python's dict-keyed
  `%`-formatting against a DYNAMIC template at runtime — %(key)s/%(key)d/
  width/precision, per-slot value-kind tags on `_DictSlot` so an int
  value formats correctly under `%s`, real catchable KeyError on a miss.
  This is exactly the "genuinely new C runtime primitive" this doc's
  root-cause-2 analysis called for; it does NOT require recovering the
  template text at compile time, sidestepping the no-constant-propagation
  limitation entirely.
- `_lower_percent` (gimple_gen_exprs.py) routes any `%` whose RHS is
  dict-shaped (DictExpr literal / `dict(k=v,...)` builtin /
  MojoDict*-typed expression) to that primitive BEFORE falling through
  to numeric modulo; all other shapes are untouched.
- Bonus gap found and fixed en route: `_lower_builtin_dict` silently
  DROPPED kwargs — `dict(VER=..., FULLVER=...)` (this file's own line
  1443 shape!) built an EMPTY dict; now lowered via the same shared
  pair-store helper as `{k: v}` literals.
- End-to-end verified: a distilled repro of packageFromRecipe's exact
  `textvars = dict(...)` + `readme % textvars` shape builds AND produces
  output byte-identical to CPython.

**Remaining blocker: root cause 1 only** (`704:17: invalid operands to
binary + (have 'char *' and 'MojoList *')`) — the Phase-1.7 global
prescan blind to cross-function `global FW_VERSION_PREFIX`
reassignment, still explicitly high-risk shared machinery per this
doc's analysis below and still not attempted. Full quality gate for
`e1e12bb`: test_gimple.py 260/260 (4 new regression tests),
test_module_cache.py 76/76, check-selfhost clean, stdlib dylib rebuild
2 skips = this worktree's pre-existing baseline (io.mojo/process.mojo
dup/pipe libc conflicts, A/B-verified against a stashed tree — not
attributable). Doc stays open on root cause 1 alone.

## Status (2026-08-25, worktree fix/rest-remainder12): re-verified — STILL-OPEN, byte-identical errors.

Re-ran `python3 fire.py build .../Mac/BuildScript/build-installer.py`
fresh (safety-bounded per this session's memory-hazard protocol),
after this session's coroutine-body emitter fixes landed elsewhere
(see COMPILE_FAIL_Apple___main__.md) — none relevant here, this file
has no generator/coroutine bodies reaching either blocker. All three
diagnostics reproduce byte-for-byte identical to the 2026-08-23 entry
below (`build-installer.py:704:17: invalid operands to binary + (have
'char *' and 'MojoList *')`; `1447:17`/`1456:17: invalid operands to
binary % (have 'int64_t' and 'MojoDict *')`). Both root causes remain
exactly as analyzed below (global-type-reconciliation-across-function-
reassignment for #1; a genuinely unimplemented dict-keyed dynamic-
format-string runtime primitive for #2) — both explicitly flagged
high-risk/feature-sized in the existing writeup, and this session
found nothing to change that assessment. Not attempted. Doc kept open.

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
$ python3 fire.py build /Users/mrs/net/Python-3.14.6/Mac/BuildScript/build-installer.py
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
