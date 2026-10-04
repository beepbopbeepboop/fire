# FORMAL_stdlib_module_names_are_not_classified: 223 of CPython's stdlib module names are in neither host-module tier, so a build calls 120 public ones "not a stdlib module"

**Area:** FORMAL (module classification — `formal/imports.py`'s
`HOST_MODELLED` / `HOST_UNREACHABLE` / `HOST_ADMITTED`, and the wording of
`unresolvable_import_error`). **Status: the FALSE SENTENCE is fixed for all 223
and the 222 judgements are still to do — with the coverage question answered, and
the answer is ZERO.**

Found while fixing that one name, 2026-10-02, on `work/formal8-10`.

## 0. What landed, 2026-10-03 (`work/formal10-4`)

**The wording, which is the half that was a lie.** `shlex` was fixed by adding
ONE tier entry, while the question its diagnostic was really asking — "is this
name in the standard library?" — has an oracle: CPython's own
`sys.stdlib_module_names`. Answering it from the hand-kept tiers made the build
say, of a module CPython ships:

```console
$ python3 fire.py build --formal --no-prove -o .tmp/a a.mojo     # `import binascii`
build: a.mojo imports 'binascii', which is not a stdlib or sibling module,
and no such file exists
```

`formal/imports.py::is_cpython_stdlib` now asks the oracle in the place that
decides the WORDING, and `unresolvable_import_error` has three arms:

| the name | what the build says |
|---|---|
| in a tier | "a host module (CPython standard library), which has no Mojo source for this backend to compile" — unchanged, and it carries `host_module_advice` |
| CPython ships it, no tier names it | "a CPython standard-library module, which has no Mojo source in this tree and no tier … saying whether implementing it would need an object this target does not have — so nothing here can say whether it is reachable" |
| CPython does not ship it | "not a stdlib or sibling module, and no such file exists" — the only sentence that may say it |

**And `tools/formal_sweep.py`'s `_is_cpython_stdlib` is deleted as a copy.** It
existed precisely because the build's message was wrong, and read
`sys.stdlib_module_names` to correct a verdict the build had already printed — a
report disagreeing with the message it reports on. Its own docstring records the
cost: "36 of them would otherwise be filed as unresolved imports". It is now a
delegation, so the build and the report cannot come apart.

`_is_host_module` is deliberately NOT the place: it answers "is this one of the
names we have CLASSIFIED", which includes every module with a `formal/hostmods/`
source — `math`, `stat`, `shutil`, `fcntl`, `platform` all answer False there
and are pinned False by their own suites. One oracle, two questions, and both are
asked where they are used.

**One red this area was already carrying, fixed here because the area's own
semantics settle it.** `test_formal_link_accounting.py`'s `test_host_tiers`
asserted that a name may enter the host set only if it has real source, and it
has been red since the `shlex` fix (`c5bbd0b3`, 2026-10-02) — `shlex` entered
`HOST_MODELLED` with no `formal/hostmods/shlex.mojo` behind it. The invariant's
premise is wrong for that tier and the measurement says so: **all 31
`HOST_MODELLED` names have no source in this tree**, which is what the tier's own
comment means by "reachable in principle, not implemented today, and therefore a
gap with an owner". So the requirement is now asserted where it means something —
an addition to `HOST_UNREACHABLE` (a permanent fact about the target) or to
`HOST_ADMITTED` (a name that ANSWERS under declared contracts) — and a
`HOST_MODELLED` addition is held only to the rule the check already stated: it
was being MISCLASSIFIED.

## 0.1 The coverage question, answered: ZERO

§"The next step" says "which of the 120 a swept file actually imports is the
number that decides how much of this is worth doing, and it is cheap … Until that
is counted, 120 is an upper bound". Counted, on this tree, with
`formal/imports.py`'s own `imported_modules` over every `.mojo` file in this
repository and the stdlib:

```
223 names in no tier (120 public, 103 private)
370 .mojo files scanned
0 of the 223 are imported by ANY of them
```

