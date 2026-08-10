# CODEGEN_generator_function: Lib/tarfile.py

## Status (updated 2026-08-09)

Re-verified again against current master with a fresh real rebuild
(`MOJO_DEBUG=1 python3 mojo.py build .../Lib/tarfile.py`, real
`gcc-mp-15`/`g++-mp-15` via `mojo.py`'s own resolution — not a hand
invocation). Classification UNCHANGED: **NOT a generator-codegen-cluster
failure**. Confirmed via `MOJO_DEBUG=1`: all 3 of tarfile.py's own
generator sites (`TarFile.__iter__`'s `yield from self.members` /
`yield tarinfo` x2, lines 2999/3011/3024) — no "not eligible" refusal
logged for any of them; every "not eligible" line in this build's debug
output names a generator/async function in a DIFFERENT, transitively-
imported module (e.g. `ItemsView.__iter__`, `_unpack_opargs`,
`findlinestarts`, `Flag._iter_member_by_value_`, `WeakValueDictionary.
items`, `iter_fields`), never `TarFile.__iter__` or anything else from
tarfile.py itself.

The error set has shifted again since the last note: the previous
`:1863:1`/`:2403:1` "non-trivial conversion in 'var_decl'" pair is GONE
(both those source lines now only produce ordinary unused-variable/
unused-label warnings), replaced by one new error:
```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2418:27: error: unexpected RHS for assignment before ';' token
```
at `return _NAMED_FILTERS[filter]` inside a `try:`/`except KeyError:`
(`TarFile._get_extraction_filter`) — a dict-subscript **read** inside a
`return` inside a `try` body. (Note: this is a different shape from the
dict-subscript *augmented-assignment* mis-codegen fixed by commit
`0b6394a`/"Fix bug31" just before this session started — that fix was
for `dict[k] += v`; this is a plain `return dict[k]` inside try/except.
Not investigated further — out of scope for this generator-codegen
pass.) The rest of the previously-documented error set is unchanged:
```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:149:26: error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:151:26: error: assignment to 'char *' from 'int' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:754:7: error: 'SpecialFileError' has no member named 'tarinfo'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2035:3: error: implicit declaration of function 'bz2_BZ2File___init__'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2040:3: error: implicit declaration of function 'bz2_BZ2File_mojo_close'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2063:3: error: implicit declaration of function 'lzma_LZMAFile___init__'
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:2068:3: error: implicit declaration of function 'lzma_LZMAFile_mojo_close'
```
Still none of these are inside tarfile.py's own generator bodies. Not
investigated further here — same out-of-scope non-generator issues
(exception-subclass attribute, conditional `import bz2`/`import lzma`
symbol resolution, dict-subscript-in-try codegen) as previously noted.
No code change made in this pass.

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
