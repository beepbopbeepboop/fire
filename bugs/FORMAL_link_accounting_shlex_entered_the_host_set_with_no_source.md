# FORMAL_link_accounting_shlex_entered_the_host_set_with_no_source: `formal-link-accounting` is red — two rules disagree about a standard-library name with no Mojo source

**Not mine, found on 2026-10-03 while re-measuring the load-time
initializer row, and it is an UNDECLARED red in the everyday gate**:
`formal-link-accounting` is registered in the `check` bucket
(`tools/suite.py`, with `formal-sweep-truth` and `refusal-taxonomy`), so
`make check` fails on it today, and nothing in the suite says why.

It is not a stale constant. It is two pieces of code with opposing intents and
no rule that covers both, and it needs a decision rather than an edit.

## What I ran, and what it said

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 test_formal_link_accounting.py
# 210 passed, 1 failed, 211 checks
# FAIL  nothing has been ADDED to the host set beyond the names that were being
#       MISCLASSIFIED, and each of those has real source: added ['shlex']
```

Pre-existing, and pre-existing by construction: this branch touches neither
`formal/imports.py` nor `test_formal_link_accounting.py`
(`git diff c5ab524d..HEAD --stat` lists neither), and
`_original_host_modules()` returns the literal `PRE_SPLIT_HOST_MODULES` in the
test file rather than consulting git, so the verdict cannot depend on which
branch it runs on.

## The two rules

**`formal/imports.py` put `shlex` in `HOST_MODULES`, and says why** — it is a
CPython standard-library module with no Mojo source here, and a name in NEITHER
tier made `unresolvable_import_error` say *"not a stdlib or sibling module"*,
"a false statement about the target, and the one diagnostic in this family that
misidentifies what kind of thing the name is". It also says, in the same
comment, that `formal/hostmods/shlex.mojo` does NOT exist and is not in reach:
`split`/`quote`/`join` are pure computation, the streaming `shlex.shlex` reader
is a generator over `readline`.

**`test_formal_link_accounting.py::test_host_tiers` says a name may only ENTER
the host set if it was being misclassified AND it has real source**, and then
asserts the file exists:

```python
        check(union - orig <= set(HOST_SET_ADDED_WITH_SOURCE), …)
        for name in sorted(HOST_SET_ADDED_WITH_SOURCE):
            check(os.path.isfile(os.path.join(
                      HERE, "formal", "hostmods", f"{name}.mojo")), …)
```

`HOST_SET_ADDED_WITH_SOURCE` is `{}` — measured, and `formal/hostmods/shlex.mojo`
is absent — so `shlex` is reported, and the rule it breaks is stated in the test's
own words: *"A name enters the host set when it is a CPython standard-library
module this backend has no source for, never because one is hard to write"*
(`imports.py`) against *"nothing has been ADDED … and each of those has real
source"* (the test).

**So the test is right about `shlex` and the addition was deliberate anyway.**
Both rules are individually defensible; what is missing is the rule that says
which one a sourceless standard-library name falls under.

## The next step

Decide, in one sentence and in `formal/imports.py` (where the other host-set
rules live), which of these a name is:

1. **"this backend can answer for it"** — the current meaning of the host set.
   `shlex` is not in it by that rule, and the honest consequence is that
   `unresolvable_import_error` must stop saying "not a stdlib or sibling module"
   for a name that IS one, rather than the name being classified to fix the
   sentence. That is a change to the diagnostic, and it is the more honest of
   the two: a classification changed to make a message true is the same category
   as rewriting a source file to a shape the compiler can compile.
2. **"this is a CPython standard-library module"** — what the 2026-10-03
   addition implements. Then `test_host_tiers`'s rule has to grow the third case,
   and `HOST_SET_ADDED_WITH_SOURCE` is the wrong shape for it: the invariant
   becomes "an added name is either being misclassified or is a stdlib module",
   and the second half of that needs no file-existence check because there is no
   file by definition.

Whichever is chosen, the check should assert the rule rather than one instance of
it: today it fails on a NAME (`shlex`), which is the anti-rot weakness —
re-adding `shlex` to the allow-list with a source-less name would satisfy it.
`fcntl` is the other entry in this area and it took the first route (a real
`formal/hostmods/fcntl.mojo`), so the tree already contains one instance of each
answer.

**Not to be worked around** by adding `shlex` to the allow-list with no file:
the loop right below the subset check exists precisely to fail that, and it
would.