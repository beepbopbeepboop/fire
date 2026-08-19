# CODEGEN_generator_function: Lib/test/test_exception_group.py

## Status (updated 2026-08-12 — this doc's own `leaf_generator` cascade FIXED; file still blocked by unrelated Lib/test/support/__init__.py gaps)

Re-verified against current master with a real `MOJO_DEBUG=1 python3 mojo.py
build`. The tuple-yield refusal described in the entry below is gone (as
expected, since that fix already landed), but the file still failed with
the SAME ~150-error malformed-declaration cascade first reported on
2026-08-06 (`type defaults to 'int' in declaration of
'mojo_list_append_int'`, `conflicting types for 'mojo_list_append_int'`,
etc.), now traced to a real, different root cause than previously
diagnosed.

**Root cause, found and FIXED**: `LeafGeneratorTest.test_leaf_generator`
contains `[e for e, _ in leaf_generator(eg)]` — a list COMPREHENSION
consuming `leaf_generator`'s tuple-valued yields with a bare (no
parentheses in the source), 2-name unpacking target. `gimple_codegen.py`'s
`_compr_generator_loop` (the comprehension-specific consumer of a
compiled coroutine generator) only recognized a tuple target when the
target string was wrapped in parens (`"(a, b)"`). That's always true for
an ordinary `for` STATEMENT's target (`mojo_compiler.py`'s
`_parse_unpack_target`-based ForStmt path always synthesizes the wrapping
parens regardless of source spelling), but comprehension targets go
through the separate `_parse_generator_target`, which only adds parens
when the SOURCE itself wrote them — `for e, _ in ...` inside a
comprehension parses to the literal string `"e, _"`, no parens. The old
check missed that bare form, silently fell through to the single-variable
branch, and emitted a literal, invalid GIMPLE statement:
`e, _ = <tuple-yield-value>;` (a comma-expression assignment, not a real
per-slot unpack) — which didn't just fail to compile cleanly itself, it
desynced `-fgimple`'s parser badly enough to cascade into dozens of
unrelated-looking "type defaults to 'int'"/"conflicting types" errors on
later, perfectly well-formed declarations. This is exactly the kind of
narrow-fix-with-broad-blast-radius shape this project's history warns
about (the "_tuplegetter incidents"), except here the ROOT bug itself was
narrow and real, not a fix regression.

**Fix** (`gimple_codegen.py`, `_compr_generator_loop`): detect the tuple
target the same permissive way `_compr_list_loop` already does (strip,
then check for a bare comma OR a paren-wrapped comma list), instead of
requiring parens. Verified via an isolated repro
(`pair_gen` yielding `i, i * 10` consumed via `[a for a, _ in
pair_gen(4)]`) — compiles, links, and runs, printing the correct `0 1 2
3`. Verified against the real file: the ~150-error cascade in
`test_exception_group.py` itself is completely gone; `MOJO_DEBUG=1`
confirms `leaf_generator`/`LeafGeneratorTest_test_leaf_generator` compile
through the coroutine path cleanly now.

**This file still does not build clean** — for entirely unrelated,
pre-existing reasons transitively reached via `Lib/test/support/__init__.py`
(7 errors: an `int64_t`/pointer argument-type mismatch in
`mojo_list_set_int`, two `int64_t *` vs `int64_t` pointer-cast mismatches,
an undeclared `print_warning`, a malformed statement around line 1905-1908,
and a `mojo_getattr` pointer-cast mismatch) — none of these are generator
codegen issues, none are in `test_exception_group.py`'s own source, and
none are new (already noted as out-of-scope in
`bugs/CODEGEN_generator_function_Lib_test_test_faulthandler.md`'s own
history for the same transitively-imported file). Doc kept open, not
deleted, since the file doesn't fully build — but its OWN bug (the
generator/comprehension miscompile) is genuinely fixed, not merely
narrowed.

