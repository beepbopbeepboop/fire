# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-10-01 — unchanged; one blocker, shared with c_common/tables.py

Re-measured on the current tree (`python3 fire.py build`, sources copied from
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`). The sole
remaining refusal is still a SINGLE shape, unchanged:

```
Unsupported shape(s): check_all: unsupported for-loop iterable type: CallExpr.
```

Nothing moved. `check_all` (c_analyzer/__init__.py:92) binds `check` to a
CALLABLE-VALUE local by the outer loop and then calls it to get the iterable:

```python
def check_all(analysis, checks, *, failfast=False):
    for check in checks or ():
        for data, failure in check(analysis):
            ...
```

This is the SAME blocker now in front of
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (`read_table`'s
`for row in _get_reader(lines, ...)`, where `_get_reader` is a
default-valued callable parameter). One fix, three files — that doc's
"Next step" still names the three things the shape needs.

The imported-module floor (`c_parser.info` / `._func_body` / `c_parser.match`)
is also unchanged, and is now filed on its own rather than carried here:
`bugs/COMPILE_FAIL_cpython_lib_is_invisible_outside_it.md`.

## Status 2026-09-30 — two of three of this file's own blockers gone; one remains, and is shared with two other files

Re-verified against the current tree (`python3 fire.py build`, sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`). The
sole remaining refusal is now a SINGLE shape:

```
Unsupported shape(s): check_all: unsupported for-loop iterable type: CallExpr.
```

Both of the file's other blockers are resolved:

| blocker | what it was | how it went |
|---|---|---|
| `iter_decls: a `*`/`**`-unpack call argument is not supported in a compiled generator/coroutine body` | `iter_decls` doing `parsed = parse_files(filenames, **kwargs)` | cleared by commit `b67c170e` (see below) — not by a `**`-forwarding fix |
| (imported-module floor) `# ERROR: compiling imported module '.preprocessor' ... 169:17: Expected KW got NAME('_resolve_file_values')` | `c_parser/preprocessor/__init__.py:169` — `for patterns, in _resolve_file_values(...)` — a bare trailing comma in a `for` target, which the PARSER rejected | `b67c170e` |

**Read that table carefully: neither `**`-forwarding support nor any change
to `_cpp_try_kwargs_forward_call` was needed.** `iter_decls` stopped refusing
because its module stopped failing to PARSE its own import closure. The
`for patterns, in ...` parse failure was making `c_parser/preprocessor` fall
back to source, and with it gone, `iter_decls`'s remaining shape resolved
through paths that were already there. Anyone picking this up should not
start by extending `_cpp_try_kwargs_forward_call` — that machinery is still
exactly as narrow as its docstring says, and the two cases its docstring
names as deliberately-unhandled (`iter_analysis_results` doing
`iter_decls(filenames, **kwargs)`, `track_progress_compact` doing
`iter_marks(groups=groups, **mark_kwargs)`) are still unhandled by it.

### The blocker now in front of this file

`check_all` (c_analyzer/__init__.py:92):

```python
def check_all(analysis, checks, *, failfast=False):
    for check in checks or ():
        for data, failure in check(analysis):
            ...
            yield data, failure
```

`check` is a CALLABLE-VALUE LOCAL bound by the outer loop, and `check(analysis)`
is a dynamic call whose return is the iterable — a generator, in real code.
This is the SAME blocker now in front of
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (`read_table`'s
`for row in _get_reader(lines, ...)`, where `_get_reader` is a
default-valued callable parameter). One fix, three files — see that doc's
"Next step" for the three things that shape needs.

### Also worth recording: the imported-module floor has not gone away

Three imported modules still fail in every closure that reaches them, and
`c_analyzer/__init__.py` reports all three:

```
# ERROR: compiling imported module 'c_parser.info' from .../c_parser/info.py:
    cannot materialize a generator as a list: no known generator API for
    'rendered' (pass the generator through a variable, or consume it with a
    for loop)
# ERROR: compiling imported module '._func_body' from .../c_parser/parser/_func_body.py:
    cannot coerce MojoDict * to MojoList * (incompatible container kinds) at
    .../_func_body.py: value='_t513' dest='data'
# ERROR: compiling imported module 'c_parser.match' from .../c_parser/match.py:
    cannot coerce MojoSet * to MojoList * (incompatible container kinds) at
    .../match.py: value='_t6' dest='expected'
```

(`c_parser/preprocessor` was the fourth and is now fixed.) So even a perfect
`check_all` would not make THIS file build — the floor has to go first. The
`c_parser.info` one is understood and is the same `rendered, = rendered`
shape described in `bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
(it unpacks the first value out of a classmethod GENERATOR,
`cls._format_data(...)`, whose return the ordinary path types
`MojoGenerator *` but whose api it never records).

