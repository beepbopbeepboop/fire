# `py_tokenize` dropped its second parameter; the two hand-written C signature tables kept it

## What was run

```sh
python3 test_gimple.py
```

## What was seen

348 passed, 1 failed:

```
FAIL  handwritten_selfhost_signature_tables_match_the_source:
  py_tokenize: table declares 2 C parameter(s), the source takes 1 (['src']) — a
  DEFAULTED parameter still occupies a C parameter slot
```

This is **pre-existing on `master`** — neither this branch nor the earlier
work on it touches `py_tokenize`, `gimple_codegen._KNOWN_SIGS` or
`runtime/fire_runtime.h`. It is filed rather than fixed because the lexer
area is another worker's claim (`construct:bugs-lexer-imports`).

## Cause

Commit `7ce61398` ("lexer: py_tokenize keeps its one-argument ABI; the
filename variant gets a name") changed the definition to

```python
def py_tokenize(src: str) -> list[Token]:          # fire_compiler.py:1325
def py_tokenize_named(src: str, filename: str) -> list[Token]:
```

and did not update either of the two hand-written C declarations that
describe it, which is exactly the drift that test exists to catch:

| site | declares |
|---|---|
| `gimple_codegen.py:3131` — `GimpleGen._KNOWN_SIGS['py_tokenize']` | `('MojoList *', ['char *', 'char *'])` |
| `runtime/fire_runtime.h:1751` | `MojoList *py_tokenize(char *source, char *filename);` |

The header's own comment (`fire_runtime.h:1745-1748`) still quotes the old
signature — `py_tokenize(src: str, filename: str = "")` — and describes
precisely this failure: `too many arguments to function 'py_tokenize';
expected 1, have 2` at each of the closure's ~20 call sites.

## Why it matters beyond the red test

`_KNOWN_SIGS` is what the compiled path emits as a forward declaration when
this compiler compiles itself, so a prototype with two parameters against a
one-argument definition is a hard gcc error at every call site in the
self-host closure — the failure mode `test_gimple.py`'s docstring records
from the earlier drift of this same entry. Nothing in the ordinary
(non-self-host) path reaches it, which is why the everyday suites stay green
and only this check is red.

## Next step

1. `gimple_codegen.py:3131`: `('MojoList *', ['char *'])`.
2. `runtime/fire_runtime.h:1751`: `MojoList *py_tokenize(char *source);` and
   bring the comment at 1745-1748 back in line with the source.
3. `python3 test_gimple.py` — the same test then derives both from
   `inspect.signature`, so it cannot drift back silently.