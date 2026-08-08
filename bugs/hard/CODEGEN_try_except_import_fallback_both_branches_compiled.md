# HARD BUG: `try: from X import Y / except ImportError: from Z import Y` compiles BOTH branches, causing a redefinition conflict

## Status (FIXED 2026-08-08)

Fixed in `gen_module` (`gimple_codegen.py`, immediately before the
pre-existing `IfStmt` def-promotion block): a new pass walks each
top-level `TryStmt` and, when the `try` body and at least one `except`
handler body both bind the SAME name via `FromImportStmt`,
`ImportStmt`, or `FunctionDef`, replaces the whole `TryStmt` with just
the `try` body's statements (dropping the `except`/`else`/`finally`
bodies for codegen purposes) — mirroring the existing `IfStmt`
platform-branch resolution's "pick one branch, replace the container in
`stmts`" shape, with `try` always winning (this compiler doesn't model
real exception control flow, so there's no way to know at compile time
whether the `try` branch's import would actually fail on a given
platform; `try` winning matches the common-case expectation for the
"prefer the modern/preferred name" idiom below).

Deliberately conservative in two ways, both required by the plan and
confirmed necessary by testing (see Verification):
1. **The trigger only looks at `FromImportStmt`/`ImportStmt`/
   `FunctionDef` bindings** — NOT plain `AssignStmt`/`MultiAssignStmt`/
   `VarDecl`. An early draft also treated a shared plain-assignment
   target (e.g. `result = ...` appearing in both the `try` and `except`
   bodies) as a trigger, which is WRONG: that's the ordinary, extremely
   common defensive-error-handling idiom (`try: result = f() / except:
   result = fallback`), not the redefinition bug this fix targets.
   Only imports and function defs actually emit a competing C-level
   symbol DEFINITION that can collide; a plain assignment doesn't, so
   it's not evidence of the fallback-idiom shape and must not gate the
   branch-drop.
2. Even when triggered, an ordinary `try`/`except` doing genuinely
   different, non-overlapping things in each branch (no shared
   `FromImportStmt`/`ImportStmt`/`FunctionDef` name) is left completely
   untouched — both branches still get scanned/compiled exactly as
   before this fix (which may still hit the original redefinition error
   if they generate a genuine name collision by some other mechanism,
   but that's a materially different, non-fallback shape out of scope
   here).

### Verification

- Minimal repro (`/tmp/hardbug_repros/tryexcept2/main.py`: both `try`
  and `except` define `def helper():` with different bodies) —
  compiles without a redefinition error and the built binary runs the
  `try` branch's `helper()`, printing `"a"` as expected.
