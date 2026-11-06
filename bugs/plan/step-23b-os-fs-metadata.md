# plan/step-23b: os filesystem metadata: access + R_OK/W_OK/X_OK/F_OK, utime, symlink, link, mkfifo, umask
Class: mid      Size: M      Depends: 26      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §6.3-6.4 (host-import); round template and conventions are `bugs/plan/step-23-host-modules.md` (read it first; follow its "Work order" verbatim, items 3-7 are specialised below)

## Current state (measured; file:line verified 2026-11-05)
- Demand: `access` 3, `X_OK` 3, `W_OK` 2, `R_OK` 1, `utime` 2, `symlink` 3, `link` 1, `mkfifo` 2, `umask` 1.
- Wrappers present: `fs_access(p, mode)` (`_syscalls.mojo:608`), `fs_utimes(p, asec, ausec, msec, musec)` (:881, builds the timeval itself). Absent: symlink, link, mkfifo, umask.
- Status convention: `hoststatus` (step-26); `access` is a PREDICATE in CPython (returns bool), so it returns 1/0, not a status.

## Decisions already made
- `F_OK() -> int` 0, `R_OK()` 4, `W_OK()` 2, `X_OK()` 1 (POSIX values; assert each equals CPython's `os.R_OK` etc. in the test).
- `access(path, mode) -> int`: `1 if fs_access(path, mode) == 0 else 0`.
- `utime(path, atime, mtime) -> int`: integer seconds only (microseconds 0): `fs_utimes(path, atime, 0, mtime, 0)`; status. CPython's `times=None` (now) and float forms are NOT provided; docstring says so. (Do not add an overload.)
- `symlink(src, dst)`, `link(src, dst)` -> status via new `fs_symlink`/`fs_link`; `mkfifo(path, mode=0o666)` -> status via `fs_mkfifo`; `umask(mask) -> int` returns the old mask via `fs_umask`.
- Wrapper names collide with libc names; keep the `fs_` prefix (header point 1).

## Work order
1. Wrappers (four new) in `_syscalls.mojo`, next to `fs_rename`/`fs_unlink`.
2. API + constants in `os/__init__.mojo`, in the "Creating, removing and renaming" section (~line 940-1100).
3. Cases in `test_formal_os.py` group `fs` (line 579): build a fixture with the existing `make_fixture` (561); program performs the op; the TEST checks the result with CPython (`os.path.islink`, `os.readlink`, `os.stat(...).st_nlink`, `stat.S_ISFIFO`, `os.stat().st_mtime`); `umask`: program sets then reads back, compare to CPython's `os.umask` round trip in a fresh process.
4. Census + admitted per template.

## Do NOT
- Do not support `follow_symlinks=`/`dir_fd=`/`effective_ids=` keywords. Do not emulate `utime(None)`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py fs
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py os/__init__.mojo
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_admitted.py
```

## Done when
- [ ] all 9 names covered by `fs` cases on both backends
- [ ] census and admitted green

## If stuck
A function that will not bind on x86-64: drop only that function, record it under "Blocked" in step-23.md, land the rest.
