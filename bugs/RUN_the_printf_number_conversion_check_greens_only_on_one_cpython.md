# RUN: `test_formal_run.py`'s `printf-number-conversion` check is green on Python 3.14 and red on 3.15, because it compares against the interpreter's own `%` wording

**Area:** the run suite's own oracle check — `test_formal_run.py`'s
`check_printf_number_conversion_agreement`, reading
`formal/model.py::PRINTF_CPYTHON_NUMBER_REFUSALS`.

**Status: OPEN, diagnosed, not fixed.** The fix is either a version table or a
version guard, and both are a decision about what the project promises about its
interpreter (see "The exact next step").

## What I ran, and what I saw

```console
$ python3 tools/memslot.py --gb 8 --label run -- python3 test_formal_run.py
...
formal run: printf-number-conversion PASS=15 FAIL=0        # under 3.14
formal run: printf-number-conversion PASS=1  FAIL=14       # under 3.15
formal run: PASS=1314 FAIL=18                             # under 3.14
formal run: PASS=1312 FAIL=20                             # under 3.15 (same tree)

$ which -a python3 | head -1
/opt/homebrew/bin/python3
$ python3 -VV
Python 3.15.0 (main, Oct  9 2026, 11:16:41) [Clang 21.0.0 (clang-2100.3.34.2)]
$ /opt/local/bin/python3 -VV
Python 3.14.8 (main, Oct  3 2026, 07:52:41) [Clang 21.0.0 (clang-2100.3.34.2)]

$ /opt/local/bin/python3 -c "import sys; sys.path.insert(0,'.'); \
    import test_formal_run as T; print(T.check_printf_number_conversion_agreement()[0])"
15
$ python3 -c "… same …"
1
```

**Nothing in the tree changed between the two runs** — both are the same
commits, and running the check from `git show HEAD:test_formal_run.py` (the
committed text, not my working copy) gives the same 1/14. So it is the
interpreter, not the branch.

## What is actually wrong

The check is doing exactly what it was written to do: it asks CPython what it
says for `"%d" % [1, 2, 3]` and requires
`PRINTF_CPYTHON_NUMBER_REFUSALS["d"]` to BE that sentence, because
`printf_container_conversion_refusal` prints the table's words as something the
interpreter said. A paraphrase would be a claim about Python that nothing here
could check. **CPython reworded the message.**

| conversion | table (`formal/model.py`) | CPython 3.15 says |
|---|---|---|
| `%d` | `%d format: a real number is required, not list` | `format argument: %d requires a real number, not list` |
| `%e`/`%f`/`%g` | `must be real number, not list` | `format argument: %e requires a real number, not list` |
| `%o`/`%x`/`%X` | `%o format: an integer is required, not list` | `format argument: %o requires an integer, not list` |
| `%c` | `%c requires an int or a unicode character, not list` | `format argument: %c requires an integer or a unicode character, not list` |
| `*` | `* wants int` | `format argument 1: * requires int, not list` |

Fourteen of the fifteen members are stale; `%a`/`%A` are excluded from the table
deliberately (`repr()`, not a C conversion) and are the one that passes.

**Why this is a bug doc and not a note:** the check is green or red according to
which `python3` happens to be first on `PATH`, and this machine has two
(`/opt/homebrew/bin/python3` is 3.15.0, `/opt/local/bin/python3` is 3.14.8). The
task's own environment line is `export PATH=/opt/homebrew/bin:$PATH`, so the
homebrew one wins, and a run launched with a different `PATH` gives a different
tally for the same commit. **A test whose verdict is a function of `PATH` is not
a property of the tree**, which is the same objection `CLAUDE.md` raises about a
doc that states a tally.

## The exact next step

Pick one and say which, in this file, so the next reader does not have to:

1. **Make the check version-aware.** Keep one table per supported minor version
   and select on `sys.version_info`, failing with a message that says "CPython
   3.15 reworded this; add the 3.15 sentence" rather than "the table
   misquotes the interpreter". This preserves the check's whole point — the
   refusal must quote the interpreter *running the build* — and makes the 3.15
   wording a thing to add deliberately rather than a thing to discover by
   `PATH`.
2. ~~Pin the interpreter.~~ **Not available, and `tools/suite.py` says why:**
   `PY = sys.executable` and the Makefile's `PYTHON ?= python3`, so the suite
   runs under whatever interpreter invoked it. There is no minor version to pin
   to; making one would be a change of policy, not a repair.

Option 1 is the answer, and it is forced by what the project already does:
`tools/suite.py`'s `PY = sys.executable`, and the Makefile's `PYTHON ?=
python3`, so the suite runs under **whatever interpreter invoked it** and there
is no minor version to pin to. Pinning (option 2) would be a change of policy,
not a repair. About twenty lines: keep one sentence per supported minor version
and select on `sys.version_info`.

It is not landed here because writing down which minor versions the project
supports is a decision for the controller, not a measurement — and a table that
guessed would be exactly the "a plausible constant is a fabricated answer"
failure this codebase rejects elsewhere.

## What is NOT wrong here

The twelve container-refusal rows in the same file were a different problem and
are fixed on this branch: two branches implemented one refusal with different
message wording and both kept their rows (`99cd6041`). This doc is only about
the check that asks CPython itself.