Full mandatory gate after the fix: `test_gimple.py` 247/0,
`test_module_cache.py` 76/0, `make check-selfhost` clean, from-scratch
`libmojostdlib.dylib` rebuild 0 `skip <module>:` lines, `compile_stdlib.py`
664/664 passed 0 unexpected.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; other, pre-existing gaps now block)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`; the self-recursive `yield from leaf_generator(e, tbs)` case
from task #138 is untouched and still correctly skipped from the
type-unification walk). Confirmed via an isolated compile:
`leaf_generator`'s `yield exc, tbs` (line 564) is no longer refused,
and its own `co_yield`/tuple-boxing text is syntactically valid C++
(no g++ errors on those lines).

**This file still does not build**, blocked by unrelated, pre-existing
gaps EARLIER in the same function body: `tbs.append(exc.__traceback__)`
(line 556) and `tbs.pop()` (line 565) — `tbs`'s real type (a list,
default-valued `tbs=None` then reassigned `tbs = []`) isn't tracked as
`MojoList *` in this narrow coroutine-body model, so it defaults to
`int64_t`, and `exc.__traceback__`/`exc.exceptions` are non-`self`
struct-typed MemberExpr reads — a documented, general limitation of
this coroutine-body model (only `self.<field>` MemberExpr reads are
supported; see `_gen_cpp_generator_unit`'s own docstring). None of
these are the promise/ABI gap this session's fix targets. Not attempted
here. Doc kept open (not deleted).

## Status (updated 2026-08-09)

Re-verified against current master (`42faf64`) with a real
`MOJO_DEBUG=1 python3 mojo.py build`. The recursive-`yield-from`
classification below (task #138, `bugs/hard/
CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`) is
confirmed to remain fixed — no cascade of malformed declarations.

The refusal `leaf_generator` now hits has changed and is cleaner than
what's described below: it's now refused up front, purely on the
tuple-valued `yield exc, tbs` at the very end of its body:
```
[gimple_codegen] generator 'leaf_generator' not eligible for C++ coroutine
path, falling back to honest refusal: leaf_generator: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
```
This is a clean, honest, CORRECT refusal — not a miscompile or cascade —
from `_infer_generator_yield_ctype`'s `TupleExpr` branch in
`gimple_codegen.py` (currently ~line 2699-2724): a multi-element `yield
a, b` has no representation in this generator-body model's single-scalar
promise type, and the function deliberately returns `None` (triggering
the same graceful "not eligible" fallback every other unsupported shape
gets) rather than letting the tuple sail through to `_cpp_stmt` and emit
invalid C++.

This is the **single most common gap across the whole
`CODEGEN_generator_function_Lib_*` doc family** (per this task's
briefing) — also hit by, at least, `Lib/dis.py`, `Lib/ftplib.py`,
`Lib/pkgutil.py`, and `Lib/test/libregrtest/save_env.py`. It is
correctly classified as structural, not narrow: fixing it for real means
threading a real N-scalar (or boxed-tuple) `co_yield` payload type
through the whole coroutine promise/emission machinery
(`_infer_generator_yield_ctype`, the promise-type declaration, every
`_cpp_stmt` `YieldExpr` case, and the caller-side resume/value-extraction
API) — not a one-spot stub or missing-case fix. Not attempted here, per
this task's guidance to not force a fix on confirmed-structural gaps.

`leaf_generator`'s other previously-noted sibling gaps (`tbs.append(...)`
on an untyped param, `exc.__traceback__`/`exc.exceptions` attribute
access) are moot for this file now — the tuple-yield refusal fires
first, before those statements are ever reached by `_cpp_stmt`.

No code change made for this bug.

## Status (updated 2026-08-07)

**Classification bug FIXED for the reported symptom** (`bugs/hard/
CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`, task
#138) — the root cause (a self-recursive `yield from` can never find
itself in `self._generator_api` while its own body is still being
compiled, since registration only happens after the whole compile
succeeds) is fixed. Confirmed via a direct compile: the ~150-error
cascade of malformed declarations this doc reported (`type defaults to
'int'`, `conflicting types for 'mojo_list_append_int'`, etc.) is GONE
— the plain `.ci` output now compiles cleanly with `gcc -fgimple
-fsyntax-only` (0 errors, confirmed).

**`leaf_generator` STILL does not fully compile end-to-end**, for
OTHER, unrelated, pre-existing reasons in its own body (confirmed via
a direct g++ compile of the `.cpp`): `tbs.append(...)` (a method call
on an untyped param treated as a scalar `int64_t`), `exc.__traceback__`
/`exc.exceptions` (attribute access on the same), and `yield exc, tbs`
(a tuple yield, not a single scalar) are all out of this narrow
generator-body model's scope — separate, pre-existing gaps, not
introduced by this fix, and not attempted here. These now surface as
ordinary, LOCALIZED g++ errors rather than a cascading, hard-to-read
corruption — a real improvement in diagnosability even though the file
doesn't fully compile yet.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `request for member 'append'` .cpp error no longer
reproduces, replaced by a much larger cascade of ~150 severely malformed
declaration errors directly in the plain `.ci` output (NOT a `_gen.cpp`
file):
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py:576:3: error: type defaults to 'int' in declaration of 'mojo_list_append_int' [-Wimplicit-int]
/Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py:576:3: error: conflicting types for 'mojo_list_append_int'; have 'int()'
/Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py:593:3: error: type defaults to 'int' in declaration of '_mojogen_leaf_generator_destroy' [-Wimplicit-int]
```

**Classification: `bugs/hard/CODEGEN_generator_recursive_yield_from_no_
arg_forwarding.md`** (added as that doc's new "Additional real
occurrence" — its previous evidence was a synthetic minimal repro plus
one real file with a DIFFERENT failure mode; this is the first
confirmed REAL stdlib instance hitting a third, more severe failure
mode). Root cause: `leaf_generator(exc, tbs=None)`:
```python
def leaf_generator(exc, tbs=None):
    if tbs is None:
        tbs = []
    tbs.append(exc.__traceback__)
    if isinstance(exc, BaseExceptionGroup):
        for e in exc.exceptions:
            yield from leaf_generator(e, tbs)      # recursive yield from, extra param
    else:
        yield exc, tbs
    tbs.pop()
```
Exactly the hard-bug doc's own repro shape (recursive `yield from` to
itself, with a defaulted extra parameter `tbs`). Here it manifests as
the emission getting badly desynchronized around lines 574-598 — the
whole `_mojogen_leaf_generator_destroy`/runtime-helper declaration block
comes out with missing types/braces, cascading into unrelated-looking
errors against `mojo_list_append_int` and other runtime helpers.

Not fixed here — see the hard-bug doc's "What a real fix needs" section;
this is a substantial, pre-identified fix, not a narrow one.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py
