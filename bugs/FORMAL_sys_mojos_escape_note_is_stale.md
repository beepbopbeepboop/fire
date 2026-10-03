# FORMAL_sys_mojos_escape_note_is_stale: two `test_formal_sys.py` failures that predate the 2026-10-02 sweep work

**Status: OPEN. NOT fixed. NOT caused by anything in the
`sweep5:hostmods-more` claim; found while running the tree's own suites after
writing four host modules, and recorded because a red nobody has written down is
a red the integrator will rediscover.**

## What I ran and what I saw

    $ python3 test_formal_sys.py
    formal sys: PASS=10 FAIL=2

Two failures, both about a `printf` of a string with an escape in it:

```
FAIL  the two writers reach the right descriptors
      stderr was 'to stderr\n', expected the literal bytes 'to stderr\n'
      — see the escape test for why
FAIL  string escapes are not interpreted
      stderr was 'a\nb': string escapes are now interpreted on this path, so
      sys.mojo's note about real newlines is stale
```

The first is the same fact seen from the other side: the image printed a real
newline where the test expected the two characters `\` and `n`. The second says
it outright — **string escapes ARE now interpreted on this path**, and a test
asserting they are not, plus a `formal/hostmods/sys.mojo` docstring asserting
the same, are both stale.

## Why it is not mine

`git diff --stat 24068a01 HEAD` over the four commits of the
`sweep5:hostmods-more` claim touches 14 files, and neither
`formal/hostmods/sys.mojo` nor `test_formal_sys.py` is among them;
`formal/hostmods/sys.mojo` has no import from `formal/hostmods/os/_syscalls.mojo`,
which is the only existing file that claim modified. The last commits to touch
either file are `43d0ca09` and `808e94a2`, from the `mod-sys` / `mod-struct` work
merged long before this sweep.

**The one failure in that file that WAS mine** — the third, `the sweep calls a
sys refusal a codegen finding` — is fixed in the same commit as this note, and
the fix is worth reading because it is the third time in this sweep that a test
used "a module with no source" as its example and the module got written:
`test_formal_link_accounting.py` used `math` and `test_formal_sys.py` used
`math`, both now `decimal`. A name that is an example of "nothing here can answer
this" stops being one the day something here can.

## The next step, exactly

Someone who owns the string-literal lowering should decide which of the two is
the truth, and then fix BOTH the test and the docstring, because they currently
agree with each other and both disagree with the image:

  * if escapes ARE interpreted, delete the note at the top of
    `formal/hostmods/sys.mojo` that says they are not, and invert
    `test_formal_sys.py`'s escape group — **and check the consequence**, because
    every hostmod test in this tree that needs a record separator says in its
    own docstring that a Mojo string literal's BACKSLASH-N is not unescaped and
    therefore chose `@@` as its terminator. `test_formal_json.py`'s `mask()`
    escapes every awkward byte as `~xHH` for the same reason. If the image now
    unescapes them, those corpora could be simplified and the reasoning in at
    least five files is wrong — which is a much larger cleanup than the two
    failures, and is the reason this is filed rather than fixed.
  * if escapes are NOT interpreted and something regressed, the bug is in the
    lexer and the two failures are its evidence.

Until that decision is made the corpus spellings should stay as they are: they
are correct under BOTH answers, which is what makes them worth having.
