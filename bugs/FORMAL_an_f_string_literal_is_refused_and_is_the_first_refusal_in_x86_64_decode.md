# An f-string literal is refused with "this path has no buffer to compose one in", and it is now the FIRST refusal in `formal/x86_64_decode.py`

**Area:** `formal/model.py::interpolated_literal_refusal` (asked over the module
by `refuse_interpolated_literals`), both backends. **Status: OPEN — a literal
with a replacement field is still refused and the buffer it needs is still the
real fix. Filed by `work/formal23-1` 2026-10-04; NOT fixed here (the fix is a
value-model decision and the file that exposes it belongs to another doc's
reproduction). PARTIAL WORK 2026-10-05 on `work/formal27-2`, in "What landed" at
the end: the refusal's ADVICE was false and is now true and pinned by a test, and
the ceiling for this file was measured (it is `**kw`, not composition). PARTIAL
WORK 2026-10-08 on `work/formal167-docs`: the ONE case that needs no buffer — an
f-string with NO replacement field — is now FOLDED to the text it denotes and
BUILT (it was refused before), pinned by five CPython-pair rows in
`test_formal_run.py`; a literal with a field, and therefore every literal this
doc's file holds, is unchanged.**

**Update 2026-10-12 (`work/formal292-docs`): the CONSTANT half of composition
LANDED, and the refusal is now narrowed to the run-time half it is actually
about.** `formal/model.py` has `fold_constant_string_literals`, run by
`formal/build.py::_prepare_functions` BEFORE `refuse_interpolated_literals`, and
it realises the shape this doc's "What it would take" names — *"a compile-time
composition for the case where every hole is a literal"* — together with the
constant `+`/`*` over strings that sentence calls the prerequisite (*"landing
composition means landing concatenation first"*). An f-string every field of
which is a literal, and a `str + str` / `str * int` whose operands are all
literals, now BUILD and answer CPython: each folds to an ordinary interned
literal, which is the same `char *` every other string literal on this path is
and so needs no buffer. A field that is a NAME, a CALL or an operator, a format
spec, a conversion and a t-string still get the sentence above, unchanged — the
field counts and the wording are the same, because the pass answers only what it
can. Measured both architectures: `"ab" + "cd"` prints `abcd` (was a refusal),
`"=" * 3` prints `===`, `f"n={5}"` prints `n=5`, `f"{'a'}b{None}"` prints
`abNone`, `rf"a\n{5}"` keeps the literal backslash, and `f"n={k}"` is still
refused by name. Pinned by `test_formal_run.py`'s four
`fstring_...folds`/`raw_fstring_...` rows and its three
`str_concat...`/`str_repeat...` rows; the old `str_concat_refused` row asserted
the refusal of `"ab" + "cd"`, which is a CONSTANT, so it is now
`str_concat_of_two_variables_refused` (two VARIABLES, the run-time half) beside
the answered `str_concat_of_two_literals_folds`. **What is still missing is
unchanged and is §2's project**: the buffer that answers a run-time value, so
this doc stays open with only the constant half closed.

Found 2026-10-04 while re-measuring
`bugs/FORMAL_a_keyword_construction_with_a_star_star_spread.md`'s witness, whose
file used to be refused at the `**kw` spread and is now refused here instead.

## What landed 2026-10-13 (`work/formal363-docs`): a field-less f-string is not a composition, and is no longer refused

**The refusal was over-broad by exactly one shape: an interpolated literal with
NO `{…}` field has no composition to do, and its own message said so — "This one
has NO field at all … so its value is a CONSTANT and this refusal is over a
missing buffer rather than a run-time value" — while refusing it anyway.** A
constant string needs no buffer; it is interned into `__TEXT` like any other
literal's bytes. So it is folded instead:

* `formal/model.py::interpolated_literal_constant(node)` reads such a token into
  its one spelling (`interpolated_literal_segments` already unescapes `{{`/`}}`
  and leaves every backslash as written), or answers `None` for a literal that
  HAS a field or that the reader cannot take apart;
* `fold_constant_interpolated_literals(stmts)` rewrites each such node into the
  plain `StringLiteral` it is — `is_raw` carried from the literal's own PREFIX
  through `interpolated_literal_quote_start`, so `rf"\d+"` keeps its backslash
  rather than being decoded into a newline;
* `formal/build.py::_prepare_functions` runs the fold immediately in front of
  `refuse_interpolated_literals`, so that refusal's subject is exactly the
  INTERPOLATING literals it is for. A caller that skipped the fold would refuse
  a correct program, never miscompile one — the fold is the fix and the refusal
  is the backstop;
* `interpolated_literal_refusal`'s "NO field at all" sentence is kept (it is a
  pure function `test_refusal_taxonomy.py` still calls directly), but through
  the pipeline it is now unreachable.

