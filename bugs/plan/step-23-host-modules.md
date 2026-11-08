# plan/step-23: host-module growth: the per-module round template and the ranked queue
**Status: DONE 2026-11-08 (measured).** The round template is what 23a-23e executed, and all five rounds landed or are closed with a reason: 23a DONE (getpid, getppid, getuid, getpgid, cpu_count), 23b DONE (access, utime, symlink, link, mkfifo, umask, F_OK..X_OK), 23c DONE with two recorded deviations (stat times), 23d CLOSED AS 'NOT PROVIDED' (file-descriptor I/O: no writable-descriptor producer exists), 23e DONE (kill, killpg, setsid, defpath, and the documented refusals for fork/exec/wait/system). `test_formal_os.py`: 12/12 groups pass on the current tree. Future module rows (the ranked queue) follow the work order below verbatim, one module per round.

Class: mid      Size: S      Depends: 26      Blocks: 23a, 23b, 23c, 23d, 23e
Source: `bugs/FORMAL_known_limits.md` §6.3-6.4 (host-import); `bugs/sweeps/sweep-arm-14-after-the-max-min-fix.txt` lines 753-760

## Current state (measured; file:line verified 2026-11-05)
- The draft's "os is 79 of the 160" is STALE. In the latest committed sweep (`sweep-arm-14-after-the-max-min-fix.txt:753`) `not-answerable/host-import` is 214 files and the by-module line has NO `os`:  `importlib x98, collections x43, unittest x24, copy x12, inspect x7, importlib.util x6, types x6, builtins x3, socket x2, tokenize x2, asyncio x1, atexit x1, fractions x1, functools x1, multiprocessing x1, plistlib x1, pwd x1, resource x1, sqlite3 x1, unittest.mock x1, uuid x1`. Line 756: 72 of 214 are "in reach" (a Mojo-side module could provide them); line 757 names them: `collections, copy, fractions, functools, inspect, resource, types, uuid`. The blocked files are mostly this repo's own `.py` tools/tests.
- `os` already has a hostmod (`formal/hostmods/os/__init__.mojo`, 1421 lines, 70+ functions). What `os` still LACKS is measured from demand in this repo's own Python (script run 2026-11-05 over `*.py`, `tools/*.py`, `formal/*.py`, `mojo/**/*.py`, counting `os.X` / `os.path.X` attributes not defined in the hostmod; number = distinct files): `getpid`20 `close`11 `kill`11 `cpu_count`10 `open`7 `stat`6 `O_RDWR`6 `O_CREAT`6 `fdopen`4 `killpg`4 `getpgid`4 `symlink`3 `access`3 `lstat`3 `fork`3 `write`3 `X_OK`3 `fsync`3 `utime`2 `read`2 `W_OK`2 `O_RDONLY`2 `urandom`2 `mkfifo`2 `waitpid`2 `_exit`2 `ftruncate`2 plus 1-file names (`getuid pipe umask dup2 uname link system getloadavg getppid setsid execv execvp wait4 WEXITSTATUS SEEK_SET fsencode defpath R_OK O_TRUNC O_WRONLY`). `os.path` lacks `getmtime`7 `commonpath`1 `sep`1. These are split into steps 23a-23e (one round each).
- Other hostmods that already exist (do NOT recreate): `ls formal/hostmods` (42 files incl. `collections.mojo`, `copy.mojo`, `functools.mojo`, `importlib.mojo`).
- The rule that makes a contract legal: `formal/admitted.py` — a contract may constrain the host's ANSWER, never mechanism; `test_formal_admitted.py` `SCOPE_PROBES` and the `truth` group are the instrument. A FALSE contract is the worst outcome.
- Existing ranking instruments (read, do not rewrite): `tools/formal_host_import_wall.py` (columns reach/alone/sweep), `tools/formal_host_import_shapes.py` (what a blocked file spells, WORD vs not).

