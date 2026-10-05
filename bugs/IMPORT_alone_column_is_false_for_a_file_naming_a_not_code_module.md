# IMPORT_alone_column_is_false_for_a_file_naming_a_not_code_module: the wall
# instrument's `alone` column is a claim about the build, and it drops a refusal
# the build makes

**Area:** IMPORT (`tools/formal_host_import_wall.py::_is_wall`, and the `alone`
column of `rank`), read off `formal/imports.py::host_module_verdict`.
**Status: FIXED on `work/formal28-5` (`f4de6bbf`) — and master carries a
DIFFERENT answer for the same two red tests, so this file is here to make that
merge a decision rather than a surprise.** See §2.

## 1. The defect, measured on `master` (`7b980ca4`)

`tools/formal_host_import_wall.py`'s own definition of `alone`, in the tool's
docstring: *files for which this name is the ONLY wall, **i.e. the files "writing
this module makes this file build" is a true statement about***.* That is a claim
about the BUILD, so the test for it is not "is this name classified" but "does
the build refuse this name".

`import antigravity` is refused. Measured, one build:

```
build: a.mojo imports 'antigravity', which is a CPython standard-library module
with no content to compile — it is documentation or a demonstration, not an API —
so there is nothing here to implement and nothing for the link step to provide
```

so `a.mojo` does not build and no writing of `abc` makes it build. And
`_is_wall` answered False for it — its whitelist was `(modelled, unreachable,
admitted, unclassified)`, and `host_module_verdict` said `not-a-module`, which
the whitelist excludes. Measured on `master`, three files, `abc` and
`antigravity` and nothing:

```
abc            reach=2 alone=2        <-- `alone` says writing `abc` builds BOTH
a.mojo's walls: frozenset({'abc'})   <-- and `antigravity` is not in the set
```

`alone(abc) == 2` is the false statement: `a.mojo` is one of the two files the
column says `abc` alone would fix, and writing `abc` does not fix it. The same
run says `reach` under-counts, and `reach` is the column the ranking sorts by
last, so the visible damage is the `alone` one.

After the fix, same three files:

```
abc            reach=2 alone=1
antigravity    reach=1 alone=0
a.mojo's walls: frozenset({'abc', 'antigravity'})
```

`this` and `turtledemo` refuse the same way (`build:` measured for each, with
the same sentence), and the build's refusal is the oracle rather than a rule
this file invented: `tools/formal_host_import_wall.py`'s wall set is
`host_module_verdict`'s, so the honest place for the answer is the verdict, and
that is where the seventh answer went.

## 2. `master` answers the same two red tests differently, and this is why the
## file is not deleted with the fix

Two checks in `test_formal_imports.py` were RED on this branch's base for this
reason — `every name has one named verdict, and no answer is an absence` and
`the wall instrument separates reach from alone`. `master` has since turned both
green (`test_formal_imports.py` 83/83 there, measured by extracting `master` to a
scratch tree and running it). Its two moves:

* `host_module_verdict`'s `'not-a-module'` is **widened** to cover both "CPython
  does not ship it" and "`HOST_NOT_A_MODULE` claims it and CPython's own
  `find_spec` finds a real file with nothing computable behind it", and the
  partition invariant becomes a PAIR — a shipped name may answer
  `not-a-module` as long as a tier claims it. Six answers stay six.
* `_a_real_wall_name` and the `wall_b` fixture pick **skip** a
  `HOST_NOT_A_MODULE` member, on the stated ground that "`antigravity` is not a
  wall — it is a name the table says has no content to compile".

**The second move is what makes the test green without fixing the instrument.**
The fixture no longer contains a `HOST_NOT_A_MODULE` name, so the case that
measured the defect is no longer exercised; `_is_wall` on `master` still answers
False for `this`, `antigravity` and `turtledemo`, and `alone(abc)` is still 2 on
the three-file fixture above (measured, §1). So the two branches agree that the
red tests are red and disagree about what the `alone` column is allowed to say.

**The disagreement, stated so a merge can decide it.** The tool's docstring
defines `alone` as the files for which "writing this module makes this file
build" is TRUE. Under that definition `antigravity` is a wall, because the build
refuses it permanently and for a reason no writing of `abc` touches. Under
`master`'s reading it is not a wall, and `alone(abc) == 2` on `a.mojo` becomes
the tool's opinion — which says that fixing `abc` builds a file the build
refuses on `antigravity`.

**What this branch landed**, so the merge is a choice between two coherent
things rather than a conflict to untangle: `host_module_verdict` gains a
SEVENTH answer `'not-code'` (CPython ships it, its content is not code) and
`host_module_tier` is left alone, so `test_formal_link_accounting.py`'s ledger of
the eleven names `FORMAL_stdlib_module_names_are_not_classified.md` §0.3 settled
still reads as written; `_is_wall` gains `'not-code'`. The build's own refusal is
the measurement behind that, and `test_formal_imports.py`'s
`test_a_module_whose_content_is_not_code_is_still_a_wall` pins the verdict's
answer, the instrument's predicate AND a build, because either half alone passes
with the other broken.

`bugs/FORMAL_stdlib_module_names_are_not_classified.md` §0.4 records the same
fix from the classification side, and marks the "neither tier, deliberately"
bullet of its §"The next step" DECIDED with the name that decided each part.

## 3. What this does not claim

**No ranking NUMBER moves.** Over `formal_host_import_wall.py`'s own 749-file
walk of this repository and the stdlib, no file imports `this`, `antigravity` or
`turtledemo`, so none of them appears in the table and every count above is
unchanged by this fix (measured before and after: the table is identical). This
is the honesty of one answer and the correctness of an instrument, not a moved
row — and `bugs/FORMAL_stdlib_module_names_are_not_classified.md` §0.1's
measurement (no corpus file imports an unclassified name) is the reason, not a
coincidence.

**The 102 public names still in no tier are still in no tier.** This file is
about three that are classified and one answer; it is not progress on the queue.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH

# §1, the three-file fixture and both columns.  Unchanged on master, changed
# here — the numbers ARE the defect.
python3 - <<'PY'
import sys, os, tempfile
sys.path.insert(0, ".")
import tools.formal_host_import_wall as W
d = tempfile.mkdtemp()
a, b, c = (os.path.join(d, n) for n in ("a.mojo", "b.mojo", "c.mojo"))
open(a, "w").write("import abc\nimport antigravity\n")
open(b, "w").write("import abc\n")
open(c, "w").write("x = 1\n")
for name, info in sorted(W.rank([a, b, c]).items()):
    print("%-14s reach=%d alone=%d" % (name, len(info["reach"]),
                                       len(info["alone"])))
print("a.mojo's walls:", W.walls_of(a))
PY

# the build's refusal, which is the oracle for "is this a wall"
printf 'import antigravity\ndef main() -> Int:\n    return 0\n' > .tmp/ag.mojo
python3 tools/memslot.py --gb 8 --label ag -- \
    python3 fire.py build --formal --no-prove -o .tmp/ag .tmp/ag.mojo

# the two tests, and the one that pins both halves
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py -v
```