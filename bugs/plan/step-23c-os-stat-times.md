# plan/step-23c: os.path.getmtime/commonpath/sep and os.stat/lstat as per-field functions
Class: mid      Size: M      Depends: 26      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §6.3-6.4 (host-import); round template and conventions are `bugs/plan/step-23-host-modules.md` (read it first; follow its "Work order" verbatim, items 3-7 are specialised below)

## Current state (measured; file:line verified 2026-11-05)
- Demand: `os.path.getmtime` 7 files (the highest-demand missing name), `os.stat` 6, `os.lstat` 3, `os.path.commonpath` 1, `os.path.sep` 1.
- `os/path/__init__.mojo` already has per-field stat functions: `stat_mode(p, follow)` :597, `stat_size` :602, `stat_ino` :613, `stat_dev` :618, `stat_nlink` :633, `stat_uid` :638, `stat_gid` :643, `stat_blocks` :648, `stat_blksize` :653 (all over `fs_stat_field64/16/32` in `_syscalls.mojo`:1588+, which read byte offsets of the 64-bit `struct stat`; `fs_stat_layout_ok` guards the layout). No atime/mtime/ctime accessors.
- A value is one word; `os.stat()` returns an object, so it cannot be provided as such (same reason as `listdir`).

## Decisions already made
- Do NOT provide `os.stat`/`os.lstat` as functions. Provide in `os/path/__init__.mojo`: `stat_atime(p, follow)`, `stat_mtime(p, follow)`, `stat_ctime(p, follow)` (whole seconds, -1 on failure) and `stat_mtime_ns(p, follow)` (exact ns = sec*10^9+nsec, -1 on failure), reading the `st_*timespec` offsets exactly the way `stat_size` reads its offset (copy its helper; the offsets are in the Darwin `struct stat` and are identical for the 64-bit-inode symbol used on both arches).
- `getmtime(p)`: probe FIRST whether a `-> Float64` function crosses the module-dylib boundary and prints correctly on both backends (add a 3-line probe function `_probe_f() -> Float64` in a scratch test, not in the module). If YES: `getmtime(p) -> Float64` = seconds + nsec/1e9, and test against `os.path.getmtime` with equality of `float` bits. If NO: ship only the `stat_*` accessors and `getmtime_ns`, and write the Float64 boundary failure into this file's Status (it is a value-model fact, not this step's to fix).
- `commonpath(a, b)` ONLY the two-path form, returning `str` (CPython takes a sequence; a sequence is not a word). Port `posixpath.commonpath` for two args (raise-cases of CPython — mixing absolute and relative — return "" per hoststatus? NO: CPython raises ValueError; there is no status to invent: REFUSE by returning "" is forbidden. Implement only when both are absolute or both relative; for the mixed case follow the `os.makedirs` precedent: document that the mixed case is not provided and make the test skip it).
- `os.path.sep`: a zero-argument function `sep() -> str` returning "/" (the `os.sep` precedent at `os/__init__.mojo:145`).

## Work order
1. Accessors + `sep` + `commonpath` in `os/path/__init__.mojo`; `getmtime` per probe.
2. Cases in `test_formal_os.py` group `posixpath` (515) for `commonpath`/`sep` (oracle `posixpath` in-process) and group `fs` (579) for the time accessors (oracle `os.stat()` of the fixture; set mtime first with `os.utime` in the TEST so the value is deterministic).
3. Census + admitted per template.

## Do NOT
- Do not return truncated seconds under the name `getmtime` (it would differ from CPython's float silently).
- Do not provide stat_result-shaped tuples.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py posixpath fs
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py os/path/__init__.mojo
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_admitted.py
```

## Done when
- [ ] `stat_{a,m,c}time`, `stat_mtime_ns`, `sep`, two-path `commonpath` pass on both backends; `getmtime` passes or the probe result is recorded
- [ ] census/admitted green

## If stuck
If the timespec offsets differ between arm64 and x86-64 (they should not), record both offsets from `fs_stat_layout_ok`'s code and stop.
