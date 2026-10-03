# FORMAL_stdlib_module_names_are_not_classified: 223 of CPython's stdlib module names are in neither host-module tier, so a build calls 120 public ones "not a stdlib module"

**Area:** FORMAL (module classification — `formal/imports.py`'s
`HOST_MODELLED` / `HOST_UNREACHABLE` / `HOST_ADMITTED`, and the wording of
`unresolvable_import_error`). **Status: OPEN, measured, not fixed.** One name
of the 223 was fixed while writing this
(`bugs/FORMAL_shlex_is_not_classified_as_a_host_module.md`); the other 222 are
here because one line is not a census and the census is not one session's
judgement call.

Found while fixing that one name, 2026-10-02, on `work/formal8-10`.

## What I ran

```console
$ python3 -c "
import sys, os; sys.path.insert(0,'.')
import formal.imports as I
probe = os.path.abspath('formal/arm64.py')
rows = [n for n in sorted(sys.stdlib_module_names)
        if n not in I.HOST_MODULES
        and not I.resolve_module_path(n, relative_to=probe, project_root=probe)]
print(len(rows))"
223
```

`sys.stdlib_module_names` is CPython's own list (3.10+), so the oracle is the
interpreter and not a remembered set: a name is a standard-library module here
exactly when CPython says it is.

## What I saw

| | count |
|---|---|
| `sys.stdlib_module_names` | **303** |
| …in a tier, or with a Mojo source that answers it | **80** |
| …in NEITHER tier and with no source | **223** |
| …of those, PUBLIC (no leading `_`) | **120** |
| …of those, CPython internals (leading `_`) | **103** |
| the tiers today | `HOST_MODELLED` 31, `HOST_UNREACHABLE` 22, `HOST_ADMITTED` 5 |

## What it costs, and it is not only the sentence

A name in no tier falls through `resolve_module_path` to the last resort and
is reported

```
build: test_suite.py imports 'shlex', which is not a stdlib or sibling
module, and no such file exists
```

which is false about the target — `shlex` is a standard-library module. That
is the visible half. The load-bearing half is `host_module_tier`, which
returns `''` for every one of the 223, so a coverage report counts them as
**neither** tier: not "unreachable because it needs a second process", and not
"reachable, not written yet". A reach report built on that cannot tell a
permanent fact about the target from a gap with an owner, which is the whole
reason the tiers were split (`formal/imports.py:593`'s docstring).

**Zero of the 223 build, and that is not a consequence of the missing entry.**
Each is refused by the tier-agnostic host-import refusal either way; the
classification changes the WORDING and the reach accounting, never an outcome.
That is worth stating because it is the reason this is cheap per name and
expensive as a set: nothing here can be fixed by adding entries in bulk
without reading each one.

## The next step, and it is a judgement per name, not a list

`formal/imports.py` states the rule once (`:95`): **does implementing it need
an object a freestanding image that links libSystem and NOTHING ELSE does not
have?** Apply it name by name. The split that falls out, with the readings
that are not obvious:

* **`unreachable`** — a second process (`multiprocessing`, `bdb`, `pdb`,
  `profile`, `cProfile`, `pstats`, `idlelib`, `venv`, `ensurepip`,
  `compileall`, `modulefinder`), a terminal (`curses`, `tty`, `pty`,
  `readline`, `rlcompleter`, `tkinter`, `turtle`, `cmd`, `wsgiref`), a socket
  or an internet client (`ftplib`, `imaplib`, `poplib`, `smtplib`,
  `socketserver`, `netrc`, `selectors`, `xmlrpc`), a library outside
  libSystem (`sqlite3`, `dbm`, `bz2`, `lzma`, `ssl`, `winsound`, `winreg`,
  `mmap`?), or the interpreter's own machinery (`pyexpat`, `opcode`, `symtable`,
  `dis`-adjacent, `faulthandler`, `tracemalloc`, `runpy`, `site`, `pydoc*`,
  `inspect`-adjacent, `builtins`).
* **`modelled`** — pure computation over values a word already is:
  `binascii`, `calendar`, `cmath` (integers only, as `math` is), `colorsys`,
  `configparser`, `copyreg`, `dataclasses`, `datetime` (the arithmetic, not
  `strftime` against the C library's locale tables), `difflib`-shaped text,
  `email` (header parsing, not SMTP), `getopt`, `gettext` (the catalogue walk
  is a file read; the `.mo` compilation is not), `graphlib`, `html`,
  `ipaddress`, `keyword`, `linecache`, `mailbox`, `mimetypes`, `optparse`,
  `plistlib`, `quopri`, `sched`, `shelve`, `statistics`, `string`,
  `stringprep`, `tarfile`, `termios`, `timeit`, `tomllib`, `tokenize`,
  `unicodedata`, `wave`, `zipapp`, `zipfile`, `zipimport`, `zoneinfo` (with
  the tz database read through `os`, which exists), `contextvars`,
  `annotationlib`.
* **neither tier, deliberately** — a name whose only spelling is a
  documentation or test artefact (`this`, `antigravity`, `turtledemo`,
  `idlelib`), or a Windows-only / POSIX-only module that is not this host's
  (`msvcrt`, `winreg`, `nt*`, `posix`, `genericpath`, `nturl2path`). Those
  want a third answer or an explicit exclusion list, which is a decision
  about the table rather than a classification — and it should be recorded as
  one, not left to look like an oversight.

**Which of the 120 a swept file actually imports** is the number that decides
how much of this is worth doing, and it is cheap: the sweep's per-file import
lists already exist (`formal/imports.py`'s `imported_modules`, and the
`not-answerable/host-import` rows in `tools/formal_sweep.py`'s report). Until
that is counted, 120 is an upper bound and the honest statement is that
**`shlex` was the one a real file in this repository imports.**

## Why this is filed and not fixed here

* It is 222 judgement calls in `formal/imports.py`, which three other workers
  were editing in this same round — a bulk change to the two tier sets is a
  merge conflict on every hunk and a reach-accounting change nobody can review.
* The tiers are a CLAIM about the target, and CLAUDE.md's rule is that a claim
  is made by the rule and by nothing else. Filling them in by category from a
  distance is exactly the failure mode the comment at `:101` warns about
  ("never because it happens to be unimplemented").
* One name is already done, with its test, in
  `test_formal_imports.py::test_a_stdlib_module_in_no_tier_is_not_reported_as_a_typo`
  — which is the shape the rest of the names want, and which a bulk change
  could reuse rather than reinvent.

## Reproducing every number here

```console
$ python3 -c "
import sys, os; sys.path.insert(0,'.')
import formal.imports as I
probe = os.path.abspath('formal/arm64.py')
pub = [n for n in sorted(sys.stdlib_module_names)
       if n not in I.HOST_MODULES
       and not I.resolve_module_path(n, relative_to=probe, project_root=probe)
       and not n.startswith('_')]
print(len(pub), 'public stdlib names in no tier')"
120 public stdlib names in no tier
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove -o .tmp/x test_suite.py
build: test_suite.py imports 'shlex', which is a host module (CPython
standard library), which has no Mojo source for this backend to compile
```