# An f-string literal is refused with "this path has no buffer to compose one in", and it is now the FIRST refusal in `formal/x86_64_decode.py`

**Area:** `formal/model.py::interpolated_literal_refusal` (asked over the module
by `refuse_interpolated_literals`), both backends. **Status: OPEN — the refusal
itself is still the right answer and still stands. Filed by `work/formal23-1`
2026-10-04; NOT fixed here (the fix is a value-model decision and the file that
exposes it belongs to another doc's reproduction). PARTIAL WORK 2026-10-05 on
`work/formal27-2`, in "What landed" at the end: the refusal's ADVICE was false
and is now true and pinned by a test, and the ceiling for this file was measured
(it is `**kw`, not composition).**

Found 2026-10-04 while re-measuring
`bugs/FORMAL_a_keyword_construction_with_a_star_star_spread.md`'s witness, whose
file used to be refused at the `**kw` spread and is now refused here instead.

## What landed 2026-10-05 (`work/formal27-2`), and what is still missing

**The advice the refusal gives was wrong, and following it produces a
wrong-but-exit-0 program — which is the one thing a refusal must never do.** It
said *"Print the parts as separate operands, or build the text with `+` once that
is lowered"*, and:

* `print("n=", n)` is **not** the f-string's text. `print` inserts a space
  between its operands, so it prints `n= 7` where `print(f"n={n}")` prints
  `n=7`. A reader who took the advice got a different answer from CPython and
  exit status 0. `test_formal_run.py`'s
  `fstring_print_of_two_operands_is_not_the_rewrite` is that measurement, run on
  both architectures, and it prints `n= 7` — which is also what CPython prints,
  so the two languages agree here and NEITHER is the f-string's text;
* `+` on two strings is refused by `string_concat_refusal` for the same missing
  buffer, so naming it as a way round is naming the wall.

The sentence now says what is true: **pass the value to `printf` as an
argument** — `printf("n=%d", n)` — which is the same text and is what this path
lowers, and `fstring_the_advice_works_printf_takes_the_value_as_an_argument` is
that advice spelled as the program it names, required to print CPython's `n=7`
on both machines. A refusal that recommends a rewrite is only a diagnosis until
the rewrite is known to work; that is now a case rather than a claim.

The two instruments that key on this message needed no change, which is worth
recording because it is the reason they were built the way they were: their
markers are on `no buffer to compose into`, not on the advice, so replacing the
advice could not move a single file between causes. `test_refusal_taxonomy.py`'s
sample for this message is produced by CALLING `interpolated_literal_refusal`,
so it reworded with the sentence above.

**The ceiling for the file this doc names was measured, and it is NOT
composition.** `formal/x86_64_decode.py` has 13 f-strings (not the 10 this doc
recorded — the file has grown). With all 13 rewritten as plain literals with the
holes deleted (a scratch copy in `.tmp/`, semantically wrong on purpose, the
question being what stands BEHIND the row):

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal       --no-prove --backend=arm64 -o .tmp/x.bin .tmp/f6/x86_64_decode_nofstring.py
build: constructing Insn spreads `kw` with `**`, and a spread's KEYS are not
knowable at the construction site: …
```

**So editing that file's 13 f-strings buys nothing**: it lands on the `**kw`
spread, which is `bugs/FORMAL_a_keyword_construction_with_a_star_star_spread.md`
(`formal27-1`), and it would have cost 13 diagnostics their detail to get there.
That is why no call site was rewritten, and it is the same measurement the
2026-10-04 sweep map made for its own 115-file row (`§5.3`): the row is a
priority to KNOW ABOUT, not the first one to implement.

**What is still missing is unchanged and is a project, not a patch**: there is
no buffer. `formal/model.py`'s own reasoning in the message is the statement of
it (a string here is a bare `char *` interned into read+execute `__TEXT`, so
`"n=" + decimal(n)` has nowhere to be laid down at compile time because the field
may be a run-time value, or at run time because there is no heap), and
`bugs/FORMAL_string_composition_has_no_buffer.md` is where the project is
tracked (`formal27-6`). Nothing in this doc's area is a patch away from it, and
the cheap half — the caller's spelling — is the two sentences above.

## What was run, and what it showed

```console
$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=$A \
      -o .tmp/xd.$A.bin formal/x86_64_decode.py; done
build: an f-string literal on line 133 is refused on this path: its value is its
INTERPOLATED text, and this path has no buffer to compose one in. The parser keeps
the whole source token (`f"SIB with index {index} is not emitted"`) as the
literal's value, so …
```

Identical on both architectures, and it is the FIRST refusal the build walk
reaches in that file — the two declarations ahead of it in an earlier round
(`Insn.extra`'s `field(default_factory=dict)` and `DecodeError(msg)`'s missing
slot) are fixed, so the f-string moved to the front.

**Why it matters beyond that file: the refusal's own reasoning is a value-model
statement, and nothing in `bugs/` holds it.** `formal/model.py` says a string
here is "a bare `char *` interned into read+execute `__TEXT`", so there is
nowhere to lay down `"SIB with index " + decimal(index)`: not at compile time
(the field is a run-time value) and not at run time (there is no heap). That is
the same missing buffer `string_concat_refusal` and `LENGTH_DEPENDENT_METHODS`
name, and it is a project rather than a patch — which is why this is a doc and
not a change.

## What it would take, and the cheap half of it

* **The cheap half is the caller's spelling, and the refusal already names it:**
  `print(f"v={v}")` becomes `print("v=", v)` (the parts as separate operands) or
  `printf("v=%d", v)`. That is a per-site edit and it is what
  `bugs/FORMAL_a_keyword_construction_with_a_star_star_spread.md`'s option 1 is
  for its own construct.
* **The real fix is a buffer**, and there are exactly two shapes it can be:
  a run-time scratch area the emitters own (a `__DATA` cell per string
  expression, or a stack slot), or a compile-time composition for the case where
  every hole is a literal. The second is not a smaller version of the first — it
  is the whole of what `s = "n=" + decimal(n)` would need, and
  `string_concat_refusal` refuses that today, so landing composition means
  landing concatenation first.
* **The measurement a taker wants before starting**: how many f-strings the corpus
  has. `formal/x86_64_decode.py` alone has **10** (`grep -c 'f"' …` → 10 on
  this tree), eight of them inside `raise DecodeError(...)` and two inside the
  `insn()` helper's `f"alu_rr:{alu}"` arguments — so this file is not a
  one-edit story even for the cheap half, and it would still hit the `**kw`
  spread afterwards.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/xd.bin formal/x86_64_decode.py
build: an f-string literal on line 133 is refused on this path: …
$ grep -c 'f"' formal/x86_64_decode.py
13
$ python3 -c 'exec("f\"n={7}\"")'   # what CPython answers
n=7
```