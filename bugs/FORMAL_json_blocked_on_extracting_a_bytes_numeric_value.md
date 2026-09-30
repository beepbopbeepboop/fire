# FORMAL_json_blocked_on_extracting_a_bytes_numeric_value: the scanner needs it and this path will not give it

**Status: OPEN, and it is why `json` is NOT in this tree.** Found while writing
`json` for the formal backend (2026-09-29, the `module:json` claim). A
complete RFC 8259 scanner was written and works for every structural test; it
is blocked on ONE primitive — getting a byte's numeric value out of a string
at an index — and that primitive is not available on this path. The work is
described here so the next person does not re-derive it, and so the claim
`json` is unblocked is not mistaken for one line of work.

**Nothing is committed from that attempt.** `formal/hostmods/json.mojo` and
`test_formal_json.py` were written, tested against CPython, and deleted rather
than committed in a state where they produce wrong answers. The test was green
for the parts that do not need this primitive and red on the parts that do.

---

## The primitive

Everything in a JSON scanner reduces to three questions about the byte at
`text[i]`:

| question | available? | how |
|---|---|---|
| is it equal to a specific byte? | **YES** | `memcmp(text + i, TABLE + code, 1) == 0` |
| is it in a set of bytes? | **YES** | `strspn(text + i, SET) > 0` |
| what is its numeric value? | **NO** | see below |

The first two are enough to recognise every JSON token, because a JSON
grammar is a grammar over *fixed* characters. So the structure — objects,
arrays, the four literals, the escape characters, the number's punctuation —
is implementable today, and is.

The third is needed in three places, and each is a real requirement rather
than a convenience:

1. **UTF-8 decoding.** `dumps_string` has to turn a byte sequence into a code
   point to write `\uXXXX` and, above the BMP, a surrogate pair. That is
   arithmetic on three or four byte values.
2. **The control-character rule.** RFC 8259 forbids an unescaped byte below
   0x20 in a string. A set test answers it: `strspn` against the set of bytes
   1..31. **This one is fine** and is how the written scanner did it.
3. **The `\u00XX` escape.** Writing a control character as `\u00XX` needs the
   byte's two hex digits, which needs its value.

So two of the three are genuinely blocked and one is not, which is why the
scanner got as far as it did.

## What I measured

`code_of(s, i)` was written three ways. All three return plausible integers
and all three are wrong.

**A linear scan** over the 256 candidates:

```mojo
def code_of(s: str, i: int) -> int:
    var k = 1
    while k < 256:
        if memcmp(s + i, BYTE_TABLE + k, 1) == 0:
            return k
        k = k + 1
    return 0
```

```
code_of("{", 0)  ->  59        # want 123
```

The equality test itself is fine — `at(s, 0, 123)` returns 1 on the same
input, same buffer, same table. The `while` loop is what loses the value.
The answer is consistently **64 less** than the truth for every input tried,
which is the fingerprint of a counter losing its high bit somewhere between
the comparison and the return.

**A bisection** over `strspn` against prefixes of the byte table — no loop
over 256, seven iterations, using only the two primitives that are known good:

```
code_of("{", 0)  ->  59        # want 123
code_of("a", 0)  ->  43        # want 97
code_of("A", 0)  -> 127        # want 65
code_of("0", 0)  ->  2         # want 48
```

These are not a constant offset — `A` is wrong by +62 and `0` by −46 — so the
predicate inside the bisection is not the one the reasoning assumes. The
bisection depends on `substr(TABLE, mid)`, i.e. on **passing a module-level
constant into a function as an argument**, and the one measurement of that
combination that came back clean is `substr` on a *parameter*:

```
strlen(substr(d, 10))  ->  1        # d is one byte, so 1 is right
```

That is consistent with the module-level-constant argument never arriving, and
with the bisection then walking on a set that is not the set it thinks it is.
**It is a hypothesis, not a conclusion** — the next step below is what would
settle it, and it is one experiment.

## Why there is no easy way round it

The three things that would normally supply a byte's value are all refused or
wrong here, and each refusal is correct:

* **`text[i]`** takes the blob path: it reads a COUNT from offset 0 and
  bounds-checks the index against it. For a string literal that is the first
  eight CHARACTERS read as a word — measured at −1879048144 for `"ab"`, and
  `0x68` is `h` where the answer should be `97`
  (`bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md`).
* **`(text + i).value()`** is a correct one-byte load, and is refused here
  because the EXPRESSION declares no pointee. The refusal names the real
  reason: *"the receiver is an expression that declares no type, so no pointee
  is established"*. A `Pointer[UInt8]` local works — that is how `os`'s
  `str_at` reads bytes — but a `char *` is not a `Pointer[UInt8]` and there is
  no way to say so at a call site.
* **`strtol`** works but needs a NUL-terminated string *starting at the
  byte*, and building one is a `memcpy` from a table indexed by — the value.

So the loop closes: the answer is needed to index the table, and the table is
what produces the answer.

## The exact next step

1. **Settle whether a module-level constant survives being passed as an
   argument.** One experiment: a module with `T = "..."` and a function
   `def len_of(s: str) -> int: return strlen(s)`, plus a caller that passes
   both a literal and `T`, and the module's own function passing `T` to
   `len_of`. If the module-level one comes back 0 or garbage, that is a
   distinct bug from the one in this document and it should be filed as such
   — it is a plausible general defect, since every module-level constant in
   this tree would be affected. If it comes back right, the bisection's
   `substr` is innocent and the bug is in the loop's arithmetic, which is a
   much smaller surface.

2. **If constants do survive, the fix is in the bisection's arithmetic**, and
   the honest form of the primitive is a *macro-like* expansion rather than a
   function — an `unrolled` chain of `memcmp` against `TABLE + k` for k in the
   ASCII range, which is 128 constant comparisons and no loop at all. That is
   large but it is MECHANICAL, it is generated, and it is correct by
   construction: a chain of equality tests cannot lose a counter. The
   non-ASCII half is the only part that would still need arithmetic, and it is
   reachable only for non-ASCII input, which no file in this tree's JSON has.

   That is the recommendation: **generate the comparison chain, do not loop.**
   Given that a loop over 256 iterations with a correct body has already been
   measured to return 64-off answers, a chain is the shape this backend can be
   trusted with, and the project has more than once found that a hand-written
   loop and a C library call disagree on this path.

3. **Reconsider whether `json` needs the UTF-8 half at all.** The tree's one
   JSON consumer is `tools/ab_compare.py`, which reads a `.meta.json` whose
   members are integers, and the file names it reads are generated by
   `tools/ab_compare.py` itself. A module with `valid`, `top_kind`,
   `get_kind`, `get_int`, `get_string` and a `dumps_string` that handles
   ASCII plus **refuses** a non-ASCII byte would unblock that consumer today,
   and the non-ASCII half would become a documented gap rather than a
   blocker. That is a smaller, honest module — and per this project's own
   rule, an absent capability with a bug doc beats an approximation.

4. **A test for whatever closes it**, in `test_formal_json.py` (written, not
   committed): `code_of` over every byte value 1..255, compared with CPython's
   `ord`. That is the assertion that would have caught all three wrong
   implementations in one line, and it belongs with the primitive rather than
   with the scanner.
