# plan/step-23a: os process identity: getpid, getppid, getuid, getpgid, cpu_count
**Status: DONE 2026-11-05 (verified).** `os.getpid/getppid/getuid/getpgid/cpu_count` added (`fs_getppid/getuid/getpgid/sysconf` wrappers in `_syscalls.mojo`). The build needed C-return prototypes: `getppid`/`getpgid` `(32, True)`, `getuid` `(32, False)` (uid_t is unsigned), `sysconf` WORD, in `formal/model/layout.py::BARE_C_RETURN_KINDS`. New group `proc` in `test_formal_os.py` runs the image as a child on BOTH backends (x86-64 under Rosetta) and compares with CPython's view of that child. hostmods census unchanged at 90/92. Not run: `test_formal_admitted.py` (needs the library build). Unrelated and pre-existing: `test_formal_libc_symbol.py` x86_64 `stat` row reads `st_ino` at the wrong offset (13/14).
Class: mid      Size: S      Depends: 26      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §6.3-6.4 (host-import); round template and conventions are `bugs/plan/step-23-host-modules.md` (read it first; follow its "Work order" verbatim, items 3-7 are specialised below)

## Current state (measured; file:line verified 2026-11-05)
- Demand (distinct repo files): `getpid` 20, `cpu_count` 10, `getpgid` 4, `getuid` 1, `getppid` 1. None is defined in `formal/hostmods/os/__init__.mojo` (its `def` list is at lines 145-1407).
- `fs_getpid() -> int` already exists (`os/_syscalls.mojo:997`) and `signal.mojo:190` imports it, so `getpid` is a one-line wrapper. `getppid`, `getuid`, `getpgid`, `sysconf` have NO `fs_*` wrapper (`grep -o '^def fs_[a-z_0-9]*' formal/hostmods/os/_syscalls.mojo` lists the 55 that exist).

## Decisions already made
- Add wrappers `fs_getppid()`, `fs_getuid()`, `fs_getpgid(pid)`, `fs_sysconf(name)` to `_syscalls.mojo` (each calls the libc function of the same name; bare names collide with the API names, hence the wrappers: header point 1). Then in `os/__init__.mojo`: `getpid()`, `getppid()`, `getuid()`, `getpgid(pid)` all `-> int`.
- `cpu_count() -> int` = `fs_sysconf(58)` (`_SC_NPROCESSORS_ONLN` is 58 on Darwin; verify: `python3 -c "import os;print(os.sysconf_names['SC_NPROCESSORS_ONLN'])"`). CPython may return None; this returns the count, always >= 1 (a Python-side `None` has no word representation — say so in the docstring).
- These answers are the host's, so each gets an `@admitted` contract ONLY if `test_formal_admitted.py` requires one for a host-dependent return; otherwise none (decide by running it).
- Oracle for pid-valued functions: the test cannot compare to its own pid. Run the built image under `subprocess.Popen`, read its printed `getpid()`, require == `popen.pid`; `getppid` == `os.getpid()` of the test process; `getuid` == `os.getuid()`; `getpgid(0)` == `os.getpgid(0)` of the child's group via `os.getpgid(popen.pid)`; `cpu_count` == `os.cpu_count()`.

## Work order
1. Wrappers in `_syscalls.mojo` (mirror `fs_getpid`, line 997).
2. API functions in `os/__init__.mojo` with docstrings.
3. New group `proc` in `test_formal_os.py` (register in its group list at ~line 786 `main`), both backends (copy how group `env` builds for both: line 715).
4. Census + admitted per template.

## Do NOT
- Do not return a constant or cache a pid. Do not implement `os.getlogin`/`getgroups` (not in demand).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py proc
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py os/__init__.mojo
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
```

## Done when
- [ ] group `proc` passes on arm64 and x86_64 (5 functions)
- [ ] census and admitted green, no pin widened

## If stuck
If `sysconf` will not bind on x86-64 (see `model.target_libc_symbol` for the symbol table), ship the other four, record cpu_count under "Blocked" in step-23.md, stop.
