# CODEGEN: `os.path.splitext(str)` splits at the last '.' anywhere in the path

Found 2026-11-02 while fixing the bytes os.path/len lowering (bytes read as text): the bytes
`splitext` (`mojo_os_path_splitext_w`) deliberately follows the same rule as the str one, so
bytes and str agree -- and both disagree with CPython.

## Expected (CPython, posixpath.splitext)

    os.path.splitext('a.d/b')[0]     # 'a.d/b'   (the only dot is in a directory name)
    os.path.splitext('.bashrc')[0]   # '.bashrc' (a leading dot of the basename is not an extension)

## Seen (by reading, not yet measured)

`runtime/fire_runtime.c` `int64_t_splitext` takes the LAST '.' in the whole string, ignoring
the '/' separator, so `'a.d/b'` gives root `'a'`, and `'.bashrc'` gives root `''`.

## Next step

1. Measure both lines above against CPython (`tools/mojo` / a compiled program) to confirm.
2. Fix `int64_t_splitext` to CPython's rule: find the last '/', take the last '.' after it, and
   only split when the basename has a non-dot character before that '.' (the leading-dot rule).
3. Make `mojo_os_path_splitext_w` (the bytes twin, runtime/fire_runtime.c) use the same rule in
   the same commit, then add both lines to a regression test next to
   `test_bytes_os_path_regress.py`.
