# PARSE_FAIL_an_ordinary_string_whose_text_starts_with_an_f_prefix

**Status: open, filed 2026-10-03 by `work/formal19-fuzz-3` (the `fuzz-3` sweep).**
Not the f-string miscompile it was found beside — that one is fixed — but the
AST shape underneath it, which three readers share and none of them can
distinguish.

## What I ran

Three one-line programs, each a `def main` that binds one ordinary string and
prints it. CPython 3.14.7, this repo's interpreter, this repo's compiled path
(`fire.py build`), and the formal path (`fire.py build --formal --no-prove`):

| source | value the parser produced | CPython | `fire.py run` | compiled | formal |
|---|---|---|---|---|---|
| `s = 'f"n"'` | `f"n"` | `f"n"` | **`n`** | **`n`** | refused |
| `t = "t'x'"` | `t'x'` | `t'x'` | **`x`** | **`x`** | refused |
| `s = "f\"n\""` | `f\"n\"` | `f"n"` | `f"n"` | `f"n"` | builds, prints `f"n"` |

The commands, verbatim:

    $ printf 'def main() -> Int32:\n    s = %s\n    print(s)\n    return 0\n' "'f\"n\"'" > three.mojo
    $ python3 three.mojo; python3 fire.py run three.mojo
    f"n"
    n
    $ python3 fire.py build -o three.bin three.mojo && ./three.bin
    f"n"
    n
    $ python3 fire.py build --formal --no-prove --backend=arm64 -o three.arm64 three.mojo
    build: an f-string literal on line 2 is refused on this path: …

## What I expected

`f"n"` and `t'x'` on every engine. Neither line has an `f` or `t` prefix, no
braces, and nothing that asks for interpolation: the letter is the first
character of the string's own TEXT.

## What I saw

The interpreter and the compiled path **silently printed a different string**
(`n`, `x`) with exit status 0 — in the two engines whose whole subject is
running real Mojo. The formal path refuses the same two programs by name
(`formal/model.py`'s `is_interpolated_literal`), which is honest but is a
refusal of correct code.

The third row is the control, and it is why the shape is stated precisely: with
the outer and inner quote characters THE SAME, the escape `\"` survives into
`StringLiteral.value`, so the value starts `f\` rather than `f"` and every
reader gets it right. Only the two spellings where the inner quote differs from
the outer one — and therefore needs no escaping — are misread.

## Why

`fire_compiler.replace_tstrings_with_placeholders` puts an interpolated
literal's WHOLE SOURCE TOKEN into `string_cache` under a `__MOJO_STR_n__` name,
and `Parser._strip_string_prefix_and_quotes` deliberately leaves `f`/`F`/`t`/`T`
prefixed tokens intact so a reader can tell interpolation is needed. The
`StringLiteral` therefore carries its `f"` as the first two characters of its
`value`, and every reader decides "is this interpolated?" with

    value.startswith(('f"', "f'", 't"', "t'", …))

— `myinterpreter.eval_StringLiteral`, `gimple_codegen._lower_StringLiteral`, and
(now) `formal/model.py:is_interpolated_literal`. An ordinary literal's `value`
is its BODY, and a body can start with any character at all, so on this axis the
two shapes are the same shape.

`StringLiteral` already carries `is_bytes` and `is_raw` beside `value`; the
interpolated case is the third flag it does not carry.

## Exact next step

Set the flag where the shape is decided, not in a reader of the value:

1. `fire_compiler.py`, the `StringLiteral` construction site (~line 5266):
   pass a new `is_interpolated=` flag. The predicate already exists and already
   takes the right evidence — `Parser._raw_string_is_ftstring(raw)`, where `raw`
   is the SOURCE TOKEN, which is the one thing that distinguishes `f"n={n}"` from
   `'f"n"'` and that is discarded by the time the node is built. A synthesized
   literal (no source token) passes `False`, as does a plain `str` — the same
   convention `is_raw` follows.
2. `StringLiteral` gains the field WITH A DEFAULT, so every existing
   construction site (`gimple_codegen`, `formal/model.py`, the `mojo/` mirror)
   is unaffected and no call site has to change.
3. The three readers consult the flag instead of the value's first character:
   `myinterpreter.eval_StringLiteral`, `gimple_codegen._lower_StringLiteral`,
   `formal/model.py:is_interpolated_literal`. `INTERPOLATED_LITERAL_PREFIXES`
   then has no reader and can go.

**Then re-run this doc's first two rows**: all three engines must print `f"n"`
and `t'x'`, and the formal path must BUILD and run them rather than refuse.
`test_formal_run.py`'s `braces_in_an_ordinary_string_are_not_a_fstring` is the
guard for the over-refusing direction; this document's program is the case
missing beside it and belongs there when step 1 lands.

## What this cost, so the next reader does not have to measure it again

- The formal backends' f-string miscompile — printing the literal's own source
  spelling, exit 0, on both architectures, where the interpreter and CPython both
  print `n=7` — is fixed and pinned by `test_formal_run.py`'s
  `fstring_literal_refused` and `tstring_literal_refused`. That fix is a
  REFUSAL, so this document is what is left of it: once the flag exists, those
  two cases can build and print the parts instead, and the program here becomes a
  `match` rather than a refusal.
- `formal/model.py:is_interpolated_literal`'s docstring states the limit and
  cites this doc, so the reader that inherits the prefix test knows it is
  reading a workaround rather than a rule.
