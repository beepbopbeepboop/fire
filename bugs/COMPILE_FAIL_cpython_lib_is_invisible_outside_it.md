# The compiler has no way to see CPython's `Lib/` from an entry file outside it

## What was run

```sh
cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/* .tmp/ca/
cd .tmp/ca && python3 fire.py build c_analyzer/__main__.py
```

## What was seen

The closure compiles, and then three of its own imports degrade to
silent stubs rather than resolving:

```
# ERROR: compiling imported module 'c_parser.info' from .../c_parser/info.py:
    cannot materialize a generator as a list: no known generator API for
    'rendered' (pass the generator through a variable, or consume it with a
    for loop)
# ERROR: compiling imported module '._func_body' from .../c_parser/parser/_func_body.py:
    cannot coerce MojoDict * to MojoList * (incompatible container kinds) at
    .../_func_body.py: value='_t513' dest='data'
# ERROR: compiling imported module 'c_parser.match' from .../c_parser/match.py:
    cannot coerce MojoSet * to MojoList * (incompatible container kinds) at ...
```

and `import argparse` inside `c_analyzer/__main__.py` compiles to a
receiver stub — `parse_args()` returns the parser object and the first
attribute read off it is `Unhandled exception: AttributeError:
cross_build_dir`.

## What was expected

`c_analyzer/__main__.py` imports `argparse`, `contextlib`, `re`,
`collections`, `types`, `builtins` — every one of them is a CPython
`Lib/` module, and the CPython source tree is right there on disk.

## Root cause

Two resolver layers, and both are `.mojo`-only for PATH-based lookup:

* `imports._find` probes `<dir>/<name>.mojo` and `<dir>/<name>/__init__.mojo`.
  A `.py` file on the search path is invisible to it.
* the inline importer's candidate dirs are sys.path-inserts + the importing
  file's own dir + a bounded ancestor walk + CWD/script_dir
  (`_module_candidate_paths`). From `Tools/c-analyzer/` no walk-up reaches
  CPython's `Lib/`, because the relevant `Lib/` is a SIBLING of `Tools/`,
  not an ancestor.

`PYTHONPATH` does not help, and this is worth stating precisely because it
looks like it should: `imports.py` honours the env var for its search
PATH, but `_find` only ever probes the two `.mojo` spellings above, so
`PYTHONPATH=<tree>/Lib` leaves `resolve_source('argparse') = None`
(verified empirically).

So the two facts are independent and both must change: the candidate set
has to include `<root>/Lib`, and `_find` has to recognise a `.py` file.

## Why this is a separate doc rather than part of another one

The recorded, deliberately-not-forced direction is in
`bugs/COMPILE_FAIL_Tools_build_deepfreeze.md`'s 2026-08-26 entry, and the
reason recorded there still holds: bounded blast radius (only entry files
inside a CPython checkout), but it would newly INLINE large `Lib/`
closures into binaries that are currently green-by-stub. `deepfreeze` would
then hit `Lib/contextlib.py`'s async-codegen refusal
(`bugs/COMPILE_FAIL_Lib_contextlib_*.md`) and fail honestly instead of
silently — a real behavioural shift across every concurrently-green
baseline in this project, so it needs to be a decision, not a drive-by.

## Next step

Detect a CPython source checkout from the entry file (an ancestor
containing a `Lib/` directory with `os.py` in it) and append `<root>/Lib`
to `_module_candidate_paths`, AND teach `imports._find` the `.py`
spelling. Both halves, or neither: the first alone changes nothing
observable, because `_find` will not look at what it is handed.

Measure the fallout with `compile_stdlib.py`'s `FAILED: N (E expected, U
unexpected)` before/after — `U` must not increase — and with the
`stdlib-dylib` `skip <module>:` count, per CLAUDE.md's gate section.