**Measured on both architectures**, `f"hello"`, `f"a{{b}}"`, `rf"\d+"`,
`f"x\ny"` and `t"hello"` all build, run and print CPython's text; pinned by
`test_formal_run.py`'s `an_fstring_with_no_field_is_the_plain_string`,
`a_raw_fstring_with_no_field_keeps_its_backslash` and
`a_tstring_with_no_field_is_the_plain_string`, and the INTERPOLATING refusal
rows beside them are unchanged.

**What this does NOT move, and the doc above stands for it:** every one of
`formal/x86_64_decode.py`'s 13 f-strings INTERPOLATES a run-time field, so all
13 still take the buffer path and this file's first refusal is still the
line-133 f-string, with the `**kw` spread still behind it. The interpolating
case is untouched, and the buffer (§"What it would take") is still the whole of
what this doc is about. This is the field-less half of the same subject, not the
subject.

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

* **The cheap half is the caller's spelling, and the refusal now names the one
  that WORKS:** `print(f"v={v}")` becomes `printf("v=%d", v)`. That is a
  per-site edit and it is what
  `bugs/FORMAL_a_keyword_construction_with_a_star_star_spread.md`'s option 1 is
  for its own construct. **`print("v=", v)` is NOT the rewrite and the landed
  refusal no longer offers it** — `print` inserts a space between operands, so
  it prints `v= 7` where the f-string prints `v=7`, which is a different answer
  with exit status 0; see "What landed" above and
  `test_formal_run.py::fstring_print_of_two_operands_is_not_the_rewrite`.
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

## What landed 2026-10-08 (`work/formal167-docs`): the constant half

**An f-string with no replacement field is a CONSTANT, and the refusal was over
a buffer it does not need.** The refusal's own sentence already said so —
`_interpolated_shape_sentence`'s "This one has NO field at all … so its value is
a CONSTANT and this refusal is over a missing buffer rather than a run-time
value" — and CPython prints `abc` for `print(f"abc")` where this path refused the
program. `formal/model.py::fold_constant_interpolated_literals` now rewrites such
a literal IN PLACE into the ordinary string literal it denotes (`value` becomes
the composed text, `is_interpolated` becomes `False`, `is_raw` carries the `r` of
an `rf"…"`), and `formal/build.py::_prepare_functions` asks it immediately before
`refuse_interpolated_literals`, so the refusal never sees the foldable ones.

**This is the one case, and it is not the buffer.** A `t`-string is NOT folded —
its value is a `Template`, not a `str` — and neither is any literal with a field:
those still reach the refusal, and the buffer is still what would lift them. The
fold moves **0 files** in the corpus, which the interpolated-literal census
already measures and says in its own row: **0 files have EVERY interpolated
literal interpolating nothing** (375 literals do, and each sits in a file that
also holds one with a field). So this is a correctness fix for a program the
corpus does not write yet, not a coverage win — and it is exactly the case the
census's hard `== 0` row exists to notice becoming worth something.

Pinned by `test_formal_run.py`'s five CPython pairs:
`interpolated_with_no_field_folds_to_its_text`, `…_can_be_empty`,
`…_unescapes_braces`, `…_decodes_escapes` and
`raw_interpolated_with_no_field_stays_raw` — each built on BOTH architectures and
required to print CPython's own answer, so the escape and `is_raw` halves are
measured against the language rather than stated.
