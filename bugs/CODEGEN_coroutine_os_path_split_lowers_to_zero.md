# CODEGEN: `os.path.split(p)` in a C++-emitted generator is lowered to `0.split(p)`

Found while working `CODEGEN_glob_bytes_pattern_returns_empty.md` (2026-11-01).

## Repro (measured)

With CPython's `glob.py` and `fnmatch.py` copied next to the driver (the `drv.py` below
imports `glob`), `fire.py build drv.py -o drv` fails:

    import glob, os

    ROOT = "<any directory>"

    def g_split(pathname, root_dir):
        dirname, basename = os.path.split(pathname)
        x = len(dirname)
        if not dirname:
            yield from glob._glob1(root_dir, basename, None, False)
            return
        yield pathname

    for n in g_split(b'*.py', ROOT.encode()):
        print(n)

    cc1plus: error: unable to find numeric literal operator 'operator""split'
    drv_gen.cpp:131:12:  (void)(0.split(pathname));

`drv_gen.cpp` is written only when a generator is emitted by the C++ coroutine emitter
(`mojo/backend_gimple/cpp_core.py`), so this generator takes that path.

## What is wrong

- `cpp_core.py`'s `_cpp_expr` `os.path.*` section has arms for `join`, `isdir`, `exists`,
  `isfile`, `basename`, `dirname`, `splitext`, `expanduser`, `abspath`, `islink`, `relpath`,
  `normpath`, but **no `split` arm**. The call falls through to the generic module-receiver
  path, so `os.path` is emitted as the opaque module marker `0` and the call as `0.split(p)`.
- The tuple-unpacking statement `dirname, basename = <call>` then takes the
  `_tup_is_unresolved_call` branch: it emits the call as a bare `(void)(...)` statement and
  assigns **every target `0`** (`dirname = 0; basename = 0;`). So even where the call compiles,
  the unpacked names are zero.

The GIMPLE path (`emit_methods.py`, the `os.path.split` arm near line 2526) does have a split
lowering (`int64_t_path_split`), which is why the same shape works in a plain function and in
the GIMPLE-emitted generators.

## Why it matters for glob

`_iglob` unpacks `dirname, basename = os.path.split(pathname)` as its first statement. In a
generator emitted this way `dirname` is `0`, so `not dirname` is true and `basename` is `0`,
which sends every glob down the `_glob1(root_dir, 0, ...)` branch.

## Next step

1. Add a `split` arm beside the `join` arm in `cpp_core.py`'s `os.path` section. A word
   argument should use the word-kinded runtime entry (`mojo_os_path_split_w`, see
   `CODEGEN_glob_bytes_pattern_returns_empty.md` Status); a str argument `int64_t_path_split`.
   Return the `MojoList *`.
2. In `_cpp_stmt`'s tuple-unpacking branch, treat a `split` call as a list-valued pair
   (`_tup_is_list_val`), so each target reads `mojo_list_get_int(list, i)`, and mark the
   targets as tagged words (`_cpp_mark_tagged_word`) so `not x` / `if x` use
   `mojo_truthy_word`.
3. Quick test: the repro above, run in a compiled program against CPython's output. It must
   print the same lines as CPython for `b'a/b.py'` and `b'*.py'`.

Status (2026-11-01): the `split` arm and the unpack change were drafted in `cpp_core.py` and
reverted before commit. The repro above was NOT re-run with them in place, so the change is
unverified and nothing is landed. The first step is to run the repro with the arm, confirm
it compiles and prints CPython's lines, then land the change with the test.
