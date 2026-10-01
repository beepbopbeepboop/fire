# FORMAL_comptime_string_print: a `comptime`-bound STRING prints as a NUMBER when it reaches `print` through one `var`

**Found 2026-09-29 while landing the target-query evaluator; PRE-EXISTING,
unrelated to it, and NOT FIXED here — it is in the `print` materialization path,
not in `construct:comptime-mlir-attr`.** Recorded because
`test_formal_target_queries.py` had to route a case around it, and because the
shape is a **silently wrong value**, which is the outcome this project treats as
worse than any refusal.

## The wrong answer

```
$ cat b7.mojo
def main():
    comptime OS = "darwin"
    var t = OS
    print("t=", t)

$ python3 fire.py build --formal --no-prove --backend=arm64 -o b7 b7.mojo && ./b7
Built: b7  [arm64/macho]
t= 4296786840                # arm64

$ python3 fire.py build --formal --no-prove --backend=x86_64 -o b7x b7.mojo && ./b7x
Built: b7x  [x86_64/macho]
t= 4300370841                # x86-64 — a DIFFERENT wrong number
```

Two numbers, one source, and neither is a string. This is the
"a formal value is one 64-bit word" model applied where the word is a `char *`:
the folded string is not interned, and `print` emits the word as an integer.

**The same program with an ordinary `var` prints correctly**, which is what
makes it a bug rather than a design limit:

```
$ cat b8.mojo
def main():
    var s = "darwin"
    var t = s
    print("t=", t)
$ … && ./b8
t= darwin                    # arm64 AND x86-64
```

So the defect is not "a string has no representation" — there is one, and
`b8` finds it. It is that a value arriving through a `comptime` binding does not
get it.

## The refusal that partly covers it, and why it is not enough

```
$ cat c2b.mojo
def main():
    comptime OS = "darwin"
    print("os=", OS)
$ python3 fire.py build --formal --no-prove --backend=arm64 -o c2b c2b.mojo
build: print() cannot tell whether IdentExpr is a string or a number on the
formal arm64 path, and guessing would print an address as if it were text (or a
number as if it were text). Annotate the name, or print a literal, or bind it to
a literal first
```

That refusal is **correct as a guard** and it is the only thing standing between
the wrong answer above and a direct `print(OS)`. It is not enough because the
guard can only see the AST: one `var` in between and the value is an ordinary
local whose origin it no longer knows.

## Measured boundaries, so the next step is a scope and not a search

| program | arm64 | x86-64 |
|---|---|---|
| `var s = "darwin"; print(s)` | builds, prints `darwin` | builds, prints `darwin` |
| `var s = "darwin"; var t = s; print(t)` | builds, prints `darwin` | builds, prints `darwin` |
| `comptime OS = "darwin"; print(OS)` | **refused** | (not measured; the arm64 message names the arch, so the x86-64 wording differs and should be checked) |
| `comptime OS = "darwin"; var t = OS; print(t)` | **builds, prints a number** | **builds, prints a different number** |
| `comptime N = 5; print(N)` | **refused** (same message — keyed on the read being an `IdentExpr`, not on its type) | — |
| `comptime N = 5; return N` | builds, exit 5 | — |
| `comptime N = 5; return N + 1` | builds, exit 6 | — |
| `comptime S = "ab"; return 1 if S == "ab" else 0` | builds, **exit 1 (correct)** | — |
| `comptime S = "ab"; var t = S; return 1 if t == "ab" else 0` | builds, **exit 1 (correct)** | — |
| `comptime S = "ab"` at MODULE level, read in a function | refused: `main: 'S' has no home` (an honest refusal) | — |

So: **comparison of the same value is correct, and only `print` is wrong.** That
narrows this to the `print` materialization, not to the comptime value model —
and it means the fix is local. It also means the *number* is not read from the
`comptime` binding at all but produced by the print path treating the word as a
scalar, which is the same shape as the register fall-through this suite has
refused elsewhere.

## The exact next step

1. Find the `print` argument classification in `formal/arm64_codegen.py` (the
   message quotes the architecture, so `formal/x86_64_codegen.py` has a twin
   with different wording — fix both in one pass, and note the wording
   difference while you are there). It is refusing on "is this read's type
   known", and a `comptime` binding IS known: `mojo/middle/comptime.py`'s rule 3
   is "every read of a bound name yields the constant", and the backends hold
   `_comptime_vals`.
2. Widen the test to "the read's value is not statically known" and accept a
   read whose value came from `_comptime_vals` — for a STRING, materialize the
   interned literal the binding holds rather than the word, so `b7` prints
   `darwin` and `b8` keeps printing `darwin`.
3. **Do not resolve the unclassifiable case by guessing.** A null pointer, a 0,
   or a stack address is exactly what the existing refusal exists to prevent;
   `b7`'s number is what guessing looks like.
4. Tests: `b7` as an EXECUTED case in `test_formal_run.py` (arm64 + x86-64 —
   and the x86-64 assertion matters, because the two wrong values differ and a
   fix that pins one number would pass one architecture and fail the other),
   and the `c2b` refusal as a `refuse:` case, which will go RED when step 2 lands
   and that is the point.
5. Then delete the note in `test_formal_target_queries.py` that points here and
   restore that case's `print` form.

## Why it was not fixed here

The construct under test is a `#kgen.param.expr<…>` target query. This is the
`print` emitter's argument classification, which `CLAUDE.md`'s "one
implementation" rule would have me fix in BOTH backends (two wordings, two
materialization paths) — a different change with its own suite, in an area the
claims table has other workers in. Fixing it here would also have meant landing
an unexecuted claim in a commit whose subject is something else.
