# FORMAL_argparse_suite_is_two_of_seven_after_untyped_callee: a new refusal lands on 107 unannotated defs in `formal/hostmods/argparse.mojo`

**Area:** CODEGEN/FORMAL (Mach-O) — the word/string comparison refusal in
`formal/model.py` and its new `untyped_callee` input, as it lands on a hostmod
written in a deliberately untyped style. NOT the `construct:cross-module-link`
claim; found by running the suites that cover the `integ` merge, and filed
rather than edited.

**Found while:** merging `integ` into
`work/fix-merge-fix-merge-fix-merge-formal-cross-module`, 2026-09-30.

**Status: OPEN, and the cause is a single new input to one function.** It is
`integ`'s own red — introduced by `ce7a3fd7` ("`==` between two computed
strings is a content compare or a refusal, never an address compare") — and it
is the same root cause as
`FORMAL_pathlib_suite_is_two_of_seven_on_an_unannotated_param_compared_to_a_string`
reached through a different door. Both are the value-model gap
`bugs/FORMAL_string_value_model.md` names; this one is about the CALLEE, that
one about the PARAMETER.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label argparse -- python3 test_formal_argparse.py
PASS  `import argparse` resolves to the module source
FAIL  every declared name is exported
FAIL  the parse matches CPython, case for case
FAIL  an unsupported spec is refused with a reason
FAIL  an underscore in an int is refused, not truncated
FAIL  prog is the basename of argv[0]
PASS  the sweep classifies an argparse refusal as codegen
formal argparse: PASS=2 FAIL=5
```

and the minimal reproduction, which does not need the suite's harness:

```console
$ cat > .tmp/ap.mojo
import argparse


def main(n):
    var p = argparse.ArgumentParser(prog="x")
    p.add_argument("--flag")
    printf("%s\n", str(p.parse_args(["--flag", "1"])))
$ python3 fire.py build --formal --no-prove -o .tmp/ap .tmp/ap.mojo
build: ap.mojo imports 'argparse', which cannot be built either: argparse.mojo:
`_name_len(...) == nlen` compares two values this path can only call numbers, and
at least one of them arrived from a call that does not say what it returns. …
```

**So the whole `argparse` module does not build**, and 5 of 7 groups are red
because they cannot reach their question. The two that pass are the resolver
check and a sweep-classification check — neither one needs the module to
compile.

## Why this is new, measured rather than dated

```console
$ for r in 86d862fc integ HEAD; do
    printf '%-10s untyped_callee occurrences in formal/model.py: ' $r
    git show $r:formal/model.py | grep -c untyped_callee
  done
86d862fc   0
integ      11
HEAD       11
```

`untyped_callee` is the backend's "is this a Mojo callee with no declared
return type" hook, and it is **new in `integ`**. The refusal this suite hits is
gated on it (`model._word_from_an_unannotated_call`), so at the merge base the
refusal could not have fired — the parameter did not exist. The change is the
right one: comparing two `char *` by address is a silently wrong answer, and
`ce7a3fd7` is correct to refuse rather than emit it. What is new is the
collateral, and it is large:

```console
$ python3 - <<'PY'   # defs in argparse.mojo with no return annotation
...                   # 107
PY
```

`formal/hostmods/argparse.mojo` is written in an untyped style throughout — 107
of its `def`s carry no `-> ` — and every one of them is now a possible refusal
site. This is the same shape as the `LENGTH_DEPENDENT_METHODS` and
`String`-receiver families the value model already refuses: correct, and each
one a diagnostic surface that grows.

## The exact next step

Three options, in the order I would take them, and the first is the one that
does not touch the model:

1. **Annotate `formal/hostmods/argparse.mojo`'s return types.** 107 signatures,
   mechanical, and the module is a transcription of CPython's `argparse` whose
   own docstrings already say what each function returns — so the annotations
   are recoverable from the file rather than invented. This is the same trade
   `FORMAL_hostmod_defaults_left_required_after_the_cross_dylib_fix` records for
   that module's defaults: additive, cannot change an answer, and it needs a
   sweep to believe. Confirm with `python3 test_formal_argparse.py`, whose five
   red groups are CPython comparisons rather than a table.
2. **Then narrow the refusal**, because 107 sites says the gate is too wide, not
   that the hostmod is wrong. `_word_from_an_unannotated_call` fires on ANY
   unannotated callee; a `-> int` on a function whose body is all arithmetic
   cannot produce a `char *`, and a cheap narrowing is to accept the comparison
   when the callee's body contains no pointer-valued return and no call to
   something that has one. That is a real analysis and a real cost, which is
   why it is step 2 and not step 1.
3. **Say which of the two is the intended steady state**, because they are not
   compatible and the tree is currently in neither. A backend that refuses
   unclassified comparisons needs every callee annotated to be usable at all;
   a backend that lowers them is silently wrong on strings. `doc/ABI.md` and
   `FORMAL_string_value_model.md` should state the rule once, and the hostmods
   should be held to it.

## The same root cause, a different door

`FORMAL_pathlib_suite_is_two_of_seven_on_an_unannotated_param_compared_to_a_string`
is the same gap through the PARAMETER rather than the CALLEE, and its fix is
two annotations instead of 107. Read it first: it is the cheaper half and it is
what makes the shape of the problem visible. (Named by slug, not by path, and
kept on one line for the reason
`TOOLS_deleting_a_bug_doc_leaves_dangling_pointers` §"That scan is a FLOOR"
gives: a citation broken across two lines is invisible to a path-based check.)

## Not this

- **Not** the cross-dylib declaration work in this merge. `_name_len` is a
  private helper called from inside `argparse.mojo`; nothing crosses a module
  boundary on this path, no manifest is consulted, and
  `git diff integ HEAD -- formal/hostmods/argparse.mojo` is empty. The two
  mechanisms are unrelated and the diagnostic even reads differently — this one
  says "does not say what it returns", the pathlib one says "compares a NUMBER
  with a string".
- **Not** a defect in `integ`'s refusal. The refusal is right; a correct program
  taking the wrong branch is the worse outcome and this backend is built to
  refuse rather than emit it. What is wrong is that 107 well-behaved functions
  now sit inside its blast radius with nothing in the tree saying so.
