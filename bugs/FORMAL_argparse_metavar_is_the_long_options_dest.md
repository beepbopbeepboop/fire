# `formal-argparse` is RED: 31 of its 69 differential cases differ from
# CPython, and it is registered with no `expect=`

**Status: PRE-EXISTING and untouched by `formal/contracts.py`. Diagnosis is
partial but localisable; see §4.**

## 1. What I ran and what I saw

```
$ python3 test_formal_argparse.py
  FAIL  the parse matches CPython, case for case
        31 of 69 cases differ from CPython:
  demo[4] argv='-v': stderr differs (this is the usage line and the error message).
  image:   'usage: demo [-h] [-v] [-j JOBS] --side {a,b} [--extra EXTRA] [stems ...]
            demo: error: the following arguments are required: --side\n'
formal argparse: PASS=8 FAIL=1
```

CPython's own `argparse`, on the same declaration and the same command line:

```
$ python3 -c "import argparse; p=argparse.ArgumentParser(prog='demo');
  p.add_argument('-v',action='store_true'); p.add_argument('-j',type=int,default=1);
  p.add_argument('--side',required=True,choices=['a','b']); p.add_argument('--extra');
  p.add_argument('stems',nargs='*'); p.parse_args(['-v'])"
usage: demo [-h] [-v] [-j J] --side {a,b} [--extra EXTRA] [stems ...]
demo: error: the following arguments are required: --side
```

**`-j JOBS` against `-j J`.**  That is the whole of this case, and it is the
shape of the majority: a metavar the image derives from the LONG option's dest
where CPython derives it from the SHORT one's.

## 2. Why this is not mine

The branch this was found on is `work/formal36-contracts-language`, whose whole
diff against its own branch point `80c56901` is 14 files:

```
fire.py                   formal/contracts.py      formal/build.py
formal/contracts/*.mojo   test_formal_contracts.py  bugs/FORMAL_*.md (2)
```

Nothing there is `formal/hostmods/argparse.mojo`, `test_formal_argparse.py`, or
anything else the differential builds.  The one shared file is `fire.py`, and
its diff is `_extract_formal_flags` returning a fourth value for
`--check-contracts` plus a `_contract_note` printer — neither is reached by a
build of an argparse program, which carries no `@requires`.

I could not produce a one-off reproduction to close this out: the harness links
its parsers through `formal/hostmods/argparse.mojo` as a MODULE, and a
hand-written demo program is refused with

```
build: argparse.ArgumentParser(): `argparse` is a linked module but it exports no ...
```

on both my tree and master's, so the harness's linkage is not something a
scratch program reproduces.  That is why the diagnosis below stops where it
does rather than claiming a fix.

## 3. What IS localised

`formal/hostmods/argparse.mojo`'s own header says, at line 63:

```
  8 metavar    empty to derive it (`{choices}`, else dest.upper())
```

and CPython's rule for `add_argument("-j", "--jobs", type=int)` is that the
metavar comes from the DEST of the option it is attached to — `-j` — which is
`j`, upper-cased to `J`.  The image prints `JOBS`, so it is taking the dest of
the LONG option.

That is a two-place fix at most: the metavar derivation has to read the
`dest` of the option the metavar is being rendered FOR, not the parser-wide
`dest` of the action.  `_dest(spec, i)` at line 804 and the metavar path at
line 849 are where to look.

## 4. The next step, precisely

1. `formal/hostmods/argparse.mojo`: find where the metavar for an option is
   derived and confirm it is not reading the long option's dest.  Compare
   against CPython for `add_argument("-j", "--jobs", type=int)` —
   `p.format_help()` must contain `-j J` and must NOT contain `-j JOBS`.
2. Re-run `python3 test_formal_argparse.py` and record how many of the 31
   remain.  They are **not** all metavars: the other 30 have not been looked
   at, so treat "the metavar is the first cause" as a hypothesis and not as the
   finding.
3. `formal-argparse` is registered in `tools/suite.py` at line 2599 with
   `mem='tiny'` and **no** `expect=` and no `disabled=`.  So it is a declared
   red that is not declared.  Whoever fixes it should not add a marker: a
   green that does not do what we want is worse than a red that needs fixing,
   and this one is 31 cases of real divergence from the oracle the file names.

**Cost note, for whoever picks it up:** the job builds and runs 11 images
(11 declared parses, 69 differential cases), measured at 11 s and 0.21 GB
(`tools/suite.py`'s `MEMCLASS` table), so it is cheap to re-measure after each
attempt.