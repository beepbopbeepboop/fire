# CODEGEN: a backslash line continuation inside a RAW string literal is deleted, where CPython keeps it as content

**Status: OPEN, and deliberately so — it is the one shape of an otherwise-closed
defect, it is a documented divergence rather than a silent wrong answer of the
kind the rest of this was, and closing it is a change to how a string value
reaches the token stream.** Fixed 2026-09-30 for the three shapes that WERE
silent: see "What was fixed in the same commit" at the bottom.

## What I ran

```python
# raw.mojo
def main():
    a = r"x\
y"
    print(a)
    print(len(a))
    return 0
```

```console
$ python3 fire.py run raw.mojo
xy                     ← this tree
2
$ python3 raw.mojo      # with main() called
x\
y                     ← CPython
3
$ python3 fire.py build --formal --no-prove -o raw raw.mojo && ./raw
xy                     ← the arm64 image, and x86-64 agrees
2
```

The two architectures agree, and the interpreter agrees with them, because the
token is made once in `fire_compiler.py` and every consumer reads it.

## Why

CPython's tokenizer decides what a backslash-newline pair is worth BEFORE the
parser sees the token, and the decision is in the token's own TEXT. Measured
with `tokenize`, not inferred:

```python
>>> [t.string for t in tokenize.generate_tokens(io.StringIO('s = "a\\\nb"\n').readline)
...     if t.type == tokenize.STRING]
['"a\\nb"']                      # the pair is DELETED
>>> [t.string for t in tokenize.generate_tokens(io.StringIO('s = r"a\\\nb"\n').readline)
...     if t.type == tokenize.STRING]
['r"a\\\nb"']                    # the pair is KEPT — it is content
```

and the full matrix, from `eval` on the same 24 spellings (prefix × delimiter):

| literal | CPython | this tree |
|---|---|---|
| `"a\<nl>b"`, `'a\<nl>b'` | `ab` | `ab` ✓ |
| `b"a\<nl>b"` | `b'ab'` | `ab` ✓ (the `b` prefix is dropped; separate question) |
| `"""a\<nl>b"""`, `'''a\<nl>b'''` | `ab` | `a\<nl>b` ✗ |
| `r"a\<nl>b"` | `a\<nl>b` | `ab` ✗ |
| `r"""a\<nl>b"""` | `a\<nl>b` | `a\<nl>b` ✓ |

**So the rule is "the pair is deleted unless the literal is raw", and it is a
rule about token text** — which is exactly the contract this path's value is
stated over ("the value is the source text between the delimiters, no escape
processing", `test_string_literal_lexing.py`'s `LITERALS` table). A raw literal
is the one shape where the pair is part of that text, and this tree deletes it
anyway, because the line-joining pass in `py_tokenize` has no way to keep it:
**a value only reaches the token stream with a newline in it through the
placeholder `replace_multiline_strings` builds, and the join runs after it.**

The triple-quoted row above is the same fact seen from the other side — that one
IS placeholdered, so it keeps the pair, and CPython deletes it. It is pre-existing
and is part of the wider documented divergence that this path does not process
escapes at all (`"\n"` is four characters here and one in CPython), so it is
recorded here rather than claimed as a defect of its own. Both rows are pinned
as labelled divergences in `test_string_literal_lexing.py`'s `CONTINUATIONS`
table, so neither can drift unnoticed.

## What would close it

**One place, and it is the join itself.** The pair is deleted by
`fire_compiler.py`'s `py_tokenize`, in the loop that joins backslash-continued
lines (`joined`, just after `raw_lines = src.splitlines()`). It asks
`_ends_inside_string` whether the trailing backslash is inside a literal and
joins with nothing when it is; the fix is to ask a second question — *is the
literal raw?* — and, when it is, to route the pair through the placeholder
mechanism the triple-quoted path already uses, so the value keeps the two
characters:

1. `_literal_prefix(line, quote_start)` — the 0–2 letters immediately before the
   opening quote. `_string_prefix_start` (`fire_compiler.py`, used by the
   tokenizer for exactly this) already answers it, so this is a reuse and not a
   new scanner.
2. In the join, when the backslash is inside a RAW literal, put
   `__MOJO_STR_<n>__` in `joined` instead of deleting the pair, and set
   `string_cache[placeholder] = "\\\n"`.
3. The substitution in the token loop is currently `if kind == "NAME" and val in
   string_cache`, which cannot fire for a placeholder that lands *inside* a
   STRING token. It needs a second arm that substitutes placeholders in a
   STRING token's value. **That third step is the whole cost**, and it is the
   reason this is left open: the placeholder scheme was built for a literal
   that occupies a token by itself, and this is the first case where one lands
   in the middle of one.

**Cost: small in code, and the verification is the whole test file.** A
placeholder that is not substituted back would be a value reading
`__MOJO_STR_7__`, so the pin must be a byte-exact value assertion on a raw
literal with a continuation, compared against CPython's `a\<nl>b` — which is
what the `raw_keeps_the_pair_in_cpython_only` row in `CONTINUATIONS` is already
shaped for. `test_string_literal_lexing.py` builds three arm64 images and runs
them, so the fix is verifiable without a new harness.

## What is NOT the fix

Refusing the spelling. `r"a\<nl>b"` is valid Python, it is in CPython's own
test suite's grammar, and a refusal would be a regression: this path accepts it
today and produces a string.

## Measured reach

**Zero occurrences in this repository.** All 392 `.mojo` files reachable from
this worktree (98 here, 294 under `../modular/mojo/stdlib/std`) were scanned
for a line whose trailing backslash is inside a string literal: none. The token
stream and parse verdict of all 392 are **byte-identical** before and after the
commit that fixed the other three shapes. So this is a correctness item with no
coverage behind it, which is why it is filed with a pin and not chased.