## Decisions already made
- ONE MODULE (or one named group of os functions) = ONE ROUND = ONE COMMIT. Never two modules in a commit.
- Failure convention: every new status-returning function uses `hoststatus.status_ok()/status_err()` (step-26, `formal/hostmods/hoststatus.mojo`); no exceptions; no invented statuses where CPython has none.
- Constants are zero-argument functions (`os/__init__.mojo` "A CONSTANT IS A CALL"), named exactly as CPython's constant (`O_RDWR()`), one-line docstring.
- Every function carries `-> int` or `-> str` (manifest signature); every libc call goes through a `fs_*` wrapper in `os/_syscalls.mojo` (name-collision rule in its header, point 1).
- A function whose answer is not one 64-bit word (tuple, list, stat_result) follows the blob pattern of `listdir`/`listdir_len`/`listdir_get`/`listdir_free` (os/__init__.mojo:1108-1240) or a per-field function (`stat_mode(p, follow)` style, os/path/__init__.mojo:597-653). No new value-model capability.
- A function that cannot be expressed (needs a process model: `fork`, `exec*`, `wait*`, `system`) is NOT implemented: it is listed in step 23e as a documented refusal with the host limit named; do not stub it returning 0.

## Work order  (the round template; 23a-e and any future module row follow it verbatim)
1. P0: `python3 -c "import formal.model"` works (HEAD had `NameError: threading` at `formal/model/layout.py:3155`; see step-26 P0).
2. Fresh ranking (no sweep needed; seconds): `python3 tools/memslot.py --gb 8 --label t -- python3 tools/formal_host_import_wall.py --min 1 --sweep bugs/sweeps/sweep-arm-14-after-the-max-min-fix.txt`; take the row for your module and note `alone`. For a NEW module pick the top row whose name is in the "in reach" line (line 757 above) and has no `formal/hostmods/<name>.mojo` OR whose file exists but is missing names: `python3 tools/formal_host_import_shapes.py --files <name>` lists the names blocked files spell; keep only `WORD`-shaped ones.
3. Write the module/functions in `formal/hostmods/<module>.mojo` (or `os/__init__.mojo` + `_syscalls.mojo` wrappers). Docstring per function: CPython behaviour, return convention citing hoststatus.
4. Differential test: add cases to the module's existing `test_formal_<module>.py` (os -> `test_formal_os.py`, groups `fs`/`env`/`dirs`; build+RUN on BOTH backends with CPython as oracle, copy an existing group's helper usage exactly). A module with no test file gets `test_formal_<module>.py` modelled on `test_formal_os.py`'s `build`/`run`/`parse`.
5. Build census: `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py <path relative to hostmods>` (both backends).
6. Contracts: only if a function's answer is the host's (clock, pid, cpu count): `@admitted` per `formal/admitted.py` docs, and read `test_formal_admitted.py` failures to add rows from measurement (S4 rule: never widen a pin).
7. Re-run the wall tool; paste the module's before/after `alone`/`reach` into the commit message.

## Do NOT
- Do not hand-write a conformance claim: CPython is the oracle, rows are generated by asking it.
- Do not add a module to `formal/hostmods/` that shadows a name `fire.py`/`module_loader.py` imports at the repo root (see os/__init__.mojo header).
- Do not touch `lib/*.lean` or `formal/arm64_*`; this lane is Mojo source + tests only.
- Do not implement `fork`/`exec*`/`wait*`/`system` (23e).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py          # os rounds
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
```

## Done when  (per round)
- [ ] every added function answers CPython on both backends in the module's test file (count in commit message)
- [ ] census green on both backends; admitted counts unchanged or updated from measurement
- [ ] wall tool's `alone` for the module fell (or, for os, the "lacks" list above lost the names)

## If stuck
Write the exact failing function and error into this file's Status (append "Blocked: <module> <function> <message>") and stop; do not partially land a function that does not match CPython.

## Safe for iceman
All of 23a-23d and 23e's documentation. The ranking in step 2 is mechanical; module choice beyond os is a pick-the-top-row rule, so no latitude.
