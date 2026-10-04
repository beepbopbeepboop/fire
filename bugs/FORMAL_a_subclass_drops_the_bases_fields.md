# A subclass DROPS its base's fields and methods, on both architectures

**Status: NOT FIXED, and NOT MINE.** This is the bug `tools/control.py` records
as another worker's claim (`bug:FORMAL_a_subclass_drops_the_bases_fields`, held
by `formal16-2`), so this doc is the MEASUREMENT and not a claim on the fix —
`formal/fire_compiler.py`'s parser and the class-lowering path are that claim's
area and editing them from here would be two workers in one file. The fuzz-5
session found it by probing an inherited class before writing the `objs` mix, as
`bugs/FORMAL_fuzz_ledger.md` §5's rule requires of every new family.

## What was run, what was seen, what was expected

`python3 .tmp/probe.py` — the probe harness built on `tools/formal_fuzz.py`'s
own `build`/`run`/`cpython_answer`, on both backends:

    def main() -> Int32:
        b = B()
        v = b.sum()
        print(v)
        return 0

    class A:
        def __init__(self):
            self.x = 10
        def get(self):
            return self.x

    class B(A):
        def sum(self):
            return (self.get() + 1) & 0xFFFF

| | answer | exit |
|---|---|---|
| CPython | `11` | 0 |
| arm64 | **`1`** | 0 |
| x86-64 | **`1`** | 0 |

Both backends agree with each other and disagree with CPython, so this is a
SEMANTICS GAP IN BOTH rather than an x86-64 bug — which is why it is filed as a
doc and not fixed here. `1` is `0 + 1`, i.e. `self.get()` returned 0 where the
base's field `x` holds 10: the subclass's receiver has no `x`, so the inherited
method read whatever the slot held.

## The exact next step for whoever holds the claim

Three questions, in the order they have to be answered, and all three are in
`formal/model.py`'s class-shape questions rather than in either emitter:

1. **Does `class B(A)` record the base at all?** `fire_compiler.py` parses the
   bases (it has to, to reject nonsense), so the question is whether anything
   downstream reads them. `grep -n 'bases' formal/model.py` and
   `formal/arm64_codegen.py` is where to start.
2. **What is a subclass's layout?** `model.struct_fits_one_word` and
   `formal/build.py`'s `_derived_overrides` are the two places that already
   answer a question of this shape for a DERIVED class; a base's fields have to
   be laid out at the subclass's own offsets, or `self.get()`'s `base + 8k` reads
   a slot the subclass never wrote.
3. **Is `__init__` inherited?** The reproducer does not need it — `B()` calls
   `A.__init__` in CPython — so the minimal case to add beside it is a subclass
   with NO `__init__` of its own, which separates "the bases are not recorded"
   from "the constructor is not inherited".

## Why the corpus cannot see this yet

`tools/formal_fuzz.py`'s `classes` mix has no inheritance family, and adding one
before the semantics is settled would make every generated program a
`MISMATCH-*` finding — which is a real cost, not a technicality: 100 programs of
noise per sweep drowns the one finding that matters. The probe above is the
honest form for now, and §5's "what would be the next thing to generate" carries
it as a family to add WITH the fix.
