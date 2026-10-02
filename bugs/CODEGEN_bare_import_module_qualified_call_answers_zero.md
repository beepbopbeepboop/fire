# CODEGEN: a bare `import <sibling>` + `<sibling>.<free_fn>(...)` call silently answers 0 on the link/build path

Found 2026-10-01 while working `bugs/COMPILE_FAIL_ctypes_util.md` (its
remaining `implicit declaration of function 'tempfile_NamedTemporaryFile_…'`
errors are this shape — see "Where it shows up in the wild" below).

## The repro

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
| `python3 fire.py build app.py` then `./app` | `8` | `deep_fn: unavailable in compiled mode0` |

**Exit 0, no diagnostic beyond the stub's own message, and a wrong
answer.** `gimple_gen_calls.py`'s `_lower_named_call` prints its
`"{name}: unavailable in compiled mode"` weak stub and returns
`(int64_t)0`, so the value is silently 0 rather than 8.

## What is and is not already handled

Three neighbours all work, which is what makes this one look like a gap
rather than a documented limitation:

- `from deep import deep_fn` … `deep_fn(1)` → `8`. Correct.
- `from . import base` … `base.doubleval(21)` inside a real package, i.e.
  `_lower_method_call`'s own module-qualified branch → `42`. Covered by
  `test_link_mode.py::test_bare_submodule_import_call` and
  `::test_bare_submodule_import_call_inside_source_tree`.
- `deep.deep_fn(1)` reached through `compile_to_gimple(do_imports=True)`
  (the single-TU inline path) → `8`, correct, emitting
  `deep_deep_fn_9f63a2` with a real definition in the same TU.

So the shape is supported on the inline path and on the `from X import Y`
spelling, and NOT on the link/build path with a bare `import X`.

## Root cause, as far as it is traced

`_lower_method_call`'s module-qualified-call branch
(`mojo/backend_gimple/emit_methods.py`, the `_mgc_*` block) is reached and
does fire. Instrumented on this build, at the `deep.deep_fn(1)` call site:

```
module_name='deep' in_alias=True imported={'module': 'deep', 'return_type': 'unknown'}
existing_paths=['…/.tmp/nest2/deep.py']
note_own_func_home('deep_fn', 'deep', False)   ← the branch DID re-dispatch
```

so the regex confirmation, the alias lookup, the path resolution and the
`_note_own_func_home` registration all succeed. What is missing is what
happens next. The re-dispatched bare call goes to `_lower_call` →
`_lower_named_call`, and at that point:

```
_func_mangleable('deep_fn') is False
  _mangled_funcs:        'deep_fn' NOT in
  struct_field_types:    'deep_fn' not in
  _NO_OVERLOAD_MANGLE:   not in
  imported_symbols:      None      ← no 'signature' entry was ever recorded
```

`_func_mangleable` (emit_funcs.py) returns True only for a name in
`_mangled_funcs`, or one with an `imported_symbols` entry carrying a
`'signature'`. A bare `import X` records `imported_symbols['X'] =
{'module': 'X', 'return_type': 'unknown'}` and nothing about `X`'s
*members* — the entry is for the module, not its functions. So the name
is not mangleable, `_func_csym` returns the bare `_safe_name('deep_fn')`
with no qualifier and no overload suffix, `_lower_named_call`'s
`_is_unknown` branch fires, and the weak 0-returning stub is emitted.

The generated C makes the shape of the miss unmistakable — the call site
and the stub agree with each other and with nothing else:

```c
#ifndef _MOJO_STUB_deep_fn
#define _MOJO_STUB_deep_fn
__attribute__((weak)) int64_t deep_fn (...) { mojo_print ((char *)"deep_fn: unavailable in compiled mode"); return (int64_t)0; }
#endif
...
  _t2 = deep_fn (1);
```

while the inline path for the same two files emits
`deep_deep_fn_9f63a2` with a real definition — so the two paths disagree
about the same symbol's name as well as about whether it exists.

### A partial fix that is NOT enough, recorded so nobody re-lands it

Adding `gen._mangled_funcs.add(method_name)` next to the existing
`gen._note_own_func_home(method_name, _mgc_sub_ref, record_scope=False)`
in that branch is necessary and NOT sufficient. Measured: the emitted name
becomes `deep_deep_fn` (qualified) but still carries **no overload
suffix** and is still the weak stub, because mangleability only gets
`_func_csym` as far as consulting `_func_qualifier` — the suffix comes
from `_overload_suffix` → `_effective_param_types`, and there is still
no recorded signature for `deep_fn` to hash. It also has a second
problem: `deep.py` is satisfied from a dylib on this path, so its own
definition is not in this translation unit at all, and a symbol emitted
here has to match whatever that dylib exports.

## Where it shows up in the wild

`Lib/ctypes/util.py`, measured on this tree
(`python3 tools/memslot.py --gb 8 -- python3 fire.py build
/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py`, exit 1):

```
Lib/ctypes/util.py:221:10: error: implicit declaration of function 'shutil_which_15d274'
Lib/ctypes/util.py:228:10: error: implicit declaration of function 'tempfile_NamedTemporaryFile_100b86'
Lib/ctypes/util.py:228:8:  error: assignment to '_TemporaryFileWrapper *' from 'int'
Lib/ctypes/util.py:246:3:  error: implicit declaration of function 'tempfile__TemporaryFileWrapper_mojo_close'
```

All four are this shape: `shutil.which(...)`, `tempfile.NamedTemporaryFile()`,
`temp.close()` — module-qualified calls into `shutil`/`tempfile`, which
this file reaches through `import shutil` (line 2) and a function-body
`import re, tempfile` (line 203). `shutil` and `tempfile` both resolve and
both compile (`_compile_imported_module` returns `code=True`, 93 and 48
top-level statements respectively, confirmed by an instrumented trace), so
this is not a resolution failure — but their compiled text does not reach
the output TU, which is the part still to explain.

## Next step

The honest fix has to answer one question the current code never asks:
**what is the signature of `<module>.<member>` when this module was
reached by a bare `import`?** `load_module`'s export table has it —
`_register_link_imports` and `_emit_stdlib_import_externs` both consult
exactly this for the `from X import Y` spelling. The bare-`import`
module-qualified path should register the same
`imported_symbols[name] = {'module', 'original_name', 'signature',
'c_parameters', …}` entry the FromImportStmt path registers, so
`_func_mangleable` sees a signature and `_func_csym`/`_overload_suffix`
produce the same symbol the defining module emitted. That is one
registration, at the same place `_note_own_func_home` already is — but
whether it must also mark the name in `_mangled_funcs` (and whether the
dylib-satisfied case needs anything more) is not settled, so this is
recorded as the next action rather than attempted.

A regression test belongs beside `test_link_mode.py`'s
`test_bare_submodule_import_call` pair — the same two-module package with
a bare `import pkg.mod` instead of `from . import mod`, asserting the
compiled binary's stdout against CPython's, which is what every other case
in that file does.