- `/tmp/hardbug_repros/tryexcept3.py` (the `from json import loads as
  parse` / `from simplejson import loads as parse` shape from this
  doc's own repro) — compiles with no redefinition error.
- `Tools/ssl/multissltests.py` / `Tools/wasm/wasi/__main__.py` (this
  doc's original real-world instances) — re-checked; both now fail on
  unrelated, separate downstream bugs (not this one), unchanged from
  before this fix — confirms no regression, matching the plan's own
  note that these two files' exact failure mode had already shifted by
  the time this was implemented.
- **Precision check** (`/tmp/hardbug_repros/tryexcept_notfallback.py`):
  ```python
  try:
      from os import getcwd
      result = getcwd()
  except ImportError:
      error_flag = True
      result = "unknown"
  print(result)
  ```
  `result` is assigned in BOTH branches (ordinary defensive-error-
  handling, not the fallback-import idiom), while `getcwd`/`error_flag`
  are not shared. Confirmed the fix does NOT collapse this TryStmt —
  both branches are still scanned/compiled independently, producing the
  exact same (pre-existing, unrelated) `int64_t`/`char *` type-conflict
  compile error as on unmodified master (`git stash` A/B compared
  byte-for-byte identical). This is what caught and fixed the
  over-broad first draft described in point 1 above.
- Full 5-part gate: `test_gimple.py` 247/247, `test_module_cache.py`
  76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild
  0 skips, `compile_stdlib.py -j8` 664/664 (0 unexpected, unchanged
  from baseline).

## Original status (2026-08-06, historical)

Unfixed. Root-caused 2026-08-06 while triaging
`bugs/COMPILE_FAIL_Tools_ssl_multissltests.md` and
`bugs/COMPILE_FAIL_Tools_wasm_wasi___main__.md` — two independent
files, identical mechanism, confirming this is a real recurring pattern
rather than a one-off.

## Symptom

```
error: redefinition of '<name>'
```
for a name imported (or defined) in BOTH the `try` body and an
`except` handler of the same `try` statement.

## Confirmed real-world instances

1. `Tools/ssl/multissltests.py`:
   ```python
   try:
       from urllib.request import urlopen
       from urllib.error import HTTPError
   except ImportError:
       from urllib2 import urlopen, HTTPError
   ```
   → `error: redefinition of 'urlopen'`

2. `Tools/wasm/wasi/__main__.py`:
   ```python
   try:
       from os import process_cpu_count as cpu_count
   except ImportError:
       from os import cpu_count
   ```
   → `error: redefinition of 'cpu_count'`

Both are the standard CPython compatibility idiom: try importing the
modern/preferred name, fall back to an older/alternate one on
`ImportError`, with BOTH branches binding the SAME local name so the
rest of the file can use it uniformly. Extremely common throughout the
real stdlib (version/platform compatibility shims).

## Root cause (inferred, not traced into the exact codegen site)

`gen_module`'s conditional-toplevel-def promotion already resolves
`if <platform-check>: def f(): ... else: def f(): ...` down to
whichever branch is ACTUALLY correct for the target platform (commit
`7014dde`, and the analogous global-variable-conditional flattening in
Phase 1.7 — see `_flatten_resolved_conditionals` in `gimple_codegen.py`,
also documented in `bugs/COMPILE_FAIL_importlib__bootstrap_external.md`).
No equivalent resolution exists for a `TryStmt`'s `try`/`except`
branches: both bodies' top-level `FromImportStmt`s (and presumably
plain `def`s / assignments too, though not confirmed here) get
processed and each contributes its own binding for the same name,
producing two conflicting C declarations/definitions for one symbol.

Unlike the `if <platform-check>:` case (which this codegen can often
resolve at COMPILE time, since `sys.platform`/similar checks are
frequently statically knowable), a `try`/`except ImportError` fallback
is NOT generally statically resolvable in the same way — whether the
`try` branch's import actually succeeds depends on the target
platform's real availability, which this compiler doesn't know at
compile time. The correct behavior for this specific idiom (not a
general `try`/`except` semantic — this compiler doesn't implement full
exception-based control flow at the type-checking level) is almost
always "prefer the `try` branch and ignore the `except` branch(es)
for the purpose of choosing WHICH DEFINITION of the name to emit" —
mirroring how the `if` case already picks one branch, just with a
fixed default heuristic (`try` wins) rather than a resolvable
condition.

## What a real fix needs

1. Extend whatever currently only flattens `IfStmt` conditionals (the
   `_flatten_resolved_conditionals`-style logic, or a sibling pass) to
   also recognize a TOP-LEVEL `TryStmt` whose `try` body and `except`
   handler(s) both bind the SAME name(s) (via `FromImportStmt`, plain
   `AssignStmt`, or `FunctionDef` — whichever this compiler's import/
   def promotion actually processes) and keep ONLY the `try` body's
   binding, dropping the `except` handler's competing one(s) for
   codegen purposes (the `except` handler can still be emitted as
   dead/unreachable code if this codegen ever adds real try/except
   compiled semantics — out of scope here, this is purely about which
   TOP-LEVEL NAME BINDING wins).
2. Careful scope: this should be conservative — only apply when the
   `try` and `except` bodies are BOTH simple, single-purpose fallback
   imports/defs of the same name(s) (the common idiom), not a general
   "always prefer try" rule that could silently pick wrong code for a
   `try` body that has real, non-fallback side effects the `except`
   handler is meant to compensate for.
3. Verify against both confirmed instances plus a minimal repro:
   ```python
   try:
       from json import loads as parse
   except ImportError:
       from simplejson import loads as parse
   print(parse("{}"))
   ```

## Risk

Low-to-moderate. This is name-binding/import-resolution logic, similar
in spirit to (and hopefully reusable from) the already-shipped `IfStmt`
platform-branch resolution — a narrower, more mechanical fix than the
type-inference-machinery bugs elsewhere in this session's findings.
Still needs the full quality gate given import resolution is exercised
by virtually every real-world file.
