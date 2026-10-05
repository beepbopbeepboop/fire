# FORMAL: a name in `NOT_LOWERED_BUILTINS` is refused by the LINK AUDIT after the image is built, and the table that says why is never read by the build

**Area:** FORMAL (the higher-order builtins \u2014 `sorted`, `map`, `filter`, `sum`,
`all`, `any`, `min`, `max`, `reversed` \u2014 on both backends).

**Found while measuring closures/lambda/higher-order functions** against CPython
(`test_formal_closures.py`), by a round whose claim is `project33:closures-lambdas`
and which fixed the lambda-in-argument lowering beside it. Not fixed here: the
fix belongs in the shared pre-pass and this round did not have budget to prove it
against the 664-file stdlib, which is the thing that would go wrong.

## What was run

    $ cat sum.mojo
    def main():
        print(sum([1, 2, 3]))
        return 0
    $ python3 sum.mojo
    6
    $ python3 fire.py build --formal --no-prove -o sum sum.mojo
    build: sum.mojo: the image would bind 1 symbol(s) that nothing provides, so
    it could not be loaded: sum. `sum` is a call this build emitted and nothing
    provides it, so that call is not lowered on this path: this backend has no
    call to bind there, which is a fact about the PROGRAM and not about the link
    line. Write the operation out, or bind the name from a library that provides
    it. Every name in this list is one of the calls named above, so nothing about
    the link line is left to explain. (Provider check: asked the C library
    (dlsym).)

Same for `sorted([3, 1, 2])`, `map(dbl, [1, 2, 3])`, `filter(lambda v: v > 1, …)`,
`sum(…)`. Identical on arm64 and x86-64 (the message is arch-free here).

## What was expected

`formal/model.py::NOT_LOWERED_BUILTINS` already carries the reason for every one
of these, spelled per name and written for this purpose:

> `"sorted": "a sort \u2014 a comparison call per element, and a call through a value
> is not a thing this path can express"`

and its own header calls the table "a safety property rather than a census",
because a name absent from it is a name whose absence was SILENT. The table has
exactly one consumer, `tools/formal_proof_breadth.py` (which reads it to label a
sweep ledger row, and reaches the same `ast.Call` positions this would). **The
build never reads it.**

So the sequence for `sum([1, 2, 3])` is: the emitter treats `sum` as an ordinary
extern call and emits a `BL sum`, the linker notices nothing provides it, and the
LINK AUDIT refuses \u2014 after the image is built, from a message about SYMBOLS,
whose advice ("bind the name from a library that provides it") is about the link
line rather than about the fact that no library on any line provides a Python
builtin's semantics.

## Why it is worth fixing rather than documenting

Three reasons, in the order they cost a reader:

1. **The refusal arrives a stage too late.** Everything downstream of emission
   has already run by then \u2014 the whole closure was allocated, every other
   function emitted. A pre-pass refusal is free; this one has already paid.
2. **The message is about a symbol, not about the construct.** CLAUDE.md's rule
   for this area is that a refusal must name the construct, and
   `test_formal_closures.py`'s `sorted_*`/`map_*`/`filter_*`/`sum_*` rows have to
   assert a needle in a link-audit sentence for that reason alone. The sentence
   that would answer is already written and unused.
3. **`map` and `filter` are not even IN the table.** `sorted`, `sum`, `all`,
   `any`, `max`, `min`, `reversed`, `list`, `tuple`, `enumerate` are; the two names
   whose argument IS the callable \u2014 the whole point of the higher-order group \u2014
   are not, so nothing in the tree can say what lowering them would take. Adding
   them is a two-line change with a real measurement behind it: both need to CALL
   a value per element, which is the same wall as `sorted`'s comparison call.

## The next step

One pre-pass beside `formal/build.py`'s other shared refusals (`_formal_module_functions`
already hosts `generator_function_refusal`, `nonlocal_write_refusal` and
`unapplied_decorator_refusal` for the same reason \u2014 one decision, asked before
any emitter, so the executable and dylib paths cannot answer differently):

    for each CallExpr whose func is a bare IdentExpr:
        if name in NOT_LOWERED_BUILTINS: raise

with `NOT_LOWERED_BUILTINS`' own reasons quoted verbatim in the message (that is
what `tools/formal_proof_breadth.py::builtin_refusal_detail` already does for a
ledger row, so the two must not word it differently).

Two things to check before landing it, and they are why this round did not:

- **The sweep's own accounting.** `tools/formal_proof_breadth.py` classifies a
  verdict as `refused-builtin` by looking for `UNLOWERED_CALLEE_MARKS` in the
  message AND re-deriving the names from the source. A new message changes the
  text that classifier matches, so the ledger's labels can move even though the
  verdicts do not. Re-read `UNLOWERED_CALLEE_MARKS` and `verdict_for` before
  changing a word.
- **`test_refusal_taxonomy.py`'s families.** It is at 269 checks / 45 families /
  66 causes and counts refusal messages by shape; a new family for the
  higher-order builtins is a legitimate addition and its count is asserted, so it
  has to land in the same commit.

## Test coverage

`test_formal_closures.py`'s `sorted_with_a_key_lambda`, `sorted_without_a_key`,
`map_over_a_literal_with_a_lambda`, `map_over_a_literal_with_a_function`,
`filter_over_a_literal` and `sum_over_a_literal` rows. All six PASS today \u2014 as
refusals naming the builtin \u2014 because the link audit happens to quote it. The
comment above each says so and names what a by-name refusal would change, so the
gap is recorded where the rows are.