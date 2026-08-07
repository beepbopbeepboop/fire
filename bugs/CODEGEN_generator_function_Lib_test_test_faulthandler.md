# CODEGEN_generator_function: Lib/test/test_faulthandler.py

## Status (updated 2026-08-07, `sys.stderr = None` case now fixed)

This file's specific occurrence (`sys.stderr = None` in
`check_stderr_none`) is now fixed — `_cpp_stmt`'s `AssignStmt` handling
gained a narrow, structurally-scoped case for `sys.stderr`/`stdout`/
`stdin` as an assignment target (elided as a safe no-op; see
`bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md`
for the full root cause and why eliding this specific shape is sound).
Confirmed via `MOJO_DEBUG=1`: `check_stderr_none` no longer appears in
the "not eligible"/refused list at all.

**`check_stderr_none` still does NOT fully compile end-to-end**,
for OTHER, unrelated, pre-existing reasons in the same method body
(confirmed via an isolated repro of its exact source): `stderr = sys.
stderr` (a `sys.stderr` READ — a separate, still-open gap, since `sys`
has no real backing value anywhere in this model outside the `print(
file=sys.stderr)` structural match), `self.assertRaises(...)`/`self.
assertEqual(...)` (method calls on `self`, out of this narrow `self.
<scalar field>`-reads-only model's scope), and `with ... as cm:`
binding a method-call result. Same "target-shape fixed, sibling
constructs in the same body still gap out" pattern as every other
partial fix in this cluster (task #149's imaplib.py, task #150's
original list-unpack fix on gc_inspection.py).

Also still present, unrelated: the transitively-reached `test.support`
`start_threads` gap noted below (`print()` non-scalar argument).

Full 5-part CLAUDE.md gate passed for the codegen change (see the
hard-bug doc for details): test_gimple.py 247/247, test_module_cache.py
76/76, check-selfhost clean, dylib rebuild 0 skips, compile_stdlib.py
664/664 0 unexpected.

## Status (updated 2026-08-07, superseded above)

`bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md`
is now PARTIALLY fixed (task #150) — but only the tuple/list-pattern-
unpack target shape. This file's own occurrence (`sys.stderr = None`,
a non-`self` MODULE-attribute assignment target) is the specific shape
that fix deliberately did NOT cover — assigning into an arbitrary
object's attribute has no representation in this narrow scalar-only
generator-body model, correctly identified as a meaningfully bigger,
separate step in the hard-bug doc's own "What a fix needs" analysis.
`check_stderr_none` is still refused, unchanged.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`), now precisely classified.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/test_faulthandler.py
[gimple_codegen] generator method FaultHandlerTests.'check_stderr_none' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
```

**Classification: `bugs/hard/CODEGEN_generator_non_plain_assignment_
target_refused.md`** (4th confirmed occurrence, and the first involving
a MODULE attribute as the target rather than tuple/list-unpack):
```python
def check_stderr_none(self):
    stderr = sys.stderr
    try:
        sys.stderr = None            # <-- module-attribute assignment target
        with self.assertRaises(RuntimeError) as cm:
            yield
        ...
```
`sys.stderr = None` assigns to `sys.stderr` — a `MemberExpr` target
(module attribute), not a bare identifier — refused by the same
generic "only a plain identifier assignment target is supported" check
as the doc's other 3 occurrences (which were tuple/list-pattern
unpacking). Confirms the gap is broader than just unpack-shapes: ANY
non-`IdentExpr` assignment target inside a generator body is refused,
including plain attribute assignment.

Also transitively (via `test.support`, not this file's own code): a
NEW gap, `start_threads` refused with "`print()` argument must be a
scalar int64_t/double/_Bool/char* expression" — a `print()` call with a
non-scalar argument inside a generator body. Single instance, not yet a
hard-bug doc; plausibly related to the pkgutil.py callback-argument-
shape gap (`bugs/CODEGEN_generator_function_Lib_pkgutil.md`) as another
instance of "some call sites inside a generator body have a stricter
argument-shape requirement than the general parameter-type allow-list."

Not fixed here.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_faulthandler.py
