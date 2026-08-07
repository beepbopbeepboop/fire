# HARD BUG: `try: from X import Y / except ImportError: from Z import Y` compiles BOTH branches, causing a redefinition conflict

## Status

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
