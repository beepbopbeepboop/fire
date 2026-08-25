# CODEGEN_generator_function: Lib/test/test_string/test_string.py

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C3 cluster. The blocker (`BarFormatter` -- and its generator method `parse` -- defined INSIDE `test_override_parse`'s function body, so struct registration never sees it) is unaffected by this session's two landed fixes (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies) -- same nested-class-discovery family as test_ensurepip.py above. Still feature-sized; untouched.


## Status (updated 2026-08-23 — STILL-OPEN)

Re-ran the repro: identical whole-module fallback naming `parse` with no
per-function eligibility note. Root cause analysis below CONFIRMED and
UNCHANGED: BarFormatter is defined inside test_override_parse's body and
never reaches struct registration. Related-but-distinct parser work this
session (class-body CONDITIONAL method hoisting) does not cover function-
body-nested classes. Feature-sized, not attempted. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (updated 2026-08-09, root cause now FULLY CONFIRMED)

Re-verified against current master (fast-forwarded to `e5daa1d`) —
reproduces identically (`Error building: cannot compile module:
function(s) parse ...`, still no per-function "not eligible" debug note
naming `parse`).

Traced `gen_module` directly this pass (rather than just re-running the
build) to settle the "probable, not fully confirmed" root cause from
2026-08-06/07 with certainty:

- `gimple_codegen.py:28928`: `all_struct_defs = stmts + (imported_stmts
  ...)` — `stmts` is the flat list of MODULE-level statements passed
  into `gen_module`; it is never recursed into `FunctionDef` bodies.
- `gimple_codegen.py:30766` and `:30797` (the two generator-method
  compile passes, "Milestone C step 3" and its yield-from second pass):
  `for _sd in stmts: if not isinstance(_sd, StructDef): continue` — same
  flat top-level-only iteration.
- `_walk_ast` (`gimple_codegen.py:2091`), the one helper in this file
  that *does* recurse into arbitrary nesting depth (`if`/`while`/`try`/
  `with`/nested-`def` bodies), is used throughout this file only to hunt
  for specific node kinds inside an already-known function's body
  (`yield`, `await`, etc.) — never to discover additional `StructDef`s
  to feed into the struct-registration or generator-method-compile
  loops.

This confirms with certainty: `BarFormatter`, defined locally inside
`test_override_parse`'s body (`Lib/test/test_string/test_string.py`
~line 33-40), is never added to `stmts`'s top-level `StructDef` set at
all, so its `parse` generator method is never even visited by either
generator-method compile pass — not considered, not refused, hence no
per-function debug note. The whole-module fallback still fires because
a separate, correctly-thorough deep-scan (unrelated to struct
registration) finds the unhandled `yield` reachable somewhere in the
module regardless.

Confirmed genuinely structural, not attempted as a fix: `all_struct_defs`
and the two generator-method loops are load-bearing, module-wide
assumptions (struct field-layout emission, forward declarations, generic
elaboration, etc. all key off this same top-level-only `stmts` scan) —
teaching this codegen to discover and compile function-body-local
classes at all is a real, feature-sized change to the struct-
registration story generally, not scoped to generators specifically.
Out of scope for a narrow-bug pass.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild (both the full
`mojo.py build` CLI path and a direct isolated
`compile_to_gimple_with_cpp(..., do_imports=False)` call) — reproduces
byte-for-byte identically, same `RuntimeError` message, still with NO
per-function "not eligible" debug note for `parse`. The probable root
cause below (a locally-nested class's generator METHOD never reaching
the struct-registration/generator-method compile loop at all) was not
traced further to full certainty this pass either — still flagged as
the shape to confirm for whoever picks this up next. Not attempted as a
fix (would need the struct-registration-scan trace this doc's own note
already calls out, plus design work for compiling a function-body-local
class at all — likely feature-sized once confirmed, given how much of
this codegen's struct machinery assumes module/class-level struct
registration).

## Status (updated 2026-08-06, superseded above — re-verified, unchanged)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) — same top-level symptom as 2026-07-30 (`function(s) parse
... falling back to interpreting this module from source instead`), but
with a notable difference this pass: unlike every other refusal in this
cluster, `MOJO_DEBUG=1` shows **no per-function "not eligible" debug
note naming `parse` at all** — the fatal whole-module message fires
without the usual diagnostic breadcrumb.

**Root cause (probable, not fully confirmed — new gap, possibly
distinct from every other gap found in this cluster):**
```python
def test_override_parse(self):
    class BarFormatter(string.Formatter):
        def parse(self, format_string):
            for field in format_string.split('|'):
                ...
                yield '', field_name, format_spec, None
                ...
```
`parse` is a generator METHOD of `BarFormatter` — a class defined
LOCALLY, nested inside a test METHOD's own body (not at module level,
and not even inside a top-level class — two levels of nesting). Given
this codegen's generator-method compilation loop scans `struct.methods`
for each STRUCT it already knows about from its top-level struct-
registration pass, a class defined inside a function body plausibly
never gets registered as a "struct" that loop iterates at all — which
would explain why no per-function eligibility debug note is emitted
(the generator is never even CONSIDERED, let alone refused with a
specific reason) even though the whole-module fallback logic still
correctly detects an unhandled `yield` reachable somewhere in the
module and raises the same fatal RuntimeError.

Not confirmed with full certainty in this pass (would need to trace
`gen_module`'s struct-registration scan directly to confirm nested-
class-in-function bodies are skipped, vs. some other reason the debug
note didn't fire). Single instance in this cluster; not folded into a
hard-bug doc. If confirmed, this would be a NEW, distinct gap from
`bugs/CODEGEN_generator_function_Lib_test_test_ensurepip.md`'s nested-
class-INSIDE-a-generator-BODY gap (this is the reverse shape: a
generator method whose ENCLOSING class is nested inside a function).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_string/test_string.py
