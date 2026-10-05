# `fire_compiler.py`'s tokenizer cannot lex a PEP 701 f-string whose replacement field spans LINES

**Area:** PARSE / COMPILE_FAIL — the compiled path's lexer, reached through the
formal sweep. Found 2026-10-04 on `work/formal30-sweep-b12` while writing
`bugs/FORMAL_sweep_work_map_2026-10-04_b12.md` §4.2; **1 file** in the corpus.

**Status: OPEN, not fixed.** It is a parser change rather than a formal one, it
is worth one file, and the session that found it had a sweep round and a 229-file
regression to land. The next step is below and it is small.

## What was run

Six shapes, each parsed through the compiler's own entry point, so the answer is
the lexer's and not a CPython comparison:

```
$ python3 -c 'import sys; sys.path.insert(0,"."); import fire_compiler as F
… for name, src in CASES: F.Parser(F.py_tokenize(src)).parse_module()'
  OK    nested same quote:          x = f"{d[\x27k\x27]}"
  OK    nested double quote:        x = f"{d["k"]}"
  OK    plain f-string:             x = f"a{b}c"
  OK    backslash continuation:     x = f"a{\<newline>  b}"
  FAIL  multiline f-string expression:  x = f"a {[os.path.basename(n)<newline>   for n in y]} b"
  FAIL  comment inside:               x = f"{a # note<newline>}"
```

Both failures are the same line in one place:

```
build: parse error: …/test_formal_libc_symbol.py:483:23: unterminated string literal
```

`test_formal_libc_symbol.py:482-484` is the shape that fails:

```python
        fails.append(f"expected exactly one glob dylib on the {arch} link "
                     f"line, got {[os.path.basename(n)
                                  for n in linked_dylibs(out)]}")
```

## What it is, and what it is not

**It is not the nested-quote half of PEP 701, which this lexer already does.**
`f"{d['k']}"` and `f"{d["k"]}"` both parse. That half is what
`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md` §72 is about
— that doc's concern is the 3.10 interpreter this path refuses to start under,
because `fire_compiler.py` emits PEP 701 into a proof file and 3.10 cannot parse
it back. **This is the other half**: 3.12+ *accepts* a replacement field that
spans lines, and this lexer stops the string at the newline.

So the two are independent, and this doc does not replace that one or the other.
`doc/PLAN.md:30` records a third, adjacent instance (`NAME('__notes__')**` in
`traceback.py`), so there are now three known holes in f-string lexing and no
single place that lists them.

## Why it matters more than one file

The sweep's class for this file is **`codegen`** — *"THE FINDING: the backend
refused a construct IN THIS FILE"* — and it got there from
`not-answerable/host-import` at `-11`. So one real repository file stopped being
a fact about the target and became a backend finding, and the finding is a
**lexer's** newline rule rather than anything about the formal value model. In a
sweep that reads `codegen` as "a construct in this file the backend cannot
lower", a lexer newline is indistinguishable from a missing feature, which is the
classification being slightly wrong in the direction that costs a reader time.

It is also the shape most likely to recur: a long comprehension inside an f-string
is ordinary Python, and this repository writes it.

## The next step

`fire_compiler.py`'s `py_tokenize` (and whatever reads an f-string's braces
afterwards). The minimal change is in the f-string scanner: when a `{` opens a
replacement field, **do not treat a newline as the end of the string** until the
matching `}` is closed, and skip a `#` comment to the end of its line rather than
reporting an unterminated literal. Both halves are in the tokenizer, not in the
parser, so this is a self-contained change with one caller.

Two things a fix has to keep, and both are already measured above:

* **nested same-quote braces must still lex** — `f"{d['k']}"` works today and a
  brace counter that does not understand quoting will break it;
* **the refusal must not become silent.** A string left unterminated is a parse
  error today, which is the right answer for a genuinely unterminated literal; the
  fix has to keep it for that case, or a typo becomes a wrong program.

Then re-sweep `test_formal_libc_symbol.py` and check it returns to
`not-answerable/host-import` — which is what it was at `-11`, and which is the
whole of what this bug is worth.
