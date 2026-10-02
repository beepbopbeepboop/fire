# A module global rebound inside a function: reading it BEFORE the reassignment

## What was run

```sh
python3 fire.py build .tmp/g1/m.py      # the distilled build-installer shape
python3 tools/scan_globals.py           # the census below
```

## What was seen

```python
FW_PREFIX = ["Library", "Frameworks", "Python.framework"]
FW_VERSION_PREFIX = "--undefined--"     # the placeholder
FW_SSL_DIRECTORY = "--undefined--"

def parseOptions():
    global FW_VERSION_PREFIX, FW_SSL_DIRECTORY
    FW_VERSION_PREFIX = FW_PREFIX[:] + ["Versions", "3.14"]
    FW_SSL_DIRECTORY = FW_VERSION_PREFIX[:] + ["etc", "openssl"]

def main():
    print(FW_VERSION_PREFIX)           # runs BEFORE parseOptions()
    print(FW_SSL_DIRECTORY)

main()
```

`main()` is called at module scope, so both `print`s read the globals before
`parseOptions()` has replaced them. Compiled: **SIGSEGV**. Under
`Mac/BuildScript/build-installer.py` itself this costs nothing, because its
placeholder is never read before `parseOptions()` runs — but the compiled
answer is a segfault, not a wrong value, and that is a memory-safety failure
rather than a modelling gap.

## Cause

`fa85e923` gives a multi-kind global a BOXED C FIELD (`int64_t`) and the
SEMANTIC type of the kind the function bodies store (`MojoList *` here). That
is right for every read that happens after the reassignment, which is the
shape the real file uses. A read before it gets the later kind, and:

```
_t = _root_globals.FW_VERSION_PREFIX;     /* an int64_t holding a char *   */
_t2 = (MojoList *)_t;
_t3 = mojo_repr_list_ints (_t2);         /* reads a string as a MojoList  */
```

`mojo_repr_list_ints` reads `->len` and `->data` out of a `char *` and then
walks `data[0..len)` — that is the fault, and `len` is whatever the first 8
bytes of the string literal happened to spell.

## Why it is not fixed here

The correct representation is the box PLUS runtime discrimination, and the
runtime has registries for the three container kinds
(`mojo_is_registered_list` / `_dict` / `_set`) but **none for `char *`**: a
boxed string is not distinguishable from a boxed scalar integer. So the
registry dispatch that would answer this correctly does not exist, and adding
one means touching `runtime/fire_runtime.{c,h}` — shared machinery that other
workers hold (the `coro` suite drives `runtime/test_fire_coro_gen.c` against
the same translation unit), which is not a light worker's trade.

The two answers that need no new runtime support are both one-sided, which is
why neither is landed: keeping the module-level kind is wrong after the
reassignment (and is why the file did not compile at all), and the current
choice is wrong before it.

## Blast radius, measured

The pass that produces this shape fires on **nothing** in either corpus that
matters:

```
$ python3 .tmp/scan_globals.py                 # the Mojo stdlib
files scanned: 610
multi-kind globals: 0
```

and the same scan over the **262 `.py` files of this compiler's own
self-hosting closure** (what `--dump-full fire.py` compiles) reports
`multi-kind globals: 0`. So the shape is reachable only from a sentinel-global
idiom like the one above, which today does not compile at all. This is the
measure to re-run after any change to that pass; it is cheap because it is a
parse plus a `_quick_type`, not a compile.

## Next step

1. Register `char *` in the same way the three container kinds are (one
   registry node per live `mojo_str`/`cstr` value), then
2. route `_repr_boxed_container` and the boxed-consumer arms through a
   `mojo_is_registered_str` arm, and mark the read-back temp of a
   multi-kind global as a boxed container when the function has no
   store-provenance for it (`_actual_types` is per-function, so a read in a
   *different* function than the store is indistinguishable from a read
   before it) — which also fixes the sibling case, a read in another
   function than the reassignment, which has the same segfault today.
3. Re-run `scan_globals.py` over both corpora afterwards.