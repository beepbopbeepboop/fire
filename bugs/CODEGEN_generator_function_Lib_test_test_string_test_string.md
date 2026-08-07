# CODEGEN_generator_function: Lib/test/test_string/test_string.py

## Status (updated 2026-08-06)

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