**So the classification is worth nothing for coverage, and that is the finding
that decides what to do with the 222.** It is not an emergency and it is not
invisible either: the tier sets are the CLAIM about the target, and a claim is
made by the rule and by nothing else, so filling 222 entries by category from a
distance is the failure the comment at `:101` warns about — and with nothing
importing them there is no measurement to tell a right entry from a plausible
one. The honest shape is what landed: the diagnostic is true, the unclassified
names are named as unclassified (so a coverage report counts them as "no verdict"
rather than as either tier), and the queue for the 222 is a bounded piece of
per-name work with the readings §"The next step" already lists.

## 0.2 What landed on the second pass (`work/formal18-6`): §0.1's measurement is
now a TEST, and one sentence that claimed more than the code did was corrected

**The open question in §"The next step" — "which of the 120 a swept file actually
imports is the number that decides how much of this is worth doing … Until that is
counted, 120 is an upper bound" — is now answered permanently and in the
direction that decides it.** `test_formal_imports.py::
test_no_unclassified_stdlib_name_is_imported_by_anything` walks every `.mojo` file
in this repository **and** in the stdlib, parses each with
`formal/imports.py`'s own `parse_module_for_closure` + `imported_modules`, and
asserts that not one of them imports a CPython standard-library name that no tier
classifies and no module answers:

```
217 names in no tier (no `host_module_tier`, no `resolve_module_path` hit)
>100 .mojo files scanned (this repository + ../new-modular/Mojo/stdlib/std)
0 files import one of them
```

1.8 s, no build, no Lean, and it is a **tripwire with a direction**: the day a
file imports `binascii`, it goes red and the fix is to place the name by the
rule in `formal/imports.py` — which is the only thing that can answer the
question the new consumer has asked. Until then the 217 are inert, which is the
measurement §0.1 made and the reason this doc's remaining work is not urgent.

**Two details of that test that are load-bearing, because the obvious version of
it is wrong:**

* **"in no tier" is not `host_module_tier(n) == ''`.** A name this tree has
  WRITTEN leaves its tier (that is `formal/imports.py`'s own rule), so `os`,
  `sys` and `os._syscalls` all answer `''` while being the three most-imported
  modules in the corpus. The set is the doc's own — no tier AND no module —
  resolved through `resolve_module_path`, which is also what makes a SUBMODULE of
  an answered package (`os._syscalls`) count as answered. The first version of
  the test used the tier alone and reported 11 consumers, every one of them a
  module that is written.
* **the stdlib half is optional and the repository half is not.** The stdlib
  lives outside this repository, so it is walked only when present and the
  repository is always walked: "there is no corpus here" must not print the same
  word as "every consumer of these names is classified", which is the reason
  `test_formal_mlir_precedence.py`'s census returns SKIPPED rather than PASS.

**And one sentence in the area was false and is now true.**
`formal/imports.py::_host_tier_conflicts`'s docstring claimed it reported "names in
both tiers, and (for auditing a future edit) names in neither". The code has only
ever returned the intersection, and the "neither" half is not implementable as
written: 217 names are in neither tier by design, so asserting that half empty
would be a red suite rather than a discipline. The docstring now says what the
function returns, says why the other half cannot exist, and points at the test
above as the place the "neither" question is actually kept.

**What is still not done, unchanged:** the 217 per-name judgements. §0.1's
reason still stands — nothing imports them, so there is no measurement to tell a
right entry from a plausible one, and filling them by category from a distance is
the failure `formal/imports.py:101` warns about. The census test is what makes
that deferral safe rather than merely convenient: the work is now queued by the
consumer that arrives, not by a reader's guess about which names matter.

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

## Why the 222 are filed and not fixed here

* It is 222 judgement calls in `formal/imports.py`, which three other workers
  were editing in this same round — a bulk change to the two tier sets is a
  merge conflict on every hunk and a reach-accounting change nobody can review.
  §0.1 adds the reason that survives the round ending: ZERO corpus exposure, so
  there is no measurement to tell a right entry from a plausible one.
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