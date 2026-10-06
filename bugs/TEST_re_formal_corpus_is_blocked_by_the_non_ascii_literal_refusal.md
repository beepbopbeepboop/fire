# `test_re_formal.py` is red on 25 checks, and all of them are ONE refusal about a non-ASCII literal in `re.mojo`'s own source

**Area:** `test_re_formal.py` (the corpus) against `formal/build.py`'s
non-ASCII-literal refusal. **Found 2026-10-05** on `work/bugs7-4` while
consolidating the four hand-rolled "how did the child die" helpers into
`exec_budget.child_exit_reason`, and running this file as one of the four.
**Pre-existing**, proved by reverting this branch's `test_re_formal.py` diff
(`git apply -R` on a saved patch — never `git checkout <path>`) and re-running:
**1145/1170 both ways, same 25 rows.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label re -- python3 test_re_formal.py
1145/1170 checks passed
```

## What I saw

24 of the 25 are the same refusal on 12 corpus cases, once per architecture:

```
FAIL  [arm64] case 110 ('(?:→|->)' on 'a->b') builds: build failed: … This image
      holds a string literal that is not ASCII, so some string in it can have a
      character `base + 1` walks into. … For `s = "héllo"`, `s[0]` is 104 and
      `s[2]` is 108, which is `l`, and the wrong answers are the right answers
      for the NEIGHBOURING indices.
```

The 25th is the row that goes with it:

```
FAIL  test_imports.py is no longer refused for importing `re`: …
```

## What it actually is

`formal/hostmods/re.mojo` contains non-ASCII string literals — `(?:→|->)` and
friends are the module's own patterns — and `formal/build.py` refuses a build
whose image holds one, because on this path a `String` is a byte buffer walked
one byte at a time and a multi-byte character means `base + 1` can land inside
one. The refusal's own reasoning is right; what is missing is the way to say
"these particular literals are safe": a `re` module is inherently full of
non-ASCII text and there is no ASCII spelling of `→`.

The corpus is therefore being run against a module the compiler cannot build, so
it measures nothing for the 12 patterns that use non-ASCII, and
`test_imports.py`'s row — which exists to prove `re` is still refused — is
satisfied by the wrong refusal.

## Next step

One of two, and the choice belongs to whoever owns the non-ASCII refusal
(`formal/build.py`'s non-ASCII literal gate, which `formal/hostmods/ast.mojo`'s
and `argparse.mojo`'s decode work touched):

* **Teach the path to carry a multi-byte character.** The refusal's arithmetic
  (`base + 1` walks into a character) is about a `String` subscript and a `len`,
  so the real fix is a character-aware length/index for the host modules, which
  is a representation change and wants its own bug doc rather than a drive-by.
* **Or declare the literals safe the way the tree already declares other facts**,
  if it has a mechanism for that: a per-literal attribute, or an ESCAPE the
  literal layer expands to bytes, so `→` is written `\u2192` in the source and
  the image holds the two bytes the module actually wants to match. This is the
  smaller change and it is the one the corpus needs to become meaningful again.

Either way, `test_re_formal.py` should not be green-by-exclusion: if
`re.mojo` cannot be built, the 12 non-ASCII cases should be SKIPPED with the
reason printed (the harness has a `SKIP` status for this) rather than counted as
failures against a module that never reached an image.