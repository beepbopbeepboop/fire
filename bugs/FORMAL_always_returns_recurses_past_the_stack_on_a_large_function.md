# FORMAL_always_returns_recurses_past_the_stack_on_a_large_function: a few hundred statements in one function crashes the backend

**Status: OPEN. Found while writing `hashlib`'s test (2026-09-29, the
`module:hashlib` claim); the crash is in `formal/arm64_codegen.py`, which that
claim does not own, so it is filed rather than applied. Until it lands,
`test_formal_hashlib.py` builds many SMALL programs instead of one large
one — see the last section.**

This is the sweep's `backend-crash` class: the backend RAISES instead of
refusing, which is a bug in the compiler's own plumbing and not a claim about
the source under test. It is worth writing down because the input that
provokes it is not exotic — it is a straight-line function of a few hundred
`printf` calls, which is exactly the shape a generated test program has.

---

## What I ran

`test_formal_hashlib.py`'s BLAKE2b group generates one program per case:

```python
    lines = ["import hashlib", "", "def main() -> int:"]
    for n in lens:
        lines.append(f"  var m{n}: Pointer[UInt8] = malloc({max(n, 1)})")
        lines.append(f"  memset(m{n}, 97, {n})")
        for d in BLAKE2B_DIGEST_SIZES:
            lines.append(f'  printf("b{n}_{d}=%s@@", '
                         f'hashlib.blake2b_hex(m{n}, {n}, {d}))')
    lines.append("  return 0")
```

which is 188 message lengths × 6 digest sizes = 1128 `printf` calls plus 376
`var`/`memset` pairs, all in one `main`. The build:

```
  File "formal/arm64_codegen.py", line 7051, in _always_returns
    return _always_returns(rest)
  File "formal/arm64_codegen.py", line 7051, in _always_returns
    return _always_returns(rest)
  ...
  [Previous line repeated 990 more times]
RecursionError: maximum recursion depth exceeded
```

No `build:` prefix, no source line, no construct named: the traceback is the
whole diagnostic, and it names a function whose name says nothing about the
program.

## What I saw

`formal/arm64_codegen.py:7051` is one line inside a recursive walk:

```python
            return _always_returns(rest)
```

`_always_returns` recurses once per statement in the function, so a function
of N statements needs N Python frames. CPython's default limit is 1000, so the
crash arrives at a little over a thousand statements — which is 1,504 here.
The CommonCrypto group, at 54 `printf` calls, is nowhere near it and builds
fine; the BLAKE2b group, at 1,504 statements, does not.

Nothing about the SOURCE is wrong. Every statement in the generated program is
a `var`, a `memset` or a `printf`, all of which lower, and the same cases
build and RUN correctly once they are split across several smaller programs —
which is how the test passes now, with 47 builds of 24 cases each.

## Why it matters beyond this test

A `RecursionError` is the worst class of failure for a batch job, because it
is **not content-addressed away and not classified**:

- `cas.py` keys on inputs, so a crash is re-run rather than replayed — good —
  but it means every run of a suite with a large generated program pays for
  the crash again, and a crash in worker 3 of 18 can take down the batch
  rather than one case.
- `tools/formal_sweep.py` has a `backend-crash` class precisely for this, so
  the sweep reports it honestly. Individual test files do not all have that
  path, and this one surfaced as a bare traceback in a test's output.

And the scale is not large in any meaningful sense. A Mojo file with 1,500
statements in one function is not a curiosity: it is what a code GENERATOR
produces, and generating code is what this compiler is for.

## What I expect

Either of two things:

1. **The walk becomes iterative.** `_always_returns` is a
   worklist/recursive-descent question with no need for recursion: the
   statements of a block can be walked with an explicit stack, or — since the
   question is "does control always reach a `return`" — with a simple
   forward scan per compound statement, recursing only over NESTED blocks
   rather than over siblings. Nested blocks are bounded by the block depth,
   which is small, so this removes the limit entirely.
2. **A named diagnostic at a size the backend can handle.** If a 1,500-statement
   function is genuinely too much for this pass, the build should say
   `main: 1504 statements in one function exceeds the 1000 the
   always-returns analysis walks`, in the shape every other refusal in this
   tree uses. That is a smaller change than (1) and it converts a traceback
   into a diagnosis.

(1) is the better answer and is probably a small diff; (2) is what to do if
(1) turns out to be awkward. Both are worth having: (1) because the limit is
artificial, (2) because a raised exception should never be the only thing a
user sees.

## The exact next step

1. **Make it iterative** in `_always_returns`, keeping the same predicate. The
   function's answer must not change for any input that works today, so the
   test to write with it is: the existing `test_formal_run.py` cases that
   exercise `return`-in-a-branch, `return`-in-a-loop and
   `no-return-at-all` must give the same answers before and after. That is a
   behaviour-preserving refactor, and the standard for it is in `CLAUDE.md`:
   byte-identical output on a large succeeding case, before and after.

2. **Raise the recursion limit as a stopgap only if (1) is not immediate** —
   and if you do, do it in `fire.py`'s build entry rather than globally, and
   say so in a comment, because a global `sys.setrecursionlimit` in a library
   changes every caller including `cas.py`'s workers.

3. **A test for it**, in `test_formal_run.py`: a generated function of 2,000
   straight-line `printf` calls, asserting the image BUILDS AND RUNS. It is a
   small generator and about eight lines, and it is the only assertion that
   can catch a regression here — today the failure is a crash, so a test that
   only ran small functions would not notice it.

**Checked and NOT the same bug:** this is not the stack-frame *layout*
question (`FORMAL_pointer_value_model.md` and the frame-field family), which
is about what a frame contains; this is the analysis that walks the AST
before any frame exists.

## What the test does in the meantime

`test_formal_hashlib.py` builds **47 small programs instead of one large
one**, 24 cases each, through a `_chunks` helper whose docstring says why. The
cost is 47 module builds instead of one; the benefit is that a case can fail
on its own terms — the chunk is ordered by message length, so a failure in the
first chunk is about a short message, which is where the block-reading bug
that started this lives. The helper is worth keeping either way: even with
(1) fixed, a test that builds 24 cases at a time fails in 24-case units, which
is a better failure message than "one of 1,128 is wrong".
