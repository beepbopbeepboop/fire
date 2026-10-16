# FORMAL_stdlib_module_names_are_not_classified: 223 of CPython's stdlib module names are in neither host-module tier, so a build calls 120 public ones "not a stdlib module"

**Status 2026-10-07, landed in parallel by `work/formal114-docs`,
`work/formal135-docs`, `work/formal155-docs`, `work/formal175-docs` and
`work/formal181-docs` (which dated its own measurement 2026-10-08): the FIVE
names §0.5 said the `find_spec` oracle decides are in `HOST_UNREACHABLE`.** §0.5 measured the oracle's split and named
`_gdbm`, `_tkinter`, `_overlapped`, `_winapi` and `_wmi` as "the first entries a
worker could add with a measurement behind each"; all five are placed, by the
rule at the top of `formal/imports.py` applied rather than a new category.
`importlib.util.find_spec` returns no spec for every one here, and the object
each is missing is one a freestanding image cannot have (`_gdbm`/`_tkinter` need
a library outside libSystem, a fact about the TARGET; the other three are
Windows-only, so their no-spec measurement is host-independent). All five are
private, so the PUBLIC unclassified count moves by zero — five per-name
judgements with an oracle, not a moved row. The merge kept the five ONCE:
`formal/imports.py` and `test_formal_link_accounting.py::HOST_SET_ADDED_TIERS`
carried a duplicate set from each side, and the 10-07 paragraph's test pointer
(`test_the_five_gdbm_style_names_are_unreachable`) was already stale on master —
the row that pins the tier, the verdict, and (for the three whose absence is
host-independent) the no-spec measurement is
`test_formal_imports.py::test_the_five_find_spec_decided_names_are_unreachable`.
Re-measured on the merged tree 2026-10-12 (CPython 3.14.8): `unclassified 231`,
`unreachable 27` (was 22), `modelled 32`, `admitted 4`, `not-a-module 3` — the
205→200 unclassified reading in the 10-07 paragraph is a point-in-time one, and
the queue grows with the interpreter's own `stdlib_module_names` list, not with
any tier removal in this repo. **What is still not done is unchanged:** the
remaining per-name judgements, which §0.1's ZERO-corpus-exposure measurement
says cannot be told apart from plausible ones without a consumer to measure
against.

