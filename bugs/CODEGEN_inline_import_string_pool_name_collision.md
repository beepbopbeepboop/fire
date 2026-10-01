# Compiled inline-import: an imported module's string-literal pool collides with another's

**State: OPEN. NOT fixed. Found while building a CPython-comparison fixture
for the foreign-generator-handle work; unrelated to it, and it only became
reachable because that work made such a module compile at all.**

Two imported modules inlined into one translation unit each emit their own
`static char * _slit_NNNNN = ...` for the SAME N, and each also emits a
forward `static char * _slit_NNNNN;`. In one TU that is a redefinition error.

## What I ran and what I saw

`compile_to_gimple(..., do_imports=True)` over a package whose imported
sibling yields strings:

```python
# pkg/mystrutil.py
def _iter_significant_lines(lines):
    for line in lines:
        line = line.partition('#')[0]
        if not line.strip():
            continue
        yield line

# pkg/main.py
from . import mystrutil
def read_table(lines, *, sep=','):
    sig = mystrutil._iter_significant_lines(lines)
    yield next(sig)
    for rest in sig:
        yield rest
def main():
    for row in read_table(['a  # x', '  ', 'b', 'c']):
        print(row)
main()
```

`gcc -fgimple` on the emitted `.c`:

```
pkg/mystrutil.py:238:15: error: redefinition of 'char* _slit_10000'
pkg/mystrutil.py:234:15: note: 'char* _slit_10000' previously declared here
pkg/mystrutil.py:239:15: error: redefinition of 'char* _slit_10001'
pkg/mystrutil.py:235:15: note: 'char* _slit_10001' previously declared here
```

Both fragments come from `mystrutil.py` itself — line 234/235 are the
module's forward declarations, 238/239 its definitions — so this is not
merely two siblings colliding: within ONE imported module's emitted text the
same `_slit_N` name is declared and then defined again. In C, `static char *
x;` followed by `static char * x = "...";` in the same TU is a redefinition.

Expected: an inline compile of a package whose sibling yields strings
produces a `.c` that `gcc -fgimple` accepts.

## Why it is not in the way of the existing suites

`test_gimple_runner.py`'s two-file helper and `test_module_cache.py`'s
cross-module tests all use imported siblings with few or no string literals,
so their `_slit_` numbering never overlaps. It is reached the moment a
sibling has more than a handful of string constants AND is compiled inline.

## Next step

1. Find where `_slit_<N>` names are allocated for an imported module and
   confirm the forward declaration and the definition are emitted by two
   different passes that each run their own counter over the same module.
   `gimple_codegen._dedup_guarded_blocks` / `_dedup_variadic_externs` in
   `mojo/backend_gimple/emit_infra.py` are the existing post-processing
   hooks for exactly this class of duplicate; a `_slit_`-specific dedup there
   may be all it takes, since `static char * _slit_N;` followed by
   `static char * _slit_N = ...;` for the SAME N is safe to drop.
2. If the counters genuinely restart per module, prefer making the counter
   shared (`temp_gen` already shares most registries — see the sharing block
   in `mojo/backend_gimple/emit_resolve.py:_compile_imported_module`) so the
   names can never collide in the first place; dedup is the fallback, not the
   fix.
3. Regression: a CPython-comparison package fixture with a string-yielding
   sibling generator (the repro above), asserting the compiled binary's
   stdout equals CPython's `'a  \nb\nc\n'` — which is also what pins the
   `next`/`for` consumption halves the sibling-generator fix relies on.
