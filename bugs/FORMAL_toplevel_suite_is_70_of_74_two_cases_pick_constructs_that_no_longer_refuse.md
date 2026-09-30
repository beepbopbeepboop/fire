# FORMAL_toplevel_suite_is_70_of_74_two_cases_pick_constructs_that_no_longer_refuse: `test_formal_toplevel.py` is red on two cases whose SUBJECT is still true

**Area:** CODEGEN/FORMAL (Mach-O) — `test_formal_toplevel.py`, and the two
refusals that moved in front of the ones these two cases assert. NOT the
`construct:cross-module-link` claim; found by running the suites that cover the
`integ` merge, and filed rather than edited — the fix belongs with whoever owns
the module-body work, and both fixes are in the test rather than in the
compiler.

**Found while:** merging `integ` into
`work/fix-merge-fix-merge-fix-merge-formal-cross-module`, 2026-09-30.

**Status: OPEN, stale TEST rather than a compiler defect, and neither case's
subject is in doubt.** Both cases still describe a true fact about this backend.
Both fail because the program each one builds no longer reaches the refusal the
case is about: one now hits an earlier refusal, the other is no longer refused
at all. That is the good direction for the compiler and the wrong direction for
a test, and a test that keeps asserting a construct the compiler has since
learned is a hole in coverage wearing a green-looking coat.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label toplevel -- python3 test_formal_toplevel.py
FAIL  name_in_function [arm64] refusal names it: refused, but not with
      "'__name__' has no home": … `__name__ == 46` … or the string's content,
      `str_at('__main__', 0, ".")` or `'__main__'.startswith(".")`
FAIL  name_in_function [x86_64]  (same)
FAIL  body_construction_refusal [arm64] refused: it BUILT a construct with no
      representation; the binary is the real answer here
FAIL  body_construction_refusal [x86_64]  (same)
formal toplevel: PASS=70 FAIL=4 (74 checks)
```

Four failures, two cases, both architectures — so the verdicts agree and the
cases are the problem. **Neither is a regression from this merge:**
`git diff 86d862fc HEAD -- test_formal_toplevel.py` is empty, and the behaviour
each case collides with is at the merge base. See "Not this" for the two
provenances separately.

## Case 1: `name_in_function` — an earlier refusal now shadows the one asserted

The case is `def f(): if __name__ == "__main__": return 1` and it asserts the
refusal `'__name__' has no home`. What it gets is
`formal/model.py`'s string-comparison refusal, because `__name__ == "__main__"`
is a comparison between an unresolvable word and a string, and that check runs
first.

**The fact the case exists to pin is still true and still worth pinning:** a
function's `__name__` is the name of whatever module it was DEFINED in, so it is
deliberately not materialized in a function body (the case's own docstring says
so, and pins it "so a later change cannot widen the substitution into the
function bodies"). The `if __name__ == …` spelling just puts that read inside a
comparison, and the comparison has its own, more specific answer.

**The fix, and it is one line of test source** — drop the comparison so the read
is the subject again:

```mojo
def f():
    return __name__


f()
```

Measured on this tree, and it refuses with exactly the words the case asserts:

```
build: f: '__name__' has no home: the register allocator collected no home for
it, so the emitter and the allocation walk disagree about this function's locals. …
```

That is strictly better coverage than what is there now: the current program
proves the *comparison* is refused, which nothing claimed was in doubt, and
stops proving the *substitution is not widened*, which is the whole point.

## Case 2: `body_construction_refusal` — the construct is inlined now

The case is a module-level `p = Point(1, 2)` where `Point.__init__` is a
straight line of `self.<field> = …` stores, and it asserts the construction
refusal. It builds now, and correctly: `c0438b43` ("lower a declared `__init__`
by inlining its stores at the construction site") made exactly this shape work,
and `formal/model.py` says so in the refusal's own docstring — "A body that is a
straight line of `self.<field> = <expr>` stores is the same program as the
construction followed by those stores … so it is inlined rather than refused."

**The fact the case exists to pin is still true and is a good one:** a module
body is refused by the ORDINARY codegen checks, not by a second body-only list
— "a second, body-specific refusal list would have made this a different message
for the same construct depending on where it was written." What is needed is a
constructor the inliner genuinely cannot handle, so the ordinary refusal fires.

**The fix is one `if` in the test's source** — a body that is not a straight line
of stores:

```mojo
struct Point:
    x: Int
    y: Int

    def __init__(self, x, y):
        if x > 0:
            self.x = x
        self.y = y


p = Point(1, 2)
printf("%d\n", p.x)
```

Measured on this tree, and it refuses with the ordinary construction message:

```
build: constructing Point with arguments is a call to a user-defined `__init__`
whose body this path does not inline: a `if` statement. This path lowers that
call by storing each of the constructor's `self.<field> = …` assignments into the
fresh block at the construction site, …
```

That is the case's original intent, reached: the message names `__init__`, it is
the ordinary construction refusal, and it is the same one a function-level
construction gets.

## The exact next step

Two edits to `test_formal_toplevel.py`, both of which make an existing case
assert what its docstring already says, and neither of which touches the
compiler:

1. `test_name_in_a_function_is_still_refused` (the case at :362, source at
   :373) — replace the source with `def f():\n    return __name__\n\nf()\n`.
2. `test_a_module_body_can_still_be_refused_by_the_ordinary_codegen` (the case
   at :609) — add the `if x > 0:` guard to the constructor body.

Then `python3 test_formal_toplevel.py` should be 74/74. If either case goes red
for a NEW reason afterwards, that is a real finding and this doc is wrong —
which is the point of writing the two replacements down as measured output
rather than as an intention.

**A third thing worth doing while the file is open**, and it is the one that
would have caught both: neither case asserts WHICH refusal it got, only that
some refusal did — `case_refused` takes a substring, and a substring that a
DIFFERENT, more specific refusal also contains would pass. Case 1 got past a
substring check for the same reason. If `case_refused` grew an option for
"refused, and NOT with this other message", the two failures would have been
visible as message-shadowing rather than as a count.

## Not this

- **Case 2 is not this merge's doing, and not a regression.** `c0438b43` is dated
  2026-09-29 and is an ancestor of `86d862fc`, the merge base. The case has been
  red against it ever since. `git diff 86d862fc HEAD -- test_formal_toplevel.py`
  is empty, so the merge neither introduced nor repaired it.
- **Case 1 is not a compiler defect either.** `formal/model.py`'s
  string-comparison refusal is newer than the case — the `untyped_callee` input
  arrived in `integ`, and the tree has 0 occurrences of it at the merge base —
  and it is RIGHT: `__name__ == "__main__"` compares an unclassifiable word with
  a string, and lowering it to an address compare is the silently-wrong answer
  this backend refuses to emit. The test is what is out of date.
- **Not fixable by marking `expect=`.** `test_formal_toplevel.py` is in neither
  `tools/suite.py` nor `test_suite.py`'s `UNREGISTERED` table, so there is no
  `expect=` to set and no tally to move — the two reds are visible only to
  someone who runs the file by hand, which is how they were found. See
  `TOOLS_the_test_estate_check_is_red_and_nothing_reads_its_answer`.
