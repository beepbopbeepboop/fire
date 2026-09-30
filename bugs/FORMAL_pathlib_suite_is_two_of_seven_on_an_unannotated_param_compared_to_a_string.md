# FORMAL_pathlib_suite_is_two_of_seven_on_an_unannotated_param_compared_to_a_string: `test_formal_pathlib.py` is red on five of its seven groups, and the hostmod's fix is two annotations

**Area:** CODEGEN/FORMAL (Mach-O) — `formal/hostmods/pathlib.mojo` and the
value model's classification of an unannotated parameter. NOT the
`construct:cross-module-link` claim this was found in; found by running the
suites that cover `integ`'s merged tree, and filed rather than edited.

**Found while:** merging `integ` into
`work/fix-merge-fix-merge-fix-merge-formal-cross-module`, 2026-09-30.

**Status: OPEN, and the root cause is already filed — this is an instance
record plus a two-line fix.** `bugs/FORMAL_string_value_model.md` §"An
UNANNOTATED `String` parameter is still a fabricated truthiness" names the gap:
`ValueKinds` seeds an unannotated parameter as `INT_KIND` (a word) and nothing
downstream can tell a word from a `char *`. This is a THIRD site for it, the
first reached by a new suite, and it is reached through a *comparison* rather
than through a truthiness test — so it gets its own message and its own
docstring in `formal/model.py`.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label pathlib -- python3 test_formal_pathlib.py
PASS resolve  resolves to formal/hostmods/pathlib.mojo, out of HOST_MODELLED
FAIL decompose
FAIL rewrite
FAIL relative
FAIL match
FAIL reserved
PASS absent  24 absent names refused
2/7 groups passed
```

All five failures are the same refusal, and the minimal reproduction is one
line of caller:

```console
$ cat > .tmp/pl.mojo
from pathlib import PurePosixPath


def main(n):
    printf("%s\n", PurePosixPath("a/b/").name)
$ python3 fire.py build --formal --no-prove -o .tmp/pl .tmp/pl.mojo
build: pl.mojo imports 'pathlib', which cannot be built either: pathlib.mojo:
`q == '.'` compares a NUMBER with a string, and the string comparison this would
lower to is `strcmp`, which DEREFERENCES both operands — so it would be handed
the value of `q` as an address. …
```

**So the whole `pathlib` module does not build**, and 5 of 7 groups are red
because they cannot even get to their question. `resolve` passes because it
only checks the module resolves; `absent` passes because it checks 24 names are
*refused*, which a module that will not compile trivially satisfies — that one
is a false pass worth knowing about.

## Why it is not a `pathlib` bug

`formal/hostmods/pathlib.mojo` is a faithful transcription of `PurePosixPath`
and its internal `q == "."` checks are correct Mojo. The construct is:

```mojo
def last_name_at(q) -> int:      # line 241 — `q` has NO annotation
    if q == ".":                 # line 251 — and this is the refusal
        return 0 - 1
```

`q` is a parameter of this module's own function, so nothing crosses a module
boundary and no manifest is involved. `q`'s kind is `None`/word because the
parameter carries no annotation, `'.'` is a string, and
`formal/model.py`'s comparison refusal fires on exactly-one-side-classified —
which it must, because the alternative is `strcmp` on the integer value of `q`.

Every site in the file with the same shape:

| function | line | comparison |
|---|---|---|
| `last_name_at(q)` | 251 | `q == "."` |
| `name(p)` | 320 | `q == "."` (via `var q = as_posix(p)`) |
| `parent(p)` | 360 | `q == "."` |
| `relative_to(p, base)` | 446, 453 | `b == "."`, `a == "."` |
| `n_components(q)` | 492 | `q == "."` |

The first is the one that fires, and the other four are behind it in the same
call chain — the fix is one annotation, not five, and the compiler says so by
naming `q` rather than a line.

## The exact next step

1. **Annotate the parameters** `formal/hostmods/pathlib.mojo:241`
   (`def last_name_at(q: String) -> int:`) and `:480`
   (`def n_components(q: String) -> int:`), and check whether
   `relative_to(p, base)`'s two are the same shape at :434. This is the fix
   `FORMAL_string_value_model.md` §"the kind table" points at, applied at the
   source rather than in the model, and it is safe: an annotation can only
   classify MORE, never less, so a call site that already passed a string is
   unaffected. Confirm with `python3 test_formal_pathlib.py` — all seven groups
   are an oracle comparison against CPython's own `pathlib`, so "the module
   builds" is not the bar, "it builds and agrees" is, and the suite already
   asks the right question.
2. **Then decide whether `absent` is still worth anything.** It passes today
   because the module will not build. After step 1 it has to pass because 24
   names are genuinely absent, and if it still passes for the wrong reason the
   suite has a hole of the kind
   `TOOLS_the_test_estate_check_is_red_and_nothing_reads_its_answer` is
   about. Worth a look while the file is open.
3. **The model half is not this branch's and not this doc's.**
   `FORMAL_string_value_model.md` already proposes the two real options
   (propagate the call site's argument kind into the callee, or refuse
   `if <word>:` when the word is unclassified) and the second is a much larger
   diagnostic surface. What this doc adds is that the option-1 cost is now
   three sites rather than one, and the third is in a hostmod whose whole
   purpose is to be a transcription of CPython — which is the argument for
   option 1 being worth its price.

## The same root cause, a different door

`bugs/FORMAL_argparse_suite_is_two_of_seven_after_untyped_callee.md` is the same
gap reached through the CALLEE rather than the PARAMETER: `integ`'s new
`untyped_callee` hook refuses a comparison where a value "arrived from a call
that does not say what it returns", and `formal/hostmods/argparse.mojo` has 107
`def`s with no return annotation. That one is `integ`'s own red and its blast
radius is 107 sites rather than 2, so whoever fixes this should read that doc
first — the two fixes are the same annotation pass at two scales, and doing only
this one leaves `argparse` red.

## Not this

- **Not** a regression from the `integ` merge. `formal/hostmods/pathlib.mojo`
  and `test_formal_pathlib.py` are both new in `integ`, and
  `git diff integ HEAD -- formal/hostmods/pathlib.mojo` is empty on the merged
  branch. `formal/model.py`'s diff against `integ` is comment and docstring
  only outside the dylib functions — the classification code the refusal reads
  is byte-identical to what `integ` had. It is `integ`'s own red, measured.
- **Not** the `FORMAL_subscript_of_a_pointer_reads_a_blob_count` family. That
  one was a byte read through a `Pointer` blob's first word; this is a
  parameter's kind never being established. Different mechanism, and that one
  is fixed.
