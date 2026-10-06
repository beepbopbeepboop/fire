# `interpolated_literal_segments` assumes a ONE-character prefix, so every `rf"…"` f-string is refused with a sentence that is false about the source

**Found 2026-10-05 by `work/formal41-sweep-b14`** (claim `sweep41:sweep-b14`),
reading the `other refusal` row of that round's sweep — `tools/wave2_extract_shared.py`,
the only file in the 768-file scope whose terminal refusal is this reader's.

**Status: NOT FIXED.** The fix is small and identified (§4); it is not this
branch's because the claim is the sweep, and because the change would sit in the
same neighbourhood as the branch's own `max`/`min` work without being part of it.
§5 is the measurement that says it is a real defect rather than a limitation.

## 1. What it says, and what is true

The source is `tools/wave2_extract_shared.py:112-122`:

```python
        text = re.sub(
            rf"^(\s*)from\s+{re.escape(old)}\s+import\s+",
            rf"\1from {new} import ",
            text,
            flags=re.M,
        )
```

and the sweep's verdict for the file, on `master` at `b83f2ed2`, both
architectures, is `codegen` with this terminal message:

```
an f-string literal on line 116 is refused on this path, and its text could not be
taken apart either: cannot read an interpolated literal from
'rf"^(\\s*)from\\s+{re.escape(old)}\\s+import\\s+"': the character after the prefix
is not a quote
```

**Every clause of the second half is false about the source.** The character
after the prefix IS a quote. The prefix is `rf`, two characters, and the reader
asked `spelled[1]`.

## 2. The mechanism, in one place

`formal/model.py::interpolated_literal_segments(spelled)` is handed the WHOLE
source token — an interpolated literal's `value` is its token, prefix and quotes
included, which is `fire_compiler.py`'s `_strip_string_prefix_and_quotes` and the
reason the reader can work at all. Its second statement is:

```python
    # The prefix is ONE character and it is still there — that is the whole of
    # why this is readable at all (`is_interpolated_literal` tests it), so the
    # quote is at index 1 and every test below is from THERE and not from 0.
    quote = spelled[1]
```

and `body = spelled[1 + len(term):-len(term)]` assumes the same one-character
width. So every f-string whose prefix is **two** characters — `rf`, `fr`, `Rb`,
`tR`, and any spelling with a redundant `u` — is refused, with a message that
names a missing quote that is not missing.

**The lexer above it already knows better.** `fire_compiler.py` grew
`_prefix_is_interpolated` on 2026-10-05 (`bugs/FORMAL_sweep_work_map_2026-10-05_b14.md`
§4.2 — the round that measured it; the `-b13` map that said so first was deleted
when `-b14` replaced it, and this citation is the `doc-refs` ratchet's one
actionable finding) and `replace_multiline_strings` computes a prefix boundary in
`_string_prefix_start`. **This reader is one layer down and did not follow**, so the
two disagree about what a prefix is in the same tree — which is the shape of
defect `string_operand_is_string`'s docstring calls *"two answers that can drift"*.

## 3. What it costs, measured

```
$ python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-14.txt
  5       5  other refusal            # the bucket that means NOBODY HAS CLASSIFIED THIS
```

One file in a 768-file scope reaches this reader, so the honest size of the
defect is **one file**, and it is **not** a coverage gap: the same file is
refused for `string_composition_refusal` whatever this reader says, because
`re.escape(old)` is a run-time field and a string on this path is a bare
`char *` with no buffer to compose one in
(`bugs/FORMAL_string_composition_has_no_buffer.md`, a **live** claim). **Fixing
this reader does not make the file build and does not move any row's count.**

What it is worth is that the diagnostic stops being false. A message that says
"the character after the prefix is not a quote" about `rf"…"` sends a reader to
look for a typo that is not there, and it is the message a reader sees FIRST
about a construct the sweep has already decided to refuse — so it is the sentence
that shapes what they think this backend's f-string support is.

**It is also a latent wrong answer rather than only a bad message.** The reader's
job is to hand a lowering the literal's own text, and a reader that guesses a
prefix boundary would take a `fr` string's `f` for the quote and read the rest of
the token as a body. That is why it refuses rather than guesses, which is the
right decision; the bug is the narrowness, not the caution.

## 4. The fix, and the one question that has to be answered first

**Use the prefix boundary the lexer already computes** rather than `spelled[1]`
and `spelled[1 + len(term):…]`. `fire_compiler.py` has `_prefix_is_interpolated`
and `_string_prefix_start`; neither is importable from `formal/` today (the
dependency runs the other way), so the honest shape is a **predicate on the token**
published by `formal/model.py` itself and asked by both:

```python
def interpolated_literal_delimiters(spelled) -> tuple[str, int]:
    """`(quote, body_start)` — where the literal's text begins, for ANY prefix.

    THE prefix is a SET OF SPELLING FLAGS, not one character: `f`, `t`, `r`,
    `b` and `u` in any order and any number of them, so `rf"…"`, `fr"…"` and
    `Rb"…"` are all one quote at an index the caller cannot guess.
    """
```

**The one thing to decide before writing it: does `rawness` change the
SEGMENTATION?** It must not, and the reason is worth stating in the code because
it is the whole reason this fix is safe: a raw string changes what `\\s` MEANS,
not where the literal's chunks and `{…}` fields are. The brace rules (`{{`,
`}}`, brace depth, a nested literal inside a field) are prefix-independent in
both spellings, so a shared segmenter is correct for both and `raw` does not need
to be plumbed into the segments at all. **It does need to be recorded**, because
a caller that later wants the chunk's VALUE rather than its spelling needs to know
it is looking at `\\s` or at `s`.

**The oracle is already in the tree.** `test_formal_run.py`'s
`check_interpolated_segments_against_cpython` compares this reader against
CPython's own `ast.parse` of the very token, by segmentation and by each piece's
meaning — so adding rows is a comparison rather than a pinned expectation, and the
rows to add are exactly the shapes the bug is about: `rf"a={n}b"`, `fr"…"`,
`Rb"…\{{"`, and a **control that must keep refusing** (`f"a{b`, and a token with
no quote at all) so that widening the prefix reader does not turn "unterminated is
a refusal" into something read as a body.

## 5. What the sweep says about it, for the next reader

`tools/wave2_extract_shared.py` is the ONLY file in the 768-file scope with this
terminal refusal, and it is in the sweep's `other refusal` bucket — which
`tools/formal_sweep_causes.py`'s module docstring defines as *"the bucket that
means NOBODY HAS CLASSIFIED THIS"*. It is named here so that the next round's
`--min 1` table can tell a reader that this one was looked at.