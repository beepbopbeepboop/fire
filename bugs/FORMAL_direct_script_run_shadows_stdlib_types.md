# FORMAL: running any `formal/*.py` as a script imports `formal/types.py` as the stdlib `types`

Since `formal/types.py` landed (967a456ed, 2026-11-03), every direct script run of a
`formal/` module dies at import, and with it every suite job that runs one:
`formal-x86-endtoend`, `formal-x86-model`, `formal-x86-machine-model` (and every
other `[PY, 'formal/<script>.py']` registration).

## What was run

    python3 formal/x86_64_endtoend_test.py formal/examples/six_params.mojo

the exact argv of the `formal-x86-endtoend` job (via `tools/memslot.py --gb 8` and
via `checked_run.py`, both of which spawn the child with the inherited environment
and no path tweaks — `tools/memcap.py:112` is a bare `Popen`, `checked_run.py:371`
a bare `subprocess.run`).

## What was seen

    File "formal/x86_64_endtoend_test.py", line 138, in <module>
        import re
    File ".../lib/python3.15/re/__init__.py", line 126, in <module>
        import enum
    File ".../lib/python3.15/enum.py", line 3, in <module>
        from types import MappingProxyType, DynamicClassAttribute
    File "formal/types.py", line 14, in <module>
        from dataclasses import dataclass
    ...
    AttributeError: partially initialized module 'enum' ... has no attribute 'IntEnum'

On this host (Python 3.15.2). The mechanism is version-independent: a script run
puts its own directory on `sys.path[0]`, so the stdlib's `enum` — imported by the
very next `import re` — resolves `types` to `formal/types.py`. On Python 3.12 the
same chain ends in `ImportError: cannot import name 'MappingProxyType' from
'types' (…/formal/types.py)` instead: `formal/types.py` defines neither, so it
crashes there too, just one frame later. `python3 formal/x86_64_model_coverage_test.py`
fails identically (line 67, `import re`), which is also the job's documented
`Run:` line.

## What was expected

The `Run:` lines in the three files, and the three suite registrations, to run.

## Why it is safe to note, and the workaround

`python3 -m formal.x86_64_endtoend_test formal/examples/six_params.mojo` (from the
repo root) works: `sys.path[0]` is the cwd, `formal/types.py` resolves as the
package module `formal.types`, and nothing shadows the stdlib. The 2026-11-18
measurement of `six_params`' live hole went through this form.

## Next step

Change the three registrations to module form — `[PY, '-m', 'formal.x86_64_endtoend_test']`
and its siblings — or give those jobs `env={'PYTHONSAFEPATH': '1'}` (the stdlib's
safe-path switch; `checked_run.py` and `memcap.py` both pass the environment
through). Then run `python3 tools/suite.py formal-x86-endtoend formal-x86-model
formal-x86-machine-model` once to see the three jobs run again, and check no other
`[PY, 'formal/…']` registration was missed (the arm64 side has the same shape).
