# CODEGEN_string_literal_whose_content_is_quoted_loses_its_quotes

## Status (2026-10-04, work/gatefix9 — reproduced, root-caused, NOT fixed here;
## an attempted fix regressed docstrings and was reverted)

A string literal whose CONTENT starts and ends with the other quote character
loses both quotes in the compiled path. CPython is the oracle and the compiled
program is wrong on the first case and right on the next four:

    x = "'x'"      # CPython: 'x'  (3 chars)   compiled: x    (1 char)
    y = "a'b'c"    # CPython: a'b'c (5)         compiled: a'b'c  (5)   ok
    z = 'say "hi"' # CPython: say "hi" (8)      compiled: same    (8)   ok
    v = "it's"     # CPython: it's (4)          compiled: same    (4)   ok
    w = ""         # CPython: '' (0)            compiled: same    (0)   ok

So the shape is exact: `first char == last char` and both are a quote
character. Everything else is untouched.

Reproduction, no self-host involved — the compiled path of a plain program:

    def main():
        x = "'x'"
        print(x, len(x))

    main()

`python3 test_gimple_runner.py` compiles and runs it and requires CPython's
stdout; it prints `x 1` against CPython's `'x' 3`. (Do it as
`test_gimple_matches_cpython("lit_quotes", ...)` in a scratch harness; the row
is NOT in the suite yet because the fix below is not.)

## Cause (measured, both halves)

**The parser strips the outer quotes, and then the codegen strips them again.**
`fire_compiler.py`'s `Parser` builds a `StringLiteral` whose `.value` is the
inner CONTENT (CPython's own convention — measured:

    p = Parser(list(py_tokenize('x = "\'x\'"')))
    lit = p.parse_module()[0].value
    repr(lit.value), len(lit.value)      ->  "'x'" 3

i.e. the 3-character string `'x'`, quotes included as CONTENT). But
`mojo/middle/resolve_shared.py::_decode_str_literal_text` — which
`_lower_StringLiteral` calls before interning the C literal — still assumes the
value may carry its delimiters and strips a matching first/last quote pair. Its
guard for "already stripped" is

    if not val or val[0] not in ('"', "'"):
        return prefix + val, ''

and a value that IS `'x'` passes straight through it, because `'x'` starts with
a quote. `rest[1:-1]` then returns `x`, and the emitted pool entry is
`static char * _slit_NNNNN = "x";` — which is what the compiled program prints.

The two cases the guard cannot tell apart are genuinely identical after the
prefix walk: a plain string whose content starts with a quote (`'x'`, already
stripped) and an f-string that keeps its delimiters (`f'x'` -> `'x'`).

## The fix, and why the obvious one is wrong

The discriminator has to come from the SOURCE, not the text, and the obvious
candidate is the prefix walk's own output — and that is a trap, which is why the
attempted fix was reverted:

    _has_ft_prefix = any(c in 'fFtT' for c in prefix)
    if not _has_ft_prefix and not (val.startswith(_dq3) or val.startswith(_sq3)):
        return prefix + val, ''

`prefix` comes from a walk that eats any leading `fFrRbBuUtT` character, so a
DOCSTRING beginning with a capital T ("The comma-separated SLOTS of ...")
yields `prefix == 'T'` — which IS in `fFtT` — and the guard then declines to
fire on a value that is plain content. Measured consequence on
`compile_to_gimple(open('fire_compiler.py').read(), do_imports=False)`: every
such docstring changed (`_slit_10029`, `_slit_10030`, `_slit_10036`, ...), and
`is_fstring` came back TRUE for them, so the f-string interpolation path ran
over docstrings that contain `{...}`. The self-hosted compiler then mis-lexed
`for` as a NAME instead of a KW (`stage2/array_ops_jit.tok` vs `stage1`'s, one
token different) and refused ordinary indented for-loops with
`Unexpected INDENT('')`. That is a whole class of breakage from one wrong
predicate.

So the shapes the fix must keep apart, with the discriminator for each:

| value after the prefix walk | prefix | meaning | action |
|---|---|---|---|
| `he comma-separated ...` | `T` | docstring; the T was CONTENT | return `prefix + val` |
| `'x'` | `` (empty) | plain string, content = `'x'`, already stripped | return verbatim |
| `'x'` | `f` | f/t-string, delimiters still attached | strip |
| `"""x"""` | `` (empty) | triple-quoted value from py_tokenize's placeholder cache | strip |

Rows 3 and 4 are the only ones that strip. The robust discriminator is NOT the
text: it is the parser's own record of the literal. `StringLiteral` already
carries `is_raw` / `is_bytes` (see `decoded_literal`'s comment in
fire_compiler.py, which reads exactly that flag), so adding `is_fstring` /
`quote_style` at construction time and passing it down — instead of re-guessing
from the text at three call sites (`_lower_StringLiteral`, the f-string
interpolation path, and the `%`-format path that all call
`_decode_str_literal_text`) — is the change that cannot repeat this bug.

Whichever way it is done, the two existing guards must survive it: the
`_all_quote` arm (a value that is ENTIRELY quote characters is content —
`'"""'` is this file's own literal) and the "no real prefix" reset (a prefix
walk that found no quote after the prefix-like run means the run was content).

## Tests to add with the fix

* `test_gimple_runner.py`, `test_gimple_matches_cpython`, CPython as the
  oracle: the five cases above, plus `'a'`, `"'ab'"`, `'"'`, `'"x"'`, `''''''`
  and a docstring starting with each of `f F r R b B u U t T` (that last group
  is what the reverted attempt broke).
* `test_string_literal_lexing.py` has 75 checks and passes both before and
  after, so it does not cover this: every case in it starts or ends with a
  NON-quote character.

## Why this is not in the branch that fixed the SEMICOLON class

They are the same family (quotes in string literals in the compiled path) and
they are different defects. `work/gatefix9` fixed the one that made the
self-hosted parser refuse two of the 46 bootstrap inputs
(`Unexpected SEMICOLON(';')` at fire_compiler.py:1301, an `int64_t` slot holding
a boxed string compared by its low byte — see the bug doc's Status entry), and
filed this one. Landing a fix for this that regresses every docstring is the
trade `CLAUDE.md` rules out: a wrong answer that is quiet is worse than a
refusal.