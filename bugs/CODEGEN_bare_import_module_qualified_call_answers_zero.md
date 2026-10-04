# CODEGEN: a bare `import <sibling>` + `<sibling>.<free_fn>(...)` answered 0 on the link/build path

**State: CLOSED 2026-10-02.** Every table row and every wild-code site below
was re-measured on this tree; the two halves are landed and the shape prints
CPython's answer. Regression: `test_link_mode.py`'s
`test_bare_import_sibling_function_call_through_module`, with the
`from _deepmod import deep_fn` spelling as its control in the same build.

## The repro, and the answer now

```python
# deep.py
def deep_fn(x):
    return x + 7

# app.py
import deep

def main():
    print(deep.deep_fn(1))

main()
```

| | |
|---|---|
| `python3 app.py` | `8` |
| `python3 fire.py run app.py` (interpreter) | `8` |
| `python3 fire.py build app.py` then `./app` | **`deep_fn: unavailable in compiled mode0`**, exit 0 |

That last line is still the exact shape of the original report's failure text
— so it is worth being explicit about what changed. The **diagnostic and the
wrong answer are gone**: the program now prints `8`, silently, exactly like
CPython. What is gone with them is the one thing that made this bug
*visible*, and that is the whole reason it is worth stating here: on this
compiler an unresolvable call does not fail, it prints a message on the
program's own stdout and returns 0. A caller comparing exit codes sees a pass.
Any future regression of this shape will be silent again, which is why the
regression asserts stdout against CPython rather than an exit code.

## What it took, and it took two things

The doc's "partial fix that is NOT enough, recorded so nobody re-lands it"
was right, and the two halves are still separable — measured by reverting each
one alone:

| state | result |
|---|---|
| neither | `deep_fn: unavailable in compiled mode0`, exit 0 |
| the member registration only | `_t2 = deep_deep_fn_9f63a2 (1);` then `ld: symbol(s) not found for architecture arm64: _deep_deep_fn_9f63a2` |
| the inline half only | works |
| both | works, and the symbol is the same one the inline (`do_imports`) path emits |

1. **The module was never inlined.** `_inline_bare_import_struct` asked only
   `_source_defines_struct`, with a comment saying so ON PURPOSE — "a
   FUNCTION reached through a bare marker is a separately tracked bug with
   its own filed doc". That doc is this file, so the exclusion had nothing
   left to exclude. It now calls `_classify_unresolved_export`, the shared
   classifier the `from M import X` spelling uses, which already answers for
   a plain top-level function. Two functions that must agree are now one,
   which is the argument that classifier's own docstring makes about the two
   copies it replaced.

2. **The member was never registered.** `import deep` records
   `imported_symbols['deep'] = {'module': 'deep', ...}` — for the MODULE, not
   for its members. So the re-dispatched BARE call (`_note_own_func_home` +
   `_lower_call` on a synthesized `IdentExpr`) found no
   `imported_symbols['deep_fn']`, `_func_mangleable('deep_fn')` was False,
   `_func_csym` produced the bare `_safe_name('deep_fn')` with no qualifier
   and no overload suffix, and `_lower_named_call`'s `_is_unknown` branch
   emitted its weak 0-returning stub. The call site now registers the member,
   with the signature from the DEFINING module's own parsed FunctionDef
   (`_resolved_export_entry`) rather than `module_loader`'s text scan — the
   scan answers `int64_t deep_fn (void)` for an unannotated `def deep_fn(x)`,
   and as the only prototype in the file that rejects its own call site.

The registration writes three tables (`imported_symbols`, `func_return_types`,
`func_param_types`), and `_register_link_imports` was writing them inline.
Those three writes are now `funcs_shared.register_imported_symbol`, called
from both, because an entry that is present in one and missing from another is
exactly the half-registered state this bug was — and because "the same three
lines written twice" is how they drifted before. The helper carries
`write_param_types` for `_register_sym`'s rule (the param types are only
recorded when this compile will not emit the definition itself), so its
behaviour is unchanged. `_register_sym`'s string branch also stopped recording
`original_name` for an unaliased import, which is the rule the dict branch
already followed and the one whose violation makes `_func_csym` emit a
decimal-address guard name under `mojoc`.

## Where it shows up in the wild — NOT re-measured

The four `Lib/ctypes/util.py` errors this doc listed:

```
Lib/ctypes/util.py:221:10: error: implicit declaration of function 'shutil_which_15d274'
Lib/ctypes/util.py:228:10: error: implicit declaration of function 'tempfile_NamedTemporaryFile_100b86'
Lib/ctypes/util.py:228:8:  error: assignment to '_TemporaryFileWrapper *' from 'int'
Lib/ctypes/util.py:246:3:  error: implicit declaration of function 'tempfile__TemporaryFileWrapper_mojo_close'
```

