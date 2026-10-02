# `test_gimple.py`'s py_tokenize signature check fails on HEAD: the two hand-written C declarations say 2 parameters, the source now takes 1

**Area:** TEST_GIMPLE (the check) against `gimple_codegen.GimpleGen._KNOWN_SIGS`
and `runtime/fire_runtime.h` (the two hand-written C spellings). **Found
2026-10-01 on `work/bugs3-codegen-2`; NOT fixed here, and not this branch's
claim** — it arrived from `7ce61398`, which is on master.

## What I ran and what it showed

```
$ python3 test_gimple.py
...
FAIL  handwritten_selfhost_signature_tables_match_the_source:
  py_tokenize: table declares 2 C parameter(s), the source takes 1 (['src']) —
  a DEFAULTED parameter still occupies a C parameter slot
...
Results: 348 passed, 1 failed
```

Every other case in that suite passes, and the failure is the only one this
branch's changes could plausibly have caused — which is why it is worth writing
down rather than re-deriving. It is not caused by them: the check derives its
expectation from `inspect.signature(fire_compiler.py_tokenize)` and compares it
against two hand-written tables, and this branch's diff touches neither
(`mojo/backend_gimple/emit_exprs.py`, `runtime/fire_runtime.{c,h}`,
`test_container_equality.py`, `test_runtime_header_scan.py`).

## The three numbers, measured

```python
>>> inspect.signature(fire_compiler.py_tokenize)
(src: 'str') -> 'list[Token]'
>>> gimple_codegen.GimpleGen._KNOWN_SIGS['py_tokenize']
('MojoList *', ['char *', 'char *'])
>>> grep 'py_tokenize' runtime/fire_runtime.h:1787
MojoList *py_tokenize(char *source, char *filename);
```

So the source says **1**, and BOTH hand-written C spellings say **2** — and
those two agree with each other. The check counts `POSITIONAL_ONLY` /
`POSITIONAL_OR_KEYWORD` parameters of the Python function, which is 1.

## What happened, from the commit that caused it

`fd10fd92` gave `py_tokenize` a second, DEFAULTED parameter (`filename`, used
only to prefix the unterminated-string diagnostic). `7ce61398` — "lexer:
`py_tokenize` keeps its one-argument ABI; the filename variant gets a name" —
reverted that and introduced a separately-named variant instead, on the grounds
that `py_tokenize` is a **pinned C ABI symbol** (it is in
`GimpleGen._NO_OVERLOAD_MANGLE`, and its C declaration is written by hand in
the header).

That reasoning is right about the symbol and it fixed the Python side, but it
did not touch either of the two hand-written C declarations, so all three were
left disagreeing. Note the direction of the drift this time: the tables are
AHEAD of the source, where the check's own docstring describes the historical
drift as the tables being BEHIND it. Same class, opposite sign — which is why
the check is worth keeping rather than deleting now that it has fired.

## Why this matters beyond one red test

The two tables are not documentation. `_KNOWN_SIGS` is what the compiled path
emits a forward declaration from, and the header's declaration is what every
already-generated `.ci` file takes its prototype from rather than declaring for
itself. So a table that says 2 while the source takes 1 is a self-host build
that emits `py_tokenize(a, b)` calls against a one-parameter definition — an
argument-count mismatch in the closure, which is the exact failure the check
was written to catch in this direction.

## Exact next step

Decide which of the three numbers is the answer, then make the other two agree
— it is a three-line change either way, and which one is right is the whole
question:

* **`_KNOWN_SIGS` and the header drop to one parameter** (`['char *']`,
  `py_tokenize(char *source)`), which matches `7ce61398`'s stated intent. Then
  the generated closure calls `py_tokenize(src)` and the check passes.
* **the source keeps two** (re-expose the default), which contradicts the
  commit's subject and puts the pinned ABI back at risk.

The header comment at `runtime/fire_runtime.h:1781-1787` currently asserts the
two-parameter shape and explains why ("or every --dump-full" build fails with
"too many arguments to function 'py_tokenize'"), so whichever way it goes, that
comment is part of the change.

Verify with the whole file (it has no `-k` filter — the runner ignores one and
runs every case, so a `-k` invocation reads as if it narrowed anything):

```
python3 test_gimple.py
```

and then `make check-selfhost` / `make bootstrap`, since those are the steps
that actually exercise the closure's `py_tokenize` calls — a green
`test_gimple.py` alone does not, which is the same structural blindness the
gate section of `CLAUDE.md` describes.