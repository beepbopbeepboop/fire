# FORMAL_a_keyword_construction_with_a_star_star_spread: `S(a=1, **kw)` is refused because the spread MIGHT duplicate a keyword

**Status: PARTIAL — the false half is fixed and the real blocker is now
measured, twice. Re-measured 2026-10-04 (`work/formal23-1`): over this
repository, `formal/hostmods/` and 252 stdlib files the corpus holds THREE `**`
spreads and not one of them is a dict literal or a local bound to one — so the
key-set half of "The exact next step" below has NO witness in the corpus, and
every one of the three is a `**`-PARAMETER, which `FORMAL_a_variadic_parameter_
read_has_no_abi.md` owns. The doc's own witness file, `formal/x86_64_decode.py`,
is no longer refused here at all: it is now refused EARLIER, at an f-string
literal on line 133 (`bugs/FORMAL_an_f_string_literal_is_refused_and_is_the_first_
refusal_in_x86_64_decode.md`), and it holds 13 f-strings of which five are
`insn()` call sites — so "the source stops spreading" is no longer a one-file
mechanical change but a chain, and the variadic ABI is the only blocker left.**
Found 2026-10-03 while clearing the single-file causes in
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3.2. **The refusal itself is still
CORRECT** — what changed is that the sentence it used to produce was false about
the source, that a spread of a dict LITERAL is now answered rather than refused,
and that the gap that remains is NOT the one this doc's §"The exact next step"
thought. See "What landed" at the end, which is the part to read first.

## 0b. §"The exact next step" re-measured: the key-set half has no witness (2026-10-04)

**What was run.** A parse-and-walk over the same scope §1 used, counting every
`**` spread and asking, of each, whether its operand is a dict literal, a local
whose every binding in the function is such a literal, or neither. It reuses
`tools/formal_template_call_census.py`'s scope walk and `formal/model.py`'s
`iter_nodes_with_parent`, so it is the same corpus the other censuses count.

| `**` spreads in 379 files | sites |
|---|---:|
| of a dict LITERAL (already answered, "What landed" item 2) | **0** |
| of a local only ever bound a dict literal (item 2 of "The exact next step") | **0** |
| of anything else | **3** |

and the three, verbatim: `std/python/bindings.mojo:1681`, `:1722` and
`std/python/python_object.mojo:1296`, each a `**`-parameter spread in a CPython
bindings shim.

**What that changes.** Option 2 of "The exact next step" — "track a spread's key
set when it is a literal, directly or through a local that is only ever bound
such a literal" — has **no call site in the corpus to answer**. It is not
wrong; it is unmeasured, and this repository's rule about unmeasured work
(`bugs/` is a queue, and a row nobody has looked at is the bucket
`tools/formal_sweep_causes.py` exists to empty) is that it should not be the next
thing built. What §"What landed" item 4 already concluded is therefore now the
ONLY remaining step rather than one of two: **the variadic ABI**, so a `**kwargs`
parameter becomes something a callee can read, which is
`bugs/FORMAL_a_variadic_parameter_read_has_no_abi.md` and is claimed.

**And the doc's own witness has moved, which is the other half.** §"Why it is in
no list" says this refusal "will appear in the next sweep of that file, at one
file" — and `formal/x86_64_decode.py` is now refused at an earlier construct, so
it will not:

```console
$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=$A \
      -o .tmp/xd.bin formal/x86_64_decode.py; done
build: an f-string literal on line 133 is refused on this path: its value is its
INTERPOLATED text, and this path has no buffer to compose one in. …
```

