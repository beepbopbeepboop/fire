# FORMAL: `re.mojo`'s `\b` never matches, `re.VERBOSE` is accepted and ignored, and `\\` is refused — all three masked until `re.mojo` built at all

**Area:** FORMAL (`formal/hostmods/re.mojo`, the regex engine's matcher and
parser). **Status: OPEN — 7 wrong answers and 1 refusal in a module whose own
test suite says it is "CPython's `re`, span for span and character for
character". None of it is caused by anything recent: every case here was
already wrong and had never been RUN, because `re.mojo` did not compile at
all. NOT FIXED HERE — the engine is not this slice's, and the next step below
is a localisation rather than a patch.**

## What I ran

```
$ python3 test_re_formal.py
  994/1008 checks passed

# …with formal/model.py reverted to master's bytes:
  6/264 checks passed
```

The 14 failures are **7 cases × 2 architectures**, and every one of them is an
arm64/x86-64 pair with the *same* wrong answer on both:

| case | pattern | subject | CPython | this engine |
|---|---|---|---|---|
| 47 | `\bfn\b` | `fn foo` | match 0–2 | **no match** |
| 48 | `\b fn\s+(\w+)\s*\[` | `fn foo[T]` | match 0–7, group 3–6 | **no match** |
| 50 | `\b` | `" x "` | match 1–1 | **no match** |
| 51 | `\bcat\b` | `the cat sat` | match 4–7 | **no match** |
| 108 | `\b(?:fn\|def)\s+(\w+)\s*\[` | `fn foo[T]` | match 0–7, group 3–6 | **no match** |
| 88 | `a  # comment\n b`, `re.VERBOSE` | `ab` | match 0–1 (`a`) | **match 0–2 (`ab`)** |
| 92 | `\\` | `a\b` | match 1–2 (`\`) | **status 3, "unsupported"** |

I dumped both value lists through the test's own generator rather than
describing them, so the divergence is a named position and not a length:

```
C47  image    -99 0 -99 0 -1 -1  …            <- position 3 is the search STATUS: 0
     CPython  -99 0 -99 1 0 2  …               <-                             1
C92  image    -99 0 -99 3 -1 -1  …            <- status 3 = re.mojo's "unsupported"
C88  image    -99 0 -99 1 0 2  … 97 98        <- matched "ab"
     CPython  -99 0 -99 1 0 1  … 97            <- matched "a"
```

`_P_ERR = 3` is re.mojo's "unsupported", so **case 92 is a refusal** and the
other six are **wrong answers**. A refusal is the good outcome on this
backend's own terms; five of these six are not.

## `\b` never matches — in any position, and that is the whole of the 47/48/50/51/108 family

Four probes through the same generator, each isolating one variable:

| pattern | subject | CPython | this engine |
|---|---|---|---|
| `\bfn` | `fn foo` | match 0–2 | **no match** |
| `fn\b` | `fn foo` | match 0–2 | **no match** |
| `fn\B` | `fn foo` | no match | no match ✓ *(right answer, wrong reason)* |
| `\b` | `" x "` | match 1–1 | **no match** |
| `a\b` | `ab` | no match | no match ✓ *(right answer, wrong reason)* |

**`OP_WORDB` is dead.** Every `\b` in the language reports "no match", and the
two rows that agree with CPython agree by accident: `a\b` between two word
characters must not match, and a matcher that never matches anything gets that
one right.

This is a *wrong answer* and not a refusal, which is the outcome this backend
exists to prevent, and it is not a rare shape: the module's own header says
`\b` is needed by `elaborate.py`, `reflect.py` and
`consolidate_string_pool.py`, so every caller of those three gets a regex engine
that silently matches nothing.

## The next step, and it is a localisation rather than a rewrite

Everything on the compile side is already there and looks right, which is why
the fault is findable:

* `_p_esc` (`formal/hostmods/re.mojo:763`) emits `_term(a, OP_WORDB, 1, 0, 0, nxt)`
  for `\b` and `want = 0` for `\B`;
* `_worb` (`:1564`) is **correct in its own terms** — it takes the bytes either
  side of `sp`, asks `_isw` about each, and returns 1 exactly when they differ
  for `want == 1`;
* the matcher has the arm — `_st_run`'s `if op == 9:` at `:1744` calls `_worb`
  with `_pa(a, _P_SP)` and the node's arg 1, advances `_P_PC` and returns 2.

So the compiled node, the predicate and the dispatch all exist, and the arm
either is never reached or always evaluates false. **Two candidates, in the
order I would check them:**

1. **The start position the search hands the assertion.** Every probe fails at
   *every* start, including `fn\b` on `fn foo` where the boundary is at 2 and
   three earlier starts have already been tried — so if the arm is reached with
   a stale `_P_SP`, the first-iteration hypothesis is wrong and it is reached
   with the wrong position on each. Instrument the arm: print `pc`, `op`,
   `_pa(a, _P_SP)` and `_worb`'s return for the `\bfn` case and the answer is
   one build.
2. **`_next`'s target when an assertion is the first or the only node.** For a
   bare `\b` the chain is a single node, so `nxt` is whatever the concatenation
   passed down; if that is `0`, the node points at itself and the program can
   never leave the assertion. This explains the bare-`\b` row on its own and
   not the others, so it is second — but it is the reason a bare `\b` deserves
   its own row in whatever test lands, because it is a different bug from a
   misplaced assertion.

**Two smaller items, separable and cheap:**

* **`re.VERBOSE` is parsed and then ignored** (case 88). The flags reach the
  engine — `_bol`/`_eol` are handed `flags` — so the flag is threaded; the
  pattern's `#`-to-end-of-line and unescaped-whitespace stripping in `_prepare`
  is what is missing. Either strip it there or refuse `re.VERBOSE` by name, and
  the second is a few lines and removes a wrong answer today. **Refusing is the
  better first move** for the same reason case 92's refusal is: a wrong answer
  is worse than no answer.
* **`\\` is refused as unsupported** (case 92). `_escbyte` handles the
  byte escapes and `\101`, and an escaped backslash falls through to it without
  producing a byte. One more arm, or it stays refused — and while it stays
  refused it should be refused by the test's own "unsupported constructs are
  refused" convention rather than as a case that expects CPython's answer and
  fails.

## Why this was invisible, and the thing worth carrying forward

`formal/hostmods/re.mojo` **did not compile** until
`bugs/FORMAL_a_local_read_before_its_first_assignment.md`'s sibling — a
`_build_cfg` edge that gave a function's trailing loop a false predecessor and
made `_p_alt`'s `pend` look unstored — was removed (commit `91db24b9`, in the
`sweep:repo-b` branch). Before that, `test_re_formal.py` scored **6 of 264**,
which read as "the suite is red" and was in fact "the module does not build, so
almost nothing is being measured".

The generalisable half: **a suite that cannot build its subject reports a small
denominator, and a small denominator is indistinguishable from a suite with few
cases.** Here 264 vs 1008 is the whole signal — the extra 744 checks were
always in the file, waiting for the module to compile. When a coverage suite's
pass count moves by an order of magnitude, the first question is whether the
denominator moved with it, and the answer here was that the *numerator* was
suppressed, not the other way round.

Note also that
`bugs/FORMAL_x86_64_hostmods_that_do_not_build.md` (claimed by `formal3-10-r2`)
tabulates `re.mojo` as **BUILD on arm64** as of 2026-09-30, so this refusal is
newer than that census; that doc's next step is unaffected, and this one is
about what the module *computes* rather than whether it links.