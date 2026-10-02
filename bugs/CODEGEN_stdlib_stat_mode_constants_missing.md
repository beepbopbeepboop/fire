# Compiled `stat` has no mode constants, so any module touching `stat.S_IR*` dies at startup

**State: OPEN. NOT fixed. Found while re-verifying
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_datafiles.md`; a separate bug
from that one, which is now fixed.**

The compiled path's `stat` module exposes none of the `S_I*`/`S_IW*` mode
constants, so the FIRST attribute read of one raises — and a module-level
constant expression is exactly where real code meets it.

## What I ran and what I saw

`c_parser/datafiles.py` now builds cleanly (`fire.py build` exits 0, zero
gcc errors, zero imported-module fallbacks — see that doc's Status). Its
binary does not run:

```
$ python3 fire.py build .tmp/ca/c_parser/datafiles.py -o df2
Built: .../df2
$ ./df2
Unhandled exception: AttributeError: S_IRUSR
$ echo $?
1
```

CPython, same sources, imports fine:

```
$ cd .tmp/ca && python3 -c "import sys; sys.path.insert(0,'.'); import c_parser.datafiles; print(datafiles.BASE_COLUMNS)"
['filename', 'funcname', 'name', 'kind']
```

The site is a MODULE-LEVEL constant, which is why it fires at startup before
any of the analysed code runs:

```python
# c_common/fsutil.py:324
S_IRANY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
# c_common/fsutil.py:439
if mode & stat.S_IRUSR:
```

`fsutil` is reachable from `c_common.tables` -> `c_parser.datafiles` and from
`c_parser.info`, so every c-analyzer module that compiles at all pays this at
runtime.

## Why this is its own bug

It is not a COMPILE_FAIL (the constant is not a compile error — the module
compiles), and it is not the `fsutil` COMPILE_FAIL another worker holds: that
doc's subject is `fsutil`'s own generators refusing, which is untouched here.
This is a missing surface on the compiled `stat` module, i.e. a stdlib
coverage gap like the ones CLAUDE.md's `stdlib-dylib` `skip <module>:`
count guards — except this one is loud (a raise at startup) rather than
silent, which is why it has not been hiding behind a skip count.

## Next step

1. Find where the compiled `stat` module's globals are populated (the same
   registry `_c_common_toplevel`/`_parser__regexes_toplev` structs come
   from — `runtime/fire_runtime.c` plus the stdlib module source) and confirm
   `S_IRUSR`/`S_IRGRP`/`S_IROTH` are simply absent rather than misnamed.
2. Add the full `stat` mode + flag surface as module-level globals:
   `S_IMODE`, `S_IFMT`, `S_IFREG`, `S_IFDIR`, `S_IFLNK`, `S_IFCHR`,
   `S_IFBLK`, `S_IFIFO`, `S_IFSOCK`, `S_ISUID`/`S_ISGID`/`S_ISVTX`, and the
   full `S_IRWXU`/`S_IRWXG`/`S_IRWXO`/`S_ISUID`/`S_ISGID`/`S_ISVTX` grid.
3. A CPython-comparison regression per constant:
   `import stat; print(stat.S_IRUSR, stat.S_IFREG | 0o644)` compiled vs
   interpreted vs CPython. One representative is enough to fail the suite;
   the rest are the same code path.
4. Check `compile_stdlib.py`'s `EXPECTED_FAILURES` / the `stdlib-dylib`
   `skip` count before and after — a `stat` constant that was previously
   stubbed or skipped may now compile cleanly, which would be a good sign and
   should show as a DECREASE in skips.
