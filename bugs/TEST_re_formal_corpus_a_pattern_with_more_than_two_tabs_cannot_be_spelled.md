# TEST_re_formal_corpus_a_pattern_with_more_than_two_tabs_cannot_be_spelled: two `test_re_formal.py` checks are red on an `assert` in the test's own string encoder

**Area:** TEST (`test_re_formal.py::mojo_str`) · **Status:** OPEN, measured
2026-10-04 on `master` at `3c3516db` · **Layer:** not the formal backend at all —
the capability exists and answers correctly

Found while running the formal test files for
`bugs/FORMAL_sweep20_std_collections_2.md` §5.4. It is **not** caused by that
branch's change: measured identical with `master`'s `formal/imports.py`
restored, and the failure is an `assert` in the test's own helper that runs
before any build.

## 1. What is red, and where

```
$ python3 tools/memslot.py --gb 8 --label ref -- python3 test_re_formal.py
FAIL  test_mojo_str_round_trips_through_the_decoder raised: AssertionError('^[ \t]*typedef[ \t]+(?P<target>[^;{}=]+?)[ \t]*(?P<name>[A-Za-z_]\\w*)[ \t]*;')
FAIL  test_the_corpus_patterns_all_work raised: AssertionError('^[ \t]*typedef[ \t]+(?P<target>[^;{}=]+?)[ \t]*(?P<name>[A-Za-z_]\\w*)[ \t]*;')

1176/1178 checks passed
```

`.tmp/probe_re_tb.py` (scratch) calls the two functions directly and prints the
traceback, which names the line:

```
File "test_re_formal.py", line 367, in mojo_str
    assert len(parts) <= 3, s
AssertionError: ^[ \t]*typedef[ \t]+(?P<target>[^;{}=]+?)[ \t]*(?P<name>[A-Za-z_]\w*) [ \t]*;
```

## 2. The cause, in one paragraph

`mojo_str` spells a string as a Mojo literal, and a real **newline or tab**
cannot go in one, so it splits on it and composes `os._syscalls`' `mk2` (one
separator) or `mk3` (two). **The assertion is that helper's own limit, and it
is two separators.** The pattern is `reflect.py:677`'s C-`typedef` finder, and
`[ \t]` appears in it **four** times, so `s.split("\t")` yields five parts and
the encoder cannot spell the string at all.

That pattern is in the corpus because `corpus_patterns()` walks every
`re.compile(r"…")` in this repository's own `*.py` and keeps anything longer
than 8 characters containing both `{` and `\w` — which is a real pattern this
compiler uses, on its own reflection path, to find C typedefs.

## 3. The capability is NOT missing: the hostmod answers this pattern correctly

This is the part worth recording, because "the corpus pattern does not work" and
"the test cannot spell the corpus pattern" want opposite next steps.
`.tmp/probe_re_typedef.py` (scratch) builds ONE program that runs
`formal/hostmods/re.mojo`'s `re.search` over four (pattern, subject) pairs and
prints CPython's answer beside it, arm64:

| pattern | subject | CPython | hostmod |
|---|---|---|---|
| the `reflect.py` pattern, named groups | `typedef int foo;` | at=0 len=16 | status=1 at=0 len=16 |
| the same | `typedef struct foo[T] bar;` | at=0 len=26 | status=1 at=0 len=26 |
| the same with `(?:…)` instead of `(?P<…>)` | `typedef struct foo[T] bar;` | at=0 len=26 | status=1 at=0 len=26 |
| the same, an empty name | `typedef ;` | no match | status=0 |

**Four for four, including the span and the length.** So `formal/hostmods/re.mojo`
is right about this pattern, its lazy `+?`, and its named groups, and nothing in
`formal/` needs to change. The two red checks are `test_re_formal.py`'s own
harness refusing to write the string down.

## 4. The exact next step

1. Give `mojo_str` a spelling for an ARBITRARY number of separators. `mk2` and
   `mk3` are fixed-arity functions in `formal/hostmods/os/_syscalls.mojo`, and
   nesting them does not work (an inner `mk2`'s buffer has no room for the
   outer one's), so this is either a new `mkN`-style entry point or a
   `memcpy`-based join in the PRELUDE. **Whichever it is, it belongs in the
   `formal-re` line, not in a sweep round** — this file's `mojo_str` docstring
   is a careful account of why each escape is spelled the way it is, and adding
   a shape to it is that work.
2. Until then, the corpus is **one pattern short of the check it exists for**,
   and `test_the_corpus_patterns_all_work`'s own docstring is explicit that a
   corpus shape the module refuses is "a real finding about the module" — so the
   finding here is in the harness, and the honest state is that this pattern is
   currently untested rather than that it works.
3. Do **not** "fix" it by adding the pattern to an exclusion list: the test's
   own comment says a drop has to be accounted for by name and by reason, and
   this one drops for a reason that is neither CPython's nor the module's.

## 5. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label ref -- python3 test_re_formal.py
python3 tools/memslot.py --gb 8 --label retb -- python3 .tmp/probe_re_tb.py   # the traceback
python3 tools/memslot.py --gb 8 --label re -- python3 .tmp/probe_re_typedef.py  # §3's table

sed -n '360,372p' test_re_formal.py     # the assert
sed -n '677p'       reflect.py          # the pattern, and where it comes from
grep -n 'mk2\|mk3' formal/hostmods/os/_syscalls.mojo
```

Scratch, not committed: `.tmp/probe_re_tb.py`, `.tmp/probe_re_typedef.py`.
