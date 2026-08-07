# CODEGEN_generator_function: Lib/enum.py

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