**Area:** FORMAL (module classification — `formal/imports.py`'s
`HOST_MODELLED` / `HOST_UNREACHABLE` / `HOST_ADMITTED` / `HOST_NOT_A_MODULE`,
and the wording of `unresolvable_import_error`). **Status: the FALSE SENTENCE is
fixed for all 223, §"The next step"'s THIRD-ANSWER bullet is LANDED with an
oracle and two corrections (§0.3, 2026-10-05), and §0.5 (2026-10-05) settles
35 more of the queue by a RULE — 30 of them by a derivation that reads this
repository and needs no judgement about the target at all, 5 by the `find_spec`
measurement §0.3 proposed — **and FALSIFIES the other half of that proposal,
which is why the remaining 170 are still a queue and not a bulk edit.** The two
gate verdicts that matter here are unchanged: `test_formal_imports.py` 89/0
(83 before this pass, the two new ones being the rule's whole specification)
and `test_formal_link_accounting.py` 299/299.**

**Status 2026-10-08 (`work/formal205-docs`): §0.5's named next step is TAKEN for
the five names `find_spec` decides.** `_gdbm`, `_overlapped`, `_tkinter`,
`_winapi` and `_wmi` are now in `HOST_UNREACHABLE` — `importlib.util.find_spec`
returns NO SPEC for each on this host, so the object (the gdbm library, Tcl/Tk,
and the Windows overlapped-I/O, Win32 API and WMI objects) is missing from the
target, which is the rule at the top of `formal/imports.py` applied. They are
carried in `test_formal_link_accounting.py::HOST_SET_ADDED_TIERS` with their
tier, and pinned by
`test_formal_imports.py::test_the_find_spec_decided_names_are_unreachable`. All
five are private, so the PUBLIC unclassified count is unchanged; the
`unclassified` count falls 205 → **200**. The other 200 are still §0.1's
per-name judgements with no corpus exposure, and this does not change that.

**Status 2026-10-05 (`work/formal54-docs`): §0.1's measurement RE-CONFIRMED on a
corpus 20% larger, the per-verdict census REFRESHED (this document's stated
counts were stale), and `find_spec` measured as the oracle it is claimed to be —
it decides FIVE of the 205.** All three are in §0.5; none of them moves a file,
and §0.1's reason for the remaining 200 is unchanged and is re-measured here
rather than asserted.

Found while fixing that one name, 2026-10-02, on `work/formal8-10`.

## 0.5 35 of the 216 are decided by a RULE, and the other half of §0.3's
## oracle is REFUTED by the measurement it asked for

**§0.3 ended with a next step that is half right, and this section is the
measurement that shows which half.** Its words: *"That oracle is available for
the rest too, and is the next step for anyone who takes them — a name whose spec
CPython cannot find here is `unreachable` by the rule, and a name whose spec it
can is `modelled` unless the content is not code. That is 103 per-name
judgements with an oracle rather than a judgement."*

**The first clause is right and is now landed as a rule over every name.** The
second is **false**, and it is false in a way that would have put a name in the
wrong tier of a CLAIM ABOUT THE TARGET. A spec exists for `sqlite3`, `ssl`,
`bz2` and `lzma` — all four are pure-Python packages — and all four need an
object this target does not have:

| the name | `find_spec` | what it actually needs | `tools/formal_stdlib_reach.py` |
|---|---|---|---|
| `sqlite3` | a spec EXISTS (pure python) | `libsqlite3.dylib`, via `_sqlite3` | `library` |
| `ssl` | a spec EXISTS | `libssl.3.dylib`, `libcrypto.3.dylib` | `library` |
| `bz2` | a spec EXISTS | `libbz2.1.0.dylib`, via `_bz2` | `library` |
| `lzma` | a spec EXISTS | `liblzma.5.dylib`, via `_lzma` | `library` |

So "its spec can be found ⇒ `modelled`" would have claimed four names reachable
that the rule at the top of `formal/imports.py` calls `unreachable`, **and the
same clause in the other direction is just as wrong**: `_hashlib` links
`libcrypto.3.dylib` and `_decimal` links `libmpdec.4.dylib`, neither of which is
in libSystem — so a rule that reads CPython's *dynamic dependencies* would call
both `unreachable`, while `hashlib` is answered here by
`formal/hostmods/hashlib.mojo` and `decimal` is `HOST_MODELLED`. **A library
outside libSystem is a fact about CPython's PACKAGING; an object the target does
not have is a fact about the TARGET, and only the second is a tier.** Those two
rows are why the derivation below reads this repository's tables and asks the
interpreter nothing at all — the accelerator question is never asked, because
the tables already carry the answer that matters and are the claim.

### What landed, and it is a rule rather than 35 remembered entries

**`formal/imports.py::capability_sibling_tier` — 30 names, decided from THIS
tree, with no judgement about the target.** CPython splits a capability across a
public module and a private accelerator for it, so implementing `_hashlib` is
implementing what `hashlib` needs, and the tier that answers for the public name
answers for the private one:

| derived | from | tier | and the reverse case |
|---|---|---|---|
| `_socket`, `_warnings`, `_locale`, `_asyncio`, `_sysconfig` | `socket`, `warnings`, `locale`, `asyncio`, `sysconfig` | `unreachable` | — |
| `_hashlib`, `_decimal`, `_bisect`, `_csv`, `_datetime`, `_pickle`, `_queue`, `_struct`, `_stat`, `_json`, `_io`, `_random`, `_uuid`, … | a public module this tree has answered or placed | `modelled` | — |
| `_ctypes` | `ctypes` (`HOST_ADMITTED`) | `modelled` | a foreign-code loader this tree answers under declared contracts, so the capability is REACHABLE even though `ctypes` cannot be computed |

Three properties a merely-plausible version would get wrong, each with its own
check: **`admitted`/`written` become `modelled` and never themselves**
(`HOST_ADMITTED`'s membership rule is "there is a `formal/hostmods/` source", and
`_ctypes` has none — returning `admitted` would claim a file that is not there);
**a public name derives nothing**, so the rule can never answer a question with
itself; and **it is asked after all four tables**, so it cannot contradict a
hand-kept tier.

**The five `find_spec` placements, and they are the rule the four Windows names
already were.** Asked of every name CPython ships, `importlib.util.find_spec`
answers no spec for exactly five more of the queue: `_winapi`, `_overlapped`,
`_wmi`, `_tkinter` (the Tk binding `tkinter` is unreachable for) and `_gdbm`
(the GNU dbm binding `dbm` picks when it is there, and here it is not). A target
is a SUBSET of this host, so a name this host's own CPython cannot provide is a
name nothing here could have implemented, whatever the backend does.

| | before | after |
|---|---:|---:|
| `unclassified` | **205** | **170** |
| `modelled` | 32 | 57 |
| `unreachable` | 22 | 32 |
| …and `written` / `admitted` / `not-code` / `front-end` | 30 / 4 / 3 / 1 | 30 / 4 / 3 / 1 |

**Measured on this tree by re-running `host_module_verdict` over
`sys.stdlib_module_names` with the derivation switched off and the five names
taken back out** — before and after from ONE reader, because two numbers from
two implementations is the property §0.2 records getting wrong once already.

**No build outcome changes, and that is the property the split rests on.** Both
arms of `unresolvable_import_error` REFUSE the import either way; what moves is
the WORDING and the reach accounting. `_is_host_module` is the one predicate that
had to change, and only because `unresolvable_import_error`'s unclassified arm
says *"no tier in `formal/imports.py` saying whether implementing it would need
an object this target does not have"* — a sentence a derived answer makes
false. It now asks `host_module_tier` instead of reading the union, so `_hashlib`
gets the host-module sentence, which is true of it.

### The 170, and why they are still a queue: three mechanisms, measured

**The residue is not 170 judgements waiting for patience. It is 170 judgements
waiting for a reading of the MODULE that no reading of this host can supply**,
and that is a measurement rather than an opinion — a scan of every pure-Python
module's own import closure, with `formal/imports.py`'s facility vocabulary
(`subprocess`, `curses`, `socket`, `ctypes`, …) applied at every edge:

1. **An import behind `if TYPE_CHECKING:` or a platform test is not an import
   the target takes.** `_colorize` reads `nt` under one, and `_colorize` is
   imported by `calendar`, `_pyrepl` and `pdb` — so the naive closure calls
   `calendar` unreachable through a Windows-only `nt` that the closure itself
   also reports as absent. A reader has to know that an edge inside a type-only
   or platform-only arm is not an edge.
2. **An OPTIONAL import is not a dependency.** `cmd` does `try: import readline
   except ImportError: pass`, so a `cmd` without line editing is implementable
   here; the closure says `cmd` needs a terminal. The same shape in `mimetypes`
   (`_winapi`) and `pty` (`select`).
3. **A library outside libSystem is the CAPABILITY's, not the module's.** §the
   table above: `_hashlib`'s `libcrypto` is a packaging fact, and the capability
   is implemented in this tree.

Each is a per-name reading, and each is cheap once you know which one you are
looking at — which is why the honest next step is the queue with a direction,
and not a bulk edit. **What is now available and was not: `tools/formal_stdlib_reach.py`
prints the evidence row for every name in the queue** (`find_spec`'s answer, the
kind of implementation CPython gives it, every library it binds outside
libSystem, and the public sibling the derivation consulted), and `--check`
asserts the two invariants this section landed so a CPython that moves a module
between a `.py` and a `.so` cannot quietly put the tables and the tool apart.

### Reproducing every number above

```console
$ python3 tools/memslot.py --gb 8 --label reach -- \
      python3 tools/formal_stdlib_reach.py --check
OK: 0 problem(s); 170 name(s) in no tier
$ python3 tools/memslot.py --gb 8 --label reach -- \
      python3 tools/formal_stdlib_reach.py --name sqlite3 --name _hashlib --name _socket
name                     answer        kind     libraries outside libSystem            why
sqlite3                  unclassified  source
_hashlib                 modelled      binary   libcrypto.3.dylib                      derived from hashlib
_socket                  unreachable  binary                                          derived from socket
$ python3 test_formal_imports.py -v          # 89/0; the two new cases are named
formal imports: PASS=89 EXPECTED=0 SKIP=0 FAIL=0
$ python3 test_formal_link_accounting.py     # 299 checks, 0 failed
```

## 0.4 `not-code`: the fourth tier's answer stopped sharing a string with the
## typo answer, and two red tests on `master` are the measurement

**§0.3 closed the tier. It left one STRING meaning two things, and two checks on
`master` were red because of it.** `HOST_NOT_A_MODULE` is a fourth TIER and
`host_module_tier` answers `'not-a-module'` for its members — meaning "this
module's content is not code". `host_module_verdict`'s `'not-a-module'` means
"nothing here provides it **and CPython does not ship it** — a typo or a gap in
this repository". For `this`, `antigravity` and `turtledemo` the second sentence
is **false**: CPython ships all three, `sys.stdlib_module_names` says so, and
`importlib.util.find_spec` finds each on this host (`test_formal_link_accounting.py`'s
ledger, and §0.3's own measurement). So a name CPython ships was reported with
the answer whose sentence is the typo sentence, and both consumers of the verdict
acted on it:

```
$ python3 test_formal_imports.py -v          # on master, before this section
FAIL  every name has one named verdict, and no answer is an absence
        CPython ships this, so no verdict can say nothing here provides it —
        that answer is the TYPO sentence's, and it is false of a standard-library module
FAIL  the wall instrument separates reach from alone
        alone for `abc` was 2: it is the only wall on one of the two files that name it
```

The second failure is the one that says what it cost. `tools/formal_host_import_wall.py::
_is_wall` takes its wall set from the verdict and its whitelist was
`(modelled, unreachable, admitted, unclassified)`, so the three names were
invisible to it — and `alone` is computed over the names the predicate
recognises, so a file importing `abc` **and** `antigravity` read as though `abc`
were its ONLY wall. That is the statement the `alone` column exists to make true.

**The fix is an eighth answer, `'not-code'`, and nothing else moves.**
`host_module_verdict` gives `HOST_NOT_A_MODULE` members `'not-code'` — "CPython
ships it and its content is not code" — and `'not-a-module'` keeps its own
sentence, which is now true of every name that gets it. `host_module_tier` is
UNCHANGED (its fourth answer is about CONTENT, and its string names the SET
rather than the verdict), so `test_formal_link_accounting.py`'s ledger of the
eleven names §0.3 settled still reads as it was written. `_is_wall` gains
`'not-code'`, because **the BUILD refuses an import of each one** and that is the
measurement rather than a judgement — one build per name, each with its own
sentence:

```
build: w.mojo imports 'this', which is a CPython standard-library module with no
content to compile — it is documentation or a demonstration, not an API — so there
is nothing here to implement and nothing for the link step to provide
```

same for `antigravity` and `turtledemo`, and `unresolvable_import_error`'s arm for
them is unchanged. `test_formal_imports.py` 80 → **83 checks, 0 failed**
(`test_a_module_whose_content_is_not_code_is_still_a_wall` is new, and it pins
both halves — the verdict's answer and the instrument's predicate — plus a build,
because either half alone would pass with the other broken);
`test_formal_link_accounting.py` 289/289, `test_refusal_taxonomy.py` 347/347,
`test_formal_sweep_truth.py` OK, `test_suite.py` 335/335.
`tools/formal_sweep_causes.py`'s legend paragraph, which described the OLD
string by the tier's meaning, now names both.

**`master` carried a DIFFERENT answer for the same two red tests, and this
section is where that was decided** (`work/merge-formal39`, 2026-10-05). It had
gone green by (a) **widening** `'not-a-module'` to also mean "`HOST_NOT_A_MODULE`
claims it", with the partition invariant relaxed to a pair, and (b) **skipping**
every `HOST_NOT_A_MODULE` member in `_a_real_wall_name` and in the `wall_b`
fixture, on the stated ground that "`antigravity` is not a wall — it is a name
the table says has no content to compile". Move (a) is exactly the collision this
section removes, one string with two sentences; move (b) is what made the suite
green WITHOUT fixing the instrument, because the fixture no longer contained the
name that measured the defect, and `_is_wall` still dropped it. So the merge took
`'not-code'`, restored the strict invariant (a shipped name can never reach the
TYPO sentence, which is now a fact about the code rather than about a table), and
dropped both skips so `test_the_wall_instrument_separates_reach_from_alone`
exercises the `not-code` case again. `host_module_verdict`'s table counts EIGHT
answers, which is the count `tools/formal_host_import_wall.py` and
`test_formal_imports.py` now also state.

**What this section does not do, and it is §0.1's measurement again.** No
repository or stdlib file imports any of the three (re-measured over
`tools/formal_host_import_wall.py`'s own 749-file walk: none appears in the
table), so the ranking's NUMBERS are unchanged and this fix is the honesty of one
answer plus the correctness of an instrument, not a moved row. The 102 public
names still in no tier are still in no tier, and §0.1's reason is unchanged: with
nothing importing them there is no measurement to tell a right entry from a
plausible one.

## 0.5 Re-measured 2026-10-05 (`work/formal54-docs`): the corpus question still
## answers ZERO on 443 files, this document's census was stale, and `find_spec`
## decides five names

Three measurements, all through `formal/imports.py`'s own accessors, and none of
them moves a build. They are here because the census this document states in
three places had drifted, and because §"The next step" offers `find_spec` as
"the oracle" for the remaining names and that claim had never been measured.

**1. §0.1's number is a FLOOR and it still holds, on 20% more corpus.** §0.1
measured `223 names in no tier / 370 .mojo files scanned / 0 of the 223 imported
by ANY of them`. Re-measured with `host_module_verdict` + `parse_module_for_closure`
+ `imported_modules` over every `.mojo` in this repository **and**
`../new-modular/Mojo/stdlib/std`:

```
unclassified names: 205
mojo files scanned: 443
files importing one: 0
```

443 files against the 370 the doc measured, and still zero — so the tripwire
`test_formal_imports.py::test_no_unclassified_stdlib_name_is_imported_by_anything`
has not fired, and §0.1's conclusion ("the classification is worth nothing for
coverage, and that is the finding that decides what to do with the 222") is
re-confirmed rather than inherited.

**2. The census, which is a fact about the TABLE and so is checkable, was stale.**
§0.3's table reads `unclassified 216 / written 29 / modelled 29 / unreachable 18 /
admitted 4 / front-end 1` over "the 303 names CPython ships on this tree", and
§0.1 reads `223 … (120 public, 103 private)`. Neither matches:

| verdict | this doc (§0.3) | 2026-10-05 |
|---|---:|---:|
| `unclassified` | 216 | **205** |
| `modelled` | 29 | **32** |
| `written` | 29 | **30** |
| `unreachable` | 18 | **22** |
| `admitted` | 4 | 4 |
| `not-code` | (not yet an answer) | **3** |
| `front-end` | 1 | 1 |
| **total (`sys.stdlib_module_names`)** | 303 | **297** |

and of the 205, **102 are public** (the doc says 120). The totals fell because
CPython's own list is version-dependent (303 -> 297 on this interpreter), which is
the reason §0.3 already said the count "is printed by the accessor rather than
inferred by a reader" — so the numbers above are printed here **with the accessor
that computes them**, and a reader who wants them should ask it:

```console
$ python3 -c "
import sys, collections, formal.imports as I
print(collections.Counter(I.host_module_verdict(n)[0]
                           for n in sys.stdlib_module_names))"
```

**3. `find_spec` decides FIVE of the 205, and §"The next step" overstates it.**
§0.3's last paragraph offers the oracle for the rest — "a name whose spec CPython
cannot find here is `unreachable` by the rule, and a name whose spec it can is
`modelled` unless the content is not code" — and calls the result "103
per-name judgements with an oracle rather than a judgement". Measured, the oracle
splits 205 into **5 and 200**:

```
CPython CANNOT find_spec here: 5  ->  _gdbm, _overlapped, _tkinter, _winapi, _wmi
CPython CAN   find_spec here: 200
```

All five are Windows-only private modules, and the reading is right for them: the
object (the Windows extension modules, the WMI bindings) is missing from the
target, which is the rule at the top of `formal/imports.py`. **The other half of
the sentence is FALSE as a rule, and the doc's own §0.3 table is what says so:**
`multiprocessing`, `pdb`, `venv`, `curses`, `sqlite3` all have a spec on this
host and all are `unreachable` for a reason `find_spec` cannot see — a second
process, a terminal, a library outside libSystem. So a spec existing is evidence
that the name is not a typo, and nothing else; the remaining **200** are 200
per-name judgements against the rule, which is exactly what §0.1 says there is no
measurement for and exactly what §"Why the 222 are filed and not fixed here"
warns against doing by category.

**What this section does NOT do, and it is the whole of what is left:** it
classifies nothing. The five `find_spec`-decided names are the first entries a
worker could add with a measurement behind each, and they are **private**, so
adding them moves the public count by zero; §0.1's reason for the rest — nothing
imports them, so no measurement can tell a right entry from a plausible one — is
what this section re-measured and left standing.

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

## 0.3 The "third answer" is LANDED, and it is the FOURTH tier — and it corrected
## the doc's own list (2026-10-05, `work/formal25-5-r2`)

§"The next step"'s last bullet said the "neither tier, deliberately" group —
"a name whose only spelling is a documentation or test artefact (`this`,
`antigravity`, `turtledemo`, `idlelib`), or a Windows-only / POSIX-only module
that is not this host's (`msvcrt`, `winreg`, `nt*`, `posix`, `genericpath`,
`nturl2path`)" — "want[s] a third answer or an explicit exclusion list, which is
a decision about the table rather than a classification — and **it should be
recorded as one, not left to look like an oversight**." That is what landed, and
landing it turned out to be THREE answers rather than one, because the doc's
single group does not have a single reading.

**THE MEASUREMENT IS CPython's OWN `find_spec`, on the interpreter that runs
this tree, and that is what splits it.** The table's rule is stated once at the
top of `formal/imports.py` — "does implementing it need an object a
freestanding image that links libSystem and nothing else does not have?" — and
a name is "not this host's" when the OBJECT is missing, which is a fact about
the target and therefore `importlib`'s to answer, not a remembered list's:

| the doc's group | `find_spec` here | so | tier |
|---|---|---|---|
| `this`, `antigravity`, `turtledemo` | **a spec EXISTS**, and what is behind it is not code | nothing to implement AND nothing missing, so neither claim tier is true | **`HOST_NOT_A_MODULE`** — new, `'not-a-module'` |
| `msvcrt`, `winreg`, `winsound`, `nt` | **no spec AT ALL** — CPython cannot find them on this host either | the object (the Windows C runtime, the registry, the sound API, `nt`'s Windows `os`) is missing from the target | `HOST_UNREACHABLE`, the existing row applied |
| `ntpath`, `nturl2path`, `genericpath`, `posix` | **a spec DOES exist** | they are frozen or arithmetic-over-strings modules CPython ships everywhere and only ever *uses* on Windows; `posix` needs the libSystem calls `formal/hostmods/os/_syscalls.mojo` already makes, because THIS is a POSIX target | `HOST_MODELLED`, existing row applied |

**So the last four are a CORRECTION of this document, and for `posix` it is
outright.** `posix` is the POSIX low-level module; calling it "not this host's"
was true of `msvcrt` and false of `posix` on the machine this tree runs on.

**And `idlelib` is in NONE of the three, which is also a correction.** This
document lists it twice — once as "a documentation or test artefact" and once
under `unreachable`. The second is right: IDLE is an interactive editor, so it
needs a terminal, and `HOST_UNREACHABLE`'s existing "A terminal" heading is
exactly that fact. Giving it `not-a-module` would claim there is nothing to
implement when there is a whole editor, so it is left in the queue rather than
given a tier that is false of it.

**It is the FOURTH answer and not the third**, because `HOST_ADMITTED` took that
slot on 2026-10-02 — a reader counting tiers off `formal/imports.py` should not
have to re-derive the numbering. `host_module_tier` now answers four values plus
`''`, and it tests `not-a-module` LAST, because that tier asserts the LEAST:
a name in two tiers must answer with the one that says something. The partition
check `_host_tier_conflicts` now includes the new tier's overlap with the other
three, since that is the pair most worth checking.

**The WORDING is the load-bearing half and it is why the tier exists at all.** A
member is in the host union, so `_is_host_module` fires and the old arm would
say *"a host module (CPython standard library), which has no Mojo source for
this backend to compile"* — **true, and it tells the reader to go and implement
a module that has no API.** So `unresolvable_import_error`'s new arm is tested
FIRST and says there is no content to compile.

**No build outcome changes.** Every one of the eleven is refused exactly as
before, which is the same property the seven names of 2026-10-03 had: `_is_host_module`
consults the union, so a member is refused by the tier-agnostic host-import
refusal either way, and what moves is the WORDING and the reach accounting.
Public unclassified standard-library names: **114 → 103.**

The three instruments that read the tier all move with it:
`tools/formal_sweep.py`'s reach line names the fourth bucket rather than
letting these files vanish from both halves of it (the reason `HOST_ADMITTED`
is named there is the same one), `tools/formal_sweep_causes.py`'s `tier` legend
says what the value asserts, and `test_formal_link_accounting.py::
HOST_SET_ADDED_TIERS` — which is the ledger, and which correctly failed on both
of my additions — carries all eleven with the tier and the reason.

Verified: `test_formal_imports.py` PASS=76 FAIL=0 (was 75/0 — this pass's one
test, `test_a_name_with_nothing_to_implement_gets_its_own_tier`),
`test_formal_link_accounting.py` 285/285, `test_formal_sweep.py` 124/124,
`test_refusal_taxonomy.py` 264/264.

**What is still not done, unchanged:** the rest of the per-name judgements.
§0.1's reason still stands for them — nothing imports them, so there is no
measurement to tell a right entry from a plausible one, and filling them by
category from a distance is the failure `formal/imports.py:101` warns about.
**This section does not change that**, and the difference is that the eleven it
did classify were decided by a measurement rather than by a reading: the doc's
own list named them, and `find_spec` said which of three readings each one
takes. That oracle is available for the rest too, and is the next step for
anyone who takes them — a name whose spec CPython cannot find here is
`unreachable` by the rule, and a name whose spec it can is `modelled` unless
the content is not code. That is 103 per-name judgements with an oracle rather
than a judgement, which is a materially different piece of work from the 222
this document describes.

**§0.5 ran that oracle over the whole list and HALF of it does not hold.** The
first half became a rule over every name and settled five more (`find_spec`
absent ⇒ `unreachable`); the second half is refuted by six names, three in each
direction, and the refutation is what keeps the rest of the queue a reading per
name. Read §0.5 before using the sentence above.



## 0.3 What landed 2026-10-05 (`work/formal27-6`): the AMBIGUOUS `''` is gone,
## and the queue is a named answer rather than an absence

**The 217 per-name judgements are still not done, and this section is why that
is now a QUEUE rather than a gap in what a report can say.** §0.1 calls
`host_module_tier`'s empty answer "the load-bearing half" of this doc's cost, and
§0.2 records the first version of the census test getting it wrong because the
accessor could not say which kind of empty it was. It can now.

**`formal/imports.py::host_module_verdict(name)` is the one classification of a
name, and it has seven answers, none of them an absence:** `front-end`,
`written`, `admitted`, `modelled`, `unreachable`, `unclassified` and `not-code` — plus `not-a-module` for a name nothing here
provides and CPython does not ship, which
is the TYPO sentence's answer and the only one that is a statement about this
repository rather than about the target. `written` and `admitted` carry the
resolved path, because those are the two answers a reader's next question is
"then what provides it".

**The ambiguity was real and it had already been worked around three times**, in
three different ways, which is the measurement that made the accessor worth
adding rather than tidying:

| consumer | how it told "written" from "unclassified" | what that misses |
|---|---|---|
| `test_formal_imports.py::test_no_unclassified_stdlib_name_is_imported_by_anything` | paired the tier with `resolve_module_path` | nothing — it had to spell the pairing out in a comment because the accessor did not |
| `tools/formal_sweep_causes.py` | inferred it from a `formal/hostmods/<name>.mojo` existing | a repository sibling, a package `__init__.mojo`, and every module outside `formal/hostmods/` — all three came out `UNTIERED`, which is a DEFECT claim about a module that is answered |
| `tools/formal_host_import_wall.py` (this round) | paired the tier with the resolver AND `is_cpython_stdlib` | nothing, but it was a fourth copy of a fact with one home |

All three now read the one function. **And it corrects a row the day it landed:**
`html.parser` is a SUBMODULE of the written `formal/hostmods/html.mojo`, so the
verdict is `written` while `host_module_tier` says `''` and the wall table
printed `unclassified` for it a commit earlier — the exact false statement the
three-way split was hiding.

**The partition is now a CLOSED invariant, which is what makes the remaining work
a queue with a direction.** `test_formal_imports.py::
test_every_name_has_one_named_verdict_and_no_answer_is_an_absence` walks every
name in `sys.stdlib_module_names` and asserts each gets exactly one of the six,
that `not-a-module` is unreachable for them (CPython ships every one), and that
no name is in a claim tier AND has a source — which is the rule
`HOST_MODELLED` states ("a name LEAVES a tier by being WRITTEN") and which
nothing asserted until now. Measured over the 303 names CPython ships on this
tree:

| verdict | n |
|---|---:|
| `unclassified` | **216** |
| `written` | 29 |
| `modelled` | 29 |
| `unreachable` | 18 |
| `admitted` | 4 |
| `front-end` | 1 (`dataclasses`) |

216 rather than 217 because `html.parser` moved to `written`. **The count is
still a fact about the table and not about the corpus**, so it is printed by the
accessor rather than inferred by a reader — and
`test_no_unclassified_stdlib_name_is_imported_by_anything` still asks the
corpus question, which is the one that decides whether filling the queue is
worth doing. It is a queue with a trigger now, not a gap with an ambiguity in
it.

**What is still not done, unchanged:** the 216 per-name judgements. §0.1's
reason still stands — nothing imports them, so there is no measurement to tell a
right entry from a plausible one, and filling them by category from a distance is
the failure `formal/imports.py:101` warns about. What changed is that the work is
queued by a NAME the tree can print, by a tripwire that fires when a consumer
arrives, and by a test that will go red if a name is ever left with no answer at
all rather than with the wrong one.

**§0.5 (2026-10-05) is what this section's numbers became, and it SUPERSEDES the
oracle §0.3 handed the queue.** 35 of them are settled by a rule — 30 by
`capability_sibling_tier`, which reads this repository's own tables and needs no
judgement about the target, and 5 by the `find_spec` measurement this very
section proposed — so the count is **170**, not 216. And the second half of that
oracle is **false**, which is the more useful half to record: `sqlite3`, `ssl`,
`bz2` and `lzma` all have a spec and all need a library outside libSystem, while
`_hashlib` and `_decimal` bind one and have had their capability implemented here
or reduced to arithmetic. **The oracle that is sound is `find_spec` for ABSENCE
and nothing else**; the reading that decides the rest is per name, and
`tools/formal_stdlib_reach.py` prints each one's evidence so it is a reading of
the module rather than of the interpreter.

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
  one, not left to look like an oversight. **DECIDED, in §0.3 and §0.4:**
  `this` / `antigravity` / `turtledemo` are the fourth TIER (`HOST_NOT_A_MODULE`)
  and answer `not-code`; `idlelib` is deliberately in no tier at all and answers
  `unclassified` (`test_formal_imports.py` asserts both, and why: an interactive
  editor is not "nothing to implement"); `msvcrt` / `winreg` / `winsound` / `nt`
  are `unreachable` under the rule at the top of `formal/imports.py` — CPython
  cannot `find_spec` them on this host either, so the object is missing from the
  target rather than the module being unwritten.

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