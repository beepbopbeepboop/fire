# INTERP: `import a, b, c` only binds the first module name

## Repro

```python
import sys, os, difflib, argparse
print(argparse)
```

```
$ python3 mojo.py t1.py
NameError: t1.py:2:6: name 'argparse' is not defined
```

Any name after the first in a comma-separated `import` statement is left
unbound. Minimal case: `import difflib, argparse` binds `difflib` but not
`argparse`.

## Root cause (interpreter path)

`mojo_compiler.py`'s `_parse_import` already parses the full comma list: the
first `(module, alias)` goes into `ImportStmt.module`/`.alias`, and any
further comma-separated targets go into `ImportStmt.extra` (a list of
`(module, alias)` tuples) — see `mojo_compiler.py:1731`.

`myinterpreter.py`'s `execute_ImportStmt` (`myinterpreter.py:2551`) only
ever looks at `node.module`/`node.alias`; it never reads `node.extra`, so
every module past the first is silently dropped.

## Impact

Affects any stdlib/source file that imports multiple modules on one `import`
line — a very common Python idiom (`import sys, os, difflib, argparse` etc.),
so this is a wide-reaching, high-value fix. Several `bugs/TIMEOUT_*.md` /
`bugs/PARSE_FAIL_*.md` reports that looked like hangs or parse failures were
actually this: the script's `main()` used a module bound only in a
multi-name import line, then crashed (or in a couple of odd cases the
NameError being raised deep inside argparse/other stdlib machinery led to
pathological retry/backoff behavior that looked like a hang).

## Fix sketch

`execute_ImportStmt` needs to process `node.module`/`node.alias` *and* every
`(module, alias)` pair in `node.extra`, applying the same resolution logic
(sibling `.mojo` file check, `sys` special case, real `importlib.import_module`)
to each. Also check `gimple_codegen.py`'s lowering of `ImportStmt` for the
same gap on the compiled path (per CLAUDE.md's codegen quality gate).
