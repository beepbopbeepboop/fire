# Compiled `stat` has no mode constants, so any module touching `stat.S_IR*` dies at startup

## Status 2026-10-02 (work/bugs4-5): the "Next step" below is WRONG, and this
## doc's own conclusion is right for the wrong reason. The constants are NOT
## missing from the `stat` module — the compiled path cannot read ANY imported
## module's module-level constant, and `stat` is only where it was noticed.

Measured, with the out-of-tree stdlib that `module_loader.STDLIB_PATH` names:

    $ ls $STDLIB_PATH/std/stat/
    __init__.mojo  stat.aout  stat.mojo
    $ grep -nE "S_IR|S_IW|S_IF|S_IS" $STDLIB_PATH/std/stat/stat.mojo | head
    21: comptime S_IFMT = 0o0170000
    24: comptime S_IFDIR = 0o040000
    33: comptime S_IFREG = 0o0100000
    46: def S_ISLNK[intable: Intable](mode: intable) -> Bool:
    ...
    $ grep -c S_IRUSR $STDLIB_PATH/std/stat/stat.mojo
    0                       # the PERMISSION bits really are absent, as filed

So step 1's question ("confirm they are absent rather than misnamed") is now
answered: `S_IF*`/`S_IS*` are present, `S_IR*`/`S_IW*` are absent, both in the
same out-of-tree file. But the compiled path cannot reach the ones that ARE
there:

    # .tmp/fx/statmod.mojo
    import stat
    def main():
        print(stat.S_IFREG)
        print(stat.S_ISDIR(0o040755))
    main()

    compiled: Unhandled exception: AttributeError: S_IFREG      (exit 1)

and the generated C says why — the module's globals struct is EMPTY and the
read goes through the runtime dispatcher:

    _t1 = _root_globals.stat;      /* the struct field is a bare 0 */
    _t3 = _mojo_dispatch_getattr (_t2, "S_IFREG");

**Mechanism, measured against a control.** `import os; print(os.sep)` works,
and `sep` is a `comptime` in the same stdlib — but it is CONSTANT-FOLDED at
compile time to the literal `"/"`, so it never touches the globals struct:

    static char * _slit_10000 = "/";
    _t1 = _slit_10000;  mojo_print (_t1);

`sys.platform` is the same story (folded). `os.SEEK_SET`, `stat.S_IFREG` and
every other module-level constant has no such special case, so
`<module>.<constant>` lowers to a globals-struct field read plus a runtime
`_mojo_dispatch_getattr`, and that struct is populated for a hand-listed set of
modules only. A control in this repository — a two-file `import mymod` whose
module declares `comptime OCT = 0o17` / `comptime DEC = 15` — lowers the same
way as `stat`, so this is not about `stat`, octal literals, or the stdlib: it
is about `mod.NAME` for an arbitrary imported module.

**So the next step is in THIS repository, and it is bigger than the doc's step
2.** Adding `S_IRUSR` & co. to `stat.mojo` (out of tree, and not permitted from
a worker worktree) fixes nothing on its own: `stat.S_IFREG` would still raise.
What is needed is for an imported module's module-level `comptime`/constant
declarations to be visible to the compiled path — either by folding
`<module>.<NAME>` the way `os.sep`/`sys.platform` already are (the mechanism is
`module_gen.py`'s imported-module scan, `_gmi_find_comptime_one`, which today
runs for `from X import NAME` at line ~1673 and evidently not for `import X`
followed by `X.NAME`), or by populating `_root_globals.<module>` from the same
scan. Either way `stat` is the test case and not the subject.

Two things this does NOT change: `bugs/COMPILE_FAIL_Tools_c-analyzer_*`'s
`c_common/fsutil.py` sites still need the constants to EXIST, and the
`stdlib-dylib` skip-count comparison still applies.

## Status (2026-10-01 — NOT FIXABLE FROM THIS REPOSITORY; the fix site is out of tree)

Measured here rather than assumed, and the measurement changes what the next
session should do: **there is no `stat` module in this repository at all**, so
step 1 of the original "Next step" below cannot be taken from here.

    $ grep -rn "S_ISDIR\|S_ISREG\|S_IWUSR\|S_IFMT" --include=*.py --include=*.c --include=*.h .
    runtime/fire_runtime.c:8268:  return (stat(p, &st) == 0 && S_ISDIR(st.st_mode));
    runtime/fire_runtime.c:8389:  return (stat(p, &st) == 0 && S_ISREG(st.st_mode));
    ... (plus test/formal references)

Those are the *libc* `S_ISDIR`/`S_ISREG` used by `os.path.isdir`/`isfile`. There
is not one `S_IRUSR`/`S_IRWXG`/`S_IFMT` **Python-level** constant anywhere in
the tree — the compiled `stat` module's globals come from a stdlib that is not
part of this checkout:

    $ python3 -c "from module_loader import STDLIB_PATH; print(STDLIB_PATH)"
    /Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib

which is outside this repository (and outside the per-worker worktrees, which
are sandboxed to their own tree). The doc's other anchors are the same story:
`_c_common_toplevel` and `_parser__regexes_toplev` are named as the registries
this would be added to, and **neither name occurs anywhere in this tree**, so
they belong to that out-of-tree stdlib too.

So the fix belongs in the stdlib checkout that `module_loader.STDDLIB_PATH`
names: add the mode/flag constants to that `stat` module's source (or to the
module-globals registry it uses), and re-measure `c_parser/datafiles.py` there.
Nothing in this repository needs to change for it, which is why nothing in this
repository was changed.

**State: OPEN. NOT fixed — and not fixable from this tree.** The bug itself
(reproduced below by the reporter) is real and unchanged.

## Original report (2026-09-2x)

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
