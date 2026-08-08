# CODEGEN_generator_function: Lib/enum.py

## Status (updated 2026-08-07, Track B re-diagnosis, own-root build)

Re-diagnosed with `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/enum.py`
directly (this file as the ROOT of the build, not pulled in
transitively via `subprocess.py`/`typing.py`). Current result: a hard,
unhandled Python `RuntimeError` traceback (not a GCC compile error at
all):

```
Error building: cannot compile module: function(s) _iter_member_by_def_,
_iter_member_by_value_ (generator function(s), contain a `yield`/`yield
from`) — this codegen compiles every function into a single
straight-line C function and has no suspend/resume state-machine
transform for generators, nor an event loop / suspend-resume codegen
for async functions, yet, so these cannot be represented as compiled C
without emitting silently wrong or broken code; falling back to
interpreting this module from source instead
```

**This genuinely IS a generator-codegen-cluster failure** (contradicts
the 2026-08-06 re-diagnosis below, which was against a DIFFERENT
transitive graph — `subprocess.py`'s — where this exact refusal never
surfaced because something else failed first). Root cause, confirmed
via `MOJO_DEBUG=1`:

```
[gimple_codegen] generator method Flag.'_iter_member_by_value_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_value_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
[gimple_codegen] generator method Flag.'_iter_member_by_def_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_def_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
```

`enum.py`'s `Flag._iter_member_by_value_`/`_iter_member_by_def_` (lines
1428/1438) are BOTH `@classmethod` generators whose bodies reference
`cls` (`cls._flag_mask_`, `cls._iter_member_by_value_(value)`,
`cls._value2member_map_.get(val)`) — a documented, deliberate scope
limit of the C++20-coroutine generator codegen ("no class-level
attribute/method access exists yet for compiled generators"), not a
bug in the eligibility check itself. This is the SAME class of gap as
the explicitly-excluded `bugs/hard/CODEGEN_generator_struct_typed_
param_refused.md` (task #147) and `bugs/hard/CODEGEN_generator_lambda_
expr_unsupported.md` (also relevant here — `_iter_member_by_def_`'s
`yield from sorted(cls._iter_member_by_value_(value), key=lambda m:
m._sort_order_)` ALSO contains a lambda inside a generator, a second,
independent reason this exact generator would be refused even if
`cls`-access were supported) — both already flagged as feature-sized/
high-risk and NOT to be re-attempted per this session's scope. NOT
fixed; this file's OWN root build genuinely cannot succeed without a
real "class-level access from a compiled generator coroutine" feature,
which is out of scope here. The 4 OTHER `yield` sites the 2026-08-06
entry below found eligible (lines 123, 1433 [`_iter_member_by_value_`
itself, not this one — re-check needed], 1442, 1554) are unaffected;
only these two `@classmethod` ones are refused.

Separately, the `Signature`/`Parameter`-as-bare-C-identifier issue
mentioned in the 2026-08-07 entry just below is now root-caused (a
`typedef`-vs-callable-identifier collision in `_lower_MemberExpr`'s
handling of `Parameter.ATTR`-shaped member access before `Parameter`'s
own struct registration has happened) and PARTIALLY fixed — see
`bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md`'s "Mechanism 4" section for the full writeup. This
file's own `EnumType.__signature__` (the exact site quoted in that
section) is the fix's motivating example, but this file's own ROOT
build never reaches that code path at all — it fails earlier, on the
`@classmethod`-generator refusal above, before GCC ever runs.

## Status (updated 2026-08-07)

One more non-generator, unrelated error found and fixed in a
`Lib/subprocess.py`-transitive build of this file: `enum.py:1099:1:
error: invalid conversion in gimple call` (~10 occurrences,
`EnumType.__signature__`'s `from inspect import Parameter, Signature`
function-scoped import, then `Signature(...)`/`Parameter(...)`
constructor calls) — root cause was `_gen_stmt_FromImportStmt`
defaulting an unknown imported symbol's return type to `'int'` instead
of `'int64_t'` (mismatching the temp-declaration prescan and the
"unavailable in compiled mode" stub generator, both of which already
assumed `int64_t`). See `bugs/hard/CODEGEN_function_scoped_import_
rettype_and_literal_cast_mismatches.md` (Mechanism 1) for the full
writeup. Not re-verified against this file's OWN much larger error set
described below (that was from a `do_imports=True` compile rooted at
`enum.py` itself, a different transitive graph than subprocess.py's);
the `Signature`/`Parameter`-as-bare-C-type-name issue documented in that
same hard-bug doc's "Not fixed" section (found via `weakref.py`, not
here) may also be relevant to this file's own `Signature`/`Parameter`
usage — not cross-checked.

## Status (updated 2026-08-06, own re-diagnosis unaffected by the above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `request for member 'value'` .cpp error no longer reproduces.
`enum.py` has 4 of its own `yield`/`yield from` sites (lines 123, 1433,
1442, 1554) — none appear in the current error list, and `MOJO_DEBUG=1`
shows no "not eligible" refusal for any of them: enum.py's own generator
bodies now appear to compile cleanly through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore** —
the current build (whole-program transitive closure, ~600+ errors) fails
for reasons entirely unrelated to enum.py's own generators:

1. **Cross-reference: `bugs/hard/CODEGEN_generator_function_symbol_not_
   module_qualified.md`.** `Lib/tokenize.py`'s own `tokenize()` generator
   fails ITS eligibility check (`yield from
   _generate_tokens_from_c_tokenizer(...)` — delegates to a C-extension
   function, not a Python generator this compile can translate — see
   `bugs/CODEGEN_generator_function_Lib_tokenize.md`), and that failure
   leaves a stub/inconsistent `_mojogen_tokenize_value` declaration that
   collides across a dozen-plus sibling modules reachable from enum.py
   (`_weakrefset.py`, `argparse.py`, `ast.py`, `copyreg.py`,
   `encodings/aliases.py`, `functools.py`, `gettext.py`, `inspect.py`,
   `locale.py`, `reprlib.py`, `token.py`, `types.py`, `typing.py`,
   `weakref.py` all show `conflicting types for '_mojogen_tokenize_
   value'` against each other). Same underlying symbol-naming gap as the
   `os.py`/`walk` case the hard-bug doc documents, here triggered by a
   REFUSED generator rather than two independently-successful same-named
   ones — worth folding into that doc's scope once picked up.
2. **A large, apparently unrelated "double compilation" issue**: hundreds
   of `error: redefinition of 'enum_EnumType___new__'` (and ~80 more
   `enum_*`-prefixed symbols) — enum.py's OWN functions/methods being
   emitted twice into the same translation unit. Not investigated
   further (out of scope for this cluster) but looks severe and
   independent of generators.
3. The same recurring `stray '\' in program` / `_classattr_TextWrapper_
   _letter` tokenizer bug seen in `codecs.py`'s and `ipaddress.py`'s
   current re-diagnoses (line 2322 here).

None of (1)-(3) are generator-codegen bugs in enum.py's own code. Not
investigated further here.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/enum.py
