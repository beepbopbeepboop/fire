# An f-string literal is refused with "this path has no buffer to compose one in", and it is now the FIRST refusal in `formal/x86_64_decode.py`

**Area:** `formal/model.py::interpolated_literal_refusal` (asked over the module
by `refuse_interpolated_literals`), both backends. **Status: OPEN, filed by
`work/formal23-1`; NOT fixed here (the fix is a value-model decision and the file
that exposes it belongs to another doc's reproduction).**

Found 2026-10-04 while re-measuring
`bugs/FORMAL_a_keyword_construction_with_a_star_star_spread.md`'s witness, whose
file used to be refused at the `**kw` spread and is now refused here instead.

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