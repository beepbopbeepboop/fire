# CODEGEN: `self.x is None` answers False after a conditional closure store (unexplained trigger)

## Status (2026-10-29 — found while probing zipfile's `_ZipDecrypter`; trigger NOT yet isolated)

**Observed silent miscompile.** Compiled output differs from the interpreter
(and from CPython). Exit code 0, so nothing else catches it.

Repro (`.tmp`-free copy below; build with `python3 fire.py build -o <out> <file>`):

```python
_crctable = None
def _gen_crc(crc):
    for j in range(8):
        if crc & 1:
            crc = (crc >> 1) ^ 0xEDB88320
        else:
            crc >>= 1
    return crc


def _ZipDecrypter(pwd):
    key0 = 305419896
    key1 = 591751049
    key2 = 878082192

    global _crctable
    if _crctable is None:
        _crctable = list(map(_gen_crc, range(256)))
    crctable = _crctable

    def crc32(ch, crc):
        return (crc >> 8) ^ crctable[(crc ^ ch) & 0xFF]

    def update_keys(c):
        nonlocal key0, key1, key2
        key0 = crc32(c, key0)
        key1 = (key1 + (key0 & 0xFF)) & 0xFFFFFFFF
        key1 = (key1 * 134775813 + 1) & 0xFFFFFFFF
        key2 = crc32(key1 >> 24, key2)

    for p in pwd:
        update_keys(p)

    def decrypter(data):
        result = bytearray()
        append = result.append
        for c in data:
            k = key2 | 2
            c ^= ((k * (k^1)) >> 8) & 0xFF
            update_keys(c)
            append(c)
        return bytes(result)

    return decrypter


class ZipExtFile:
    def __init__(self, pwd=None):
        self._pwd = pwd
        self._decrypter = None
        if self._pwd:
            self._decrypter = _ZipDecrypter(self._pwd)


def main():
    z = ZipExtFile()
    print(z._decrypter is None)      # CPython: True.  Compiled: False.
    z2 = ZipExtFile(b"abc")
    d = z2._decrypter
    print(len(d(b"xyz")))            # CPython: 3.     Compiled: 3.


main()
```

Expected (CPython and `fire.py run`): `True` then `3`.
Compiled (`fire.py build`, post the `emit_funcs`/`emit_calls` boxed-capture
fix on this branch): `False` then `3`.

**What does NOT reproduce it** (so the trigger is something in this shape):
a minimal `Holder` with `self._dec = None` then a conditional
`self._dec = make(...)` whose `make` returns a closure gives `True` correctly
(both with and without a `self._pwd` guard). The difference in the failing
program is the `global _crctable` / `list(map(...))` prologue and the
`nonlocal`-boxed `key0..key2` in the returned closure's factory.

**Next step:** bisect the repro above by deleting one piece at a time
(`global`/`_crctable` prologue first, then the `update_keys` nonlocal writer),
checking `is None` each time; then dump the generated C for `ZipExtFile.__init__`
and see what type `_decrypter` got (it must be a pointer-or-int slot, and
`None` must compile to the NULL value that `is None` compares against).
