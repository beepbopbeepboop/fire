# plan/step-23d: os file-descriptor I/O: close, read, write, fsync, ftruncate, dup2, pipe, O_*/SEEK_SET constants
Class: mid      Size: M      Depends: 26      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §6.3-6.4 (host-import); round template and conventions are `bugs/plan/step-23-host-modules.md` (read it first; follow its "Work order" verbatim, items 3-7 are specialised below)

## Current state (measured; file:line verified 2026-11-05)
- Demand: `close` 11, `open` 7, `O_RDWR` 6, `O_CREAT` 6, `write` 3, `fsync` 3, `read` 2, `O_RDONLY` 2, `ftruncate` 2, `pipe` 1, `dup2` 1, `O_TRUNC` 1, `O_WRONLY` 1, `SEEK_SET` 1, `fdopen` 4.
- Existing wrappers: `fs_close`, `fs_read`, `fs_lseek`, `fs_open_ro` (`_syscalls.mojo`; grep `^def fs_`). The `_syscalls.mojo` header (stdio paragraph) says THIS PATH LOWERS `open` ITSELF and refuses the C library's spelling of the three-argument `open` — so a general `os.open(path, flags, mode)` may be impossible. Read `fs_open_ro`'s docstring before anything else.

## Decisions already made
- Order inside the round: (1) constants (zero-arg functions) `O_RDONLY() 0`, `O_WRONLY() 1`, `O_RDWR() 2`, `O_CREAT() 0x200`, `O_TRUNC() 0x400`, `SEEK_SET() 0`, each asserted equal to CPython's value in the test (Darwin values; the assertion makes it self-checking); (2) `close(fd)`, `read`/`write` ONLY if a bytes-free spelling exists: `write(fd, s) -> int` takes a `str` (NUL-terminated; bytes with NULs are not provided — docstring), `read` is NOT provided (returns bytes: unrepresentable, see 23e table); (3) `fsync(fd)`, `ftruncate(fd, n)`, `dup2(a, b)` -> status/int via new `fs_*` wrappers; `pipe()` -> NOT provided (returns a tuple; provide `pipe_read_fd(p)`/`pipe_write_fd(p)` ONLY if the blob pattern fits in <= 20 lines, else refuse in 23e).
- `os.open`: if `fs_open_ro`'s docstring says the three-argument call is refused, `os.open` is NOT provided (23e table) and `O_*` constants are then dead code: skip them too and record that in Status. Do not paper over by always opening read-only.
- `fdopen` returns a file object: NOT provided (23e table).

## Work order
1. Read `fs_open_ro`; decide per Decisions; record the decision in the commit message.
2. Wrappers + API as decided; new test group `fd` in `test_formal_os.py`: the TEST creates a temp file, the program uses a path-based fd obtained by whatever IS provided, writes/fsyncs/closes; the TEST reads the file back with CPython and compares.
3. Census + admitted per template.

## Do NOT
- Do not return a fake fd. Do not implement `read` returning `str` (binary data corrupts at NUL).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py fd
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py os/__init__.mojo
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_admitted.py
```

## Done when
- [ ] every function that IS provided passes group `fd` on both backends; every one that is not is named in Status with its reason
- [ ] census/admitted green

## If stuck
If no fd can be obtained at all (open refused), land only the constants-free subset (`close`, `fsync`, `dup2` over fds 0-2 in the test) or nothing; write "Blocked: os.open" with the exact lowering message and stop.