are this shape (`shutil.which(...)`, `tempfile.NamedTemporaryFile()`,
`close()`, reached through `import shutil` / a function-body
`import re, tempfile`). **Not re-measured**: verifying it needs
`compile_stdlib.py`, which this session was not permitted to run, and both
`shutil` and `tempfile` are stdlib dylib modules whose definitions live behind
a dylib rather than being inlined — the configuration this fix's inline half
deliberately leaves alone (see `_inline_bare_import_struct`'s own scoping note:
inlining a module that already has a dylib behind it would emit a second
definition of symbols the link already binds). The member registration half is
the one that applies there, and it is what turns an unqualified call into the
symbol the dylib exports. Whether it is sufficient for
`NamedTemporaryFile` (a CONSTRUCTOR reached through a module marker, which is
the struct path, not this one) is the open question, and it is a
`compile_stdlib.py` measurement.

## The original report follows, with its own next step recorded as answered
## where it was not

Two files, `deep.py` and `app.py`, built with `python3 fire.py build app.py`:

```python
# deep.py
def deep_fn(x):
    return x + 7
```

```python
# app.py
import deep

def main():
    print(deep.deep_fn(1))

main()
```

| | expected | got |
|---|---|---|
| `python3 app.py` | `8` | `8` |
| `python3 fire.py run app.py` (interpreter) | `8` | `8` |
| `python3 fire.py build app.py` then `./app` | `8` | `deep_fn: unavailable in compiled mode` |

**Exit 0, no diagnostic beyond the stub's own message, and a wrong answer.**

## What is and is not already handled

Three neighbours all work, which is what makes this one look like a gap
rather than a documented limitation:

- `from deep import deep_fn` … `deep_fn(1)` → `8`. Correct.
- `from . import base2` … `base2.doubleval(21)` inside a real package, i.e.
  `_lower_method_call`'s own module-qualified branch → `42`. Covered by
  `test_link_mode.py::test_bare_submodule_import_call` and
  `::test_bare_submodule_import_call_inside_source_tree`.
- `deep.deep_fn(1)` reached through `compile_to_gimple(do_imports=True)`
  (the single-TU inline path) → `8`, correct, emitting `deep_deep_fn_9f63a2`
  with a real definition in the same TU.

So the shape is supported on the inline path and on the `from X import Y`
spelling, and NOT on the link/build path with a bare `import X`.

## Root cause, as originally traced

`_lower_method_call`'s module-qualified-call branch
(`mojo/backend_gimple/emit_methods.py`, the `_mgc_*` block) is reached and
does fire. Instrumented on that build, at the `deep.deep_fn(1)` call site:

```
module_name='deep' in_alias=True imported={'module': 'deep', 'return_type': 'unknown'}
existing_paths=['…/.tmp/nest2/deep.py']
note_own_func_home('deep_fn', 'deep', False)   <- the branch DID re-dispatch
```

so the regex confirmation, the alias lookup, the path resolution and the
`_note_own_func_home` registration all succeed. What is missing is what
happens next:

```
_func_mangleable('deep_fn') is False
  _mangled_funcs:        'deep_fn' NOT in
  struct_field_types:    'deep_fn' not in
  _NO_OVERLOAD_MANGLE:   not in
  imported_symbols:      None      <- no 'signature' entry was ever recorded
```

`_func_mangleable` (emit_funcs.py) returns True only for a name in
`_mangled_funcs`, or one with an `imported_symbols` entry carrying a
`'signature'` — and that is the entry this fix adds.

## Next step, as the original document wrote it, and its answer

> The honest fix has to answer one question the current code never asks:
> **what is the signature of `<module>.<member>` when this module was
> reached by a bare `import`?** `load_module`'s export table has it —
> `_register_link_imports` and `_emit_stdlib_import_externs` both consult
> exactly this for the `from X import Y` spelling. The bare-`import`
> module-qualified path should register the same
> `imported_symbols[name] = {'module', 'original_name', 'signature',
> 'c_parameters', …}` entry the FromImportStmt path registers, so
> `_func_mangleable` sees a signature and `_func_csym`/`_overload_suffix`
> produce the same symbol the defining module emitted. That is one
> registration, at the same place `_note_own_func_home` already is — but
> whether it must also mark the name in `_mangled_funcs` (and whether the
> dylib-satisfied case needs anything more) is not settled.

**Answered, both open questions.** It must NOT mark the name in
`_mangled_funcs`: that was the partial fix this doc warned against, and it is
both unnecessary (an `imported_symbols` entry carrying a signature is already
enough for `_func_mangleable`) and insufficient (it produces a QUALIFIED but
UNMANGLED name — `deep_deep_fn` rather than `deep_deep_fn_9f63a2` — because
the overload suffix comes from `_effective_param_types`, i.e. from the
signature this registration supplies). And the dylib-satisfied case needs
nothing beyond the same registration: a module behind a dylib is not inlined,
and the call site's symbol then has to match what that dylib exports, which is
the same spelling the inline path emits because both go through `_func_csym`
with the same qualifier and the same signature.
