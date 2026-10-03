# FORMAL_shlex_is_not_classified_as_a_host_module: a CPython standard-library module the build calls "not a stdlib module"

**Area:** FORMAL (module classification — `formal/imports.py`). **Status: OPEN,
one line, measured, not fixed.** Found on `construct:sweep5:hostmods-core`
(2026-10-02) while adding `contextlib`, whose one sweep row then stopped here.

## What I ran

```console
$ python3 fire.py build --formal --no-prove -o /tmp/x test_suite.py
build: test_suite.py imports 'shlex', which is not a stdlib or sibling module,
and no such file exists

$ python3 -c "import sys; sys.path.insert(0,'.'); import formal.imports as I
; print(repr(I.host_module_tier('shlex')), 'shlex' in I.HOST_MODULES)"
'' False
```

## What I saw, and what I expected

**Expected:** `shlex` is a CPython standard-library module, so it is a host
module, so it is in one of the two tiers and the build says which one.

**Saw:** it is in NEITHER tier, and the build falls through to module RESOLUTION
and reports `shlex` as "not a stdlib or sibling module". That sentence is false:
`shlex` is a standard-library module. It is the one diagnostic in this family
that misidentifies what kind of thing the name is, and it is a false statement
about the target — the failure mode the `no_public_api_reason` note in
`bugs/FORMAL_known_limits.md` was written to prevent, in a message nobody wrote
that rule for.

It is a HOLE in the table rather than a wrong entry: `subprocess`, `shutil` and
`glob` all classify, and `shlex` simply was never added. The consequence is that
`formal/imports.py` cannot answer "is this reachable, and why not" about it, so a
coverage report that consults `host_module_tier` counts it as neither tier.

## Which tier it belongs in, measured

`HOST_MODELLED`, not `HOST_UNREACHABLE` — `shlex` is pure computation over
strings:

```console
$ python3 -c "
import shlex, inspect
print(shlex.split('a b \"c d\"'))
print([l.strip() for l in inspect.getsource(shlex).splitlines()
       if l.startswith(('import ','from '))])"
['a', 'b', 'c d']
['import sys', 'from io import StringIO']
```

No subprocess, no thread, no socket, no foreign loader: it tokenizes a string with
a state machine, which is the same shape as `fnmatch` and `re` (both written).
`shlex.split`, `shlex.quote` and `shlex.join` are all answerable in principle.

## The exact next step

One line, in the "Pure computation over representable values" group of
`HOST_MODELLED` beside `fnmatch` and `difflib`:

```python
"shlex",
```

with a one-line comment in that set's established style naming what it would be
written in and what it could not do — the honest answer today is "a state machine
over a string, and `shlex.shlex` the streaming reader is a generator, which is the
`fnmatch.iglob` shape".

Then re-run `python3 tools/formal_sweep.py` and `test_suite.py` and the row moves
from a false "not a stdlib module" to `not-answerable/host-import`, which is what
it always was. Zero files build; the diagnostic stops being wrong.

**Why it is filed rather than fixed here:** `shlex` is not one of the four host
modules this worker's claim covers (`enum`, `contextlib`, `collections`,
`functools`), and `formal/imports.py` is being edited by at least three other
workers this round (`sweep5:admitted-hostmods`, `module:platform+fnmatch+
collections-rest`, and the `formal-land` merge). A one-line fix is still not worth
a merge conflict on a shared file for a problem that has a correct home.
