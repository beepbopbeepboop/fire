# CODEGEN_generator_function: Lib/tarfile.py

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** — all 3 of
tarfile.py's own generator sites still compile cleanly (no "not
eligible" refusal). The `struct _genericpath_toplev` error quoted below
is GONE (fixed by `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_
fully_defined.md`'s "mechanism 2" landing, same fix confirmed elsewhere
in this session), but a DIFFERENT batch of tarfile.py's-own-code errors
has since surfaced — none inside a generator body:

```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:149:26: error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:754:7: error: 'SpecialFileError' has no member named 'tarinfo'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:1863:1: error: non-trivial conversion in 'var_decl'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2035:3: error: implicit declaration of function 'bz2_BZ2File___init__'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2403:1: error: non-trivial conversion in 'var_decl'
```

Not investigated further here (out of scope for this generator-codegen
cluster) — `:754`'s `'SpecialFileError' has no member named 'tarinfo'`
looks like it may be the same class of issue as `bugs/hard/CODEGEN_
dynamic_attribute_on_generic_object.md` (a custom exception subclass
setting an attribute not in its declared `__init__` fields — real:
`class SpecialFileError(...): def __init__(self, tarinfo): self.tarinfo
= tarinfo` or similar), and the `bz2_BZ2File___init__`/
`lzma_LZMAFile___init__` implicit-declaration errors look like a
transitively-imported-module symbol-resolution gap (likely conditional-
import related, `import bz2`/`import lzma` inside a `try:` block per
tarfile.py's own real source) — neither confirmed further, left for a
dedicated non-generator pass.

## Status (updated 2026-08-06, superseded above — struct_toplev error since independently fixed, different errors now present)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'TarFile'` .cpp error no longer reproduces. `tarfile.py` has
3 of its own generator sites (`getmembers`-adjacent `yield from
self.members`/`yield tarinfo` x2, lines 2999/3011/3024) — none appear in
the current error list, and `MOJO_DEBUG=1` shows no "not eligible"
refusal for any of them: tarfile.py's own generator bodies now appear to
compile cleanly through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore** —
this is `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md` (5th confirmed occurrence in this cluster):

```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:312:29: error: invalid use of undefined type 'struct _genericpath_toplev'
```
Not investigated further here — out of scope for this generator-codegen
cluster; see the hard-bug doc.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tarfile.py