That file has **13** f-strings, eight inside `raise DecodeError(...)` and five
inside the `insn()` helper's arguments — and those five are `**kw` FORWARDING
call sites, so rewriting them lands on this doc's blocker next rather than past
it. Option 1 of "The exact next step" ("the source stops spreading, minutes, one
file") is therefore a chain of unrelated value-model refusals before it reaches
the one this doc is about, and its own text already says why it is not the fix to
lead with ("it makes the source worse to read").

## What landed (2026-10-03, `formal/model.py`)

**1. The spread was a POSITIONAL, and that is why the message named a duplicate
the source does not contain.** `fire_compiler.py`'s `_parse_paren_args` keeps the
`**` marker alive by appending `UnaryOp('**', mapping)` to `args` — right for an
interpreter, which splices at call time, and wrong for the two readers that zip
`args` against a parameter/field LIST:

    S(a=1, **{'b': 2})   ->  constructing S with 'a' gives field 'a' more than one value

`a` was never given twice; the whole mapping was bound to `a` as the first
positional, and the keyword `a=1` then collided with it. Measured on both
architectures, and with one keyword fewer it was not a refusal at all: the
mapping's own word would have been stored in `a`'s slot.

**2. A spread of a dict LITERAL is now un-spread, with its VALUES**, in
`_unspread_keyword_mappings`, called from the two readers — `struct_construction_plan`
for a construction and `bind_call_arguments` for a call. Both keys and values are
written in the source and a dict subscript by a literal key already lowers
(`d['a']` is 1), so `S(a=1, **{'b': 2})` builds and prints `1 2`, and
`f(a=1, **{'b': 2})` prints 12 — both agreeing with CPython on both architectures.
The duplicate check then applies UNCHANGED, which is what keeps
`S(a=1, **{'a': 2})` refused with CPython's own `TypeError` rather than with
something this path invented.

**3. Any other spread is refused BY NAME**, naming the operand and saying the
keys are not knowable at the construction site — which for
`formal/x86_64_decode.py` reads `constructing Insn spreads `kw` with `**`` where
it used to read `gives field 'offset' more than one value`.

**4. The blocker for the remaining case is not the key set, and this is the
measurement that reorders §"The exact next step".** That section's option 2 is
"track a spread's key set when it is a literal … through a local that is only ever
bound such a literal … keeping the set through a `**`-parameter". The premise is
that a `**`-parameter is something whose keys could be carried — and on this path
it is not: a formal value is one 64-bit word and the target has no variadic ABI,
so a callee cannot read its own `**kwargs` AT ALL. Measured, both architectures,
on this doc's own reproduction: the refusal that fires first is

    build: mk: the body reads 'kw', its **-parameter, and this path has no
    variadic ABI. A formal value is one 64-bit word, so the arguments a caller
    passes past the fixed ones (this module's call sites pass …) have nowhere
    to go

So the exact next step is the variadic ABI, not the key set: **a `**kwargs`
parameter has to become a dict blob the callee can read by literal key**, and only
then is there a value to take a key set from. That is one feature with two
consequences (the callee can read it; the caller's spread can be answered from
it), and it is the same question `“`struct` keyword arguments are silently dropped”`
asks on the gimple side — the two should share an answer, as this doc already said.

Until then the two ways out of the original §"The exact next step" are unchanged:
write the keywords out (which is what makes `formal/x86_64_decode.py` build), or
build the variadic ABI.

Rows: `test_formal_run.py`'s `SPREAD_CONSTRUCTION_CASES` (2, CPython-differential,
both architectures) and `SPREAD_REFUSALS` (4, both architectures).

## What was run

`formal/x86_64_decode.py`, one of the repository's own files, through the formal
backend, after the two declarations ahead of it in its walk were fixed
(`formal/x86_64_decode.py: `Insn.extra`'s `field(default_factory=dict)` and
`DecodeError(msg)`'s missing slot — see that commit):

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- \
  python3 fire.py build --formal --no-prove --backend=arm64 \
  -o .tmp/xd.bin formal/x86_64_decode.py
```

## What was seen

Identical on **both** architectures (`--backend=x86_64` gives the same sentence):

```
build: constructing Insn with 'offset' gives field 'offset' more than one value:
a keyword names its field, the positionals take the remaining fields in
DECLARATION ORDER, and the two together must cover each field exactly once.
This is the same `TypeError` CPython raises — got multiple values for argument
offset
```

Minimal reproduction, measured on both architectures:

```
struct Insn:
    var offset: Int
    var length: Int
    var form: Int

def mk(off: Int, ln: Int, fm: Int, **kw) -> Insn:
    return Insn(offset=off, length=ln, form=fm, **kw)

def main(n: Int) -> Int:
    var i = mk(1, 2, 3)
    printf("%d\n", i.offset * 100 + i.length * 10 + i.form)
    return 0
```

CPython prints `123`.

## What was expected

`mk(1, 2, 3)` binds no keyword at all, so `kw` is empty and the construction is
`Insn(offset=1, length=2, form=3)` — three fields, three values, no duplicate.
The program is ordinary Python and it is what a decoder helper looks like.

## Why the refusal is right

**A `**kw` spread's keys are not knowable at the construction site, and the
duplicate is a runtime `TypeError`.** `construction_keyword_refusal`'s `"twice"`
arm assumes it can enumerate the keywords; with a spread it cannot, so the only
sound answer is that the construction is undecidable and is refused. Answering
it the other way — "the explicit keywords win and the spread fills the rest" —
would silently accept `S(a=1, **{"a": 2})`, which is the program the refusal
exists to catch. So this is the same reasoning as `formal/model.py`'s
`construction_copy_unrecognised_refusal`: **an absent answer is the answer**, and
a doubtful case has to fall out of the typed set rather than into it.

What makes it a gap rather than a limitation is that the spread's keys are often
*statically known* at the place they are written, and this corpus writes them
that way: `formal/x86_64_decode.py`'s local `insn()` helper takes `**kw` and
forwards it, and every one of its ~20 call sites passes a **literal** set of
keyword names (`insn(length, form, mod=mod, reg=reg, rm=rm, mem_base=base,
mem_disp=disp)`). The keys are in the source; nothing tracks them.

## The exact next step

Two ways out, and they are different jobs:

1. **The source stops spreading** (minutes, one file). `decode_one`'s `insn()`
   helper could take the fields it does not set by name at each of its call
   sites, or build an `Insn` per form. This is what `formal/x86_64_decode.py`
   needs to build, and it is a mechanical change to one local helper — but it
   makes the source worse to read, which is why it is not the fix to lead with.
2. **The compiler tracks a spread's key set when it is a literal** (the real
   fix). A `**` whose operand is a dict literal with literal keys — directly, or
   through a local that is only ever bound such a literal — has a key set that
   `construction_keyword_refusal`'s `"twice"` arm can be handed, which turns
   this refusal into the ordinary duplicate check and leaves the undecidable
   case refused. `formal/build.py` already has a literal-dict key reader for
   `formal/hostmods` work; the missing piece is keeping the set through a
   `**`-parameter, which is the same flow question
   `“`struct` keyword arguments are silently dropped”` asks on the gimple
   side and should share an answer with.

## Why it is in no list

`tools/formal_sweep_causes.py` ranks causes by how many files a refusal blocks,
and this one was invisible to it: on this tree `formal/x86_64_decode.py` was
refused earlier for the two declarations above, so the sweep never reached this
sentence. It will appear in the next sweep of that file, at one file, and the
cause table will need a row for it — with the marker `"more than one value"`,
which is also how `construction_keyword_refusal`'s `"twice"` arm is worded, so
the two must be told apart in the table (this one says `more than one value` and
that arm says `more than one value` too — **a collision to resolve when the row
is added**, most likely by keying this row on the `**` spread rather than on the
sentence).
