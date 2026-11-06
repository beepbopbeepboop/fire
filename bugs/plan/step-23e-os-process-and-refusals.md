# plan/step-23e: os signals/process-group wrappers and the documented NOT-PROVIDED table
Class: mid      Size: S      Depends: 26, 23a      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §6.3-6.4 (host-import); round template and conventions are `bugs/plan/step-23-host-modules.md` (read it first; follow its "Work order" verbatim, items 3-7 are specialised below)

## Current state (measured; file:line verified 2026-11-05)
- Demand: `kill` 11, `killpg` 4, `setsid` 1, `defpath` 1; process-model names: `fork` 3, `waitpid` 2, `wait4` 1, `_exit` 2, `execv` 1, `execvp` 1, `system` 1, `WEXITSTATUS` 1; non-word returns: `urandom` 2 (bytes), `uname` 1 (tuple), `getloadavg` 1 (tuple), `fsencode` 1 (bytes), `fdopen` 4, `read` 2.
- `fs_kill(pid, sig)` exists (`os/_syscalls.mojo:1002`; imported by `signal.mojo:190`). No `killpg`/`setsid` wrapper.

## Decisions already made
- PROVIDE: `kill(pid, sig) -> int` (status; wraps `fs_kill`), `killpg(pgid, sig) -> int` (new `fs_killpg`), `setsid() -> int` (new `fs_setsid`; returns the new session id or status_err), `defpath() -> str` returning ":/bin:/usr/bin" (compare to CPython's `os.defpath` in the test; if it differs, use CPython's value).
- NOT PROVIDED, documented (no stub, no fake): `fork, waitpid, wait4, _exit, execv, execvp, system, WEXITSTATUS` — need a process model/exec; host limit: "a freestanding image has no process-control model (no unwinder, no wait status object)". `urandom, fsencode, read` — return `bytes` (no word representation; see `types.py` `BYTE_BLOB_TYPE_CTORS` refusal text). `uname, getloadavg, pipe` — return tuples (use `platform` for uname). `fdopen` — file object.
- Put the table in the `os/__init__.mojo` module docstring as a new bullet "NOT PROVIDED, and why" (name, reason, 1 line each), and pin it: the test builds `import os` + a call to ONE name from each reason class (`os.fork()`, `os.urandom(4)`, `os.uname()`, `os.fdopen(1)`), records the actual refusal message FIRST (UNVERIFIED — worker must measure: build each and print the message), then adds `refuse:<needle>` rows to `test_formal_os.py` with exactly that needle, both backends. If a call BUILDS and silently links an undefined symbol, that is a bug: write it to `bugs/FORMAL_no_exceptions.md` Status and stop.
- Oracle for `kill`: spawn `sleep 30` with `subprocess.Popen` in the TEST, run the image with its pid as an argument or env var, then require `popen.poll() == -sig` after `wait()`. Use signal 15 only; a 0 signal for the existence probe (status ok vs err for a nonexistent pid 2**22 - 1... choose a pid just dead: spawn+wait a child, use its pid).

## Work order
1. Wrappers (2) + API (4) + docstring table; 2. test group `proc2` (kill/killpg/setsid/defpath) and the four refuse rows; 3. census + admitted per template.

## Do NOT
- Do not signal pid 0 or negative pids other than a test-owned process group. Do not call `kill` in the test against anything the test did not spawn.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py proc2
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py os/__init__.mojo
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
```

## Done when
- [ ] kill/killpg/setsid/defpath pass on both backends; four refuse rows pass with measured needles
- [ ] docstring table lists every name above

## If stuck
If a not-provided call builds instead of being refused, stop and record it as above.
