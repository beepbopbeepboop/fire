# `algorithm/backend/tile.mojo`: a specialization call through a FUNCTION-VALUE field, and 4 stdlib files behind it

**Area:** FORMAL (comptime specialization on a callee this unit does not
compile). Found 2026-10-01 on `work/formal-re-frusal` while working the
`other refusal` row.

**Status 2026-10-03 (`work/formal18-tile-specialization`): THE CONSTRUCT IS
LOWERED, and this file is now a record of what stands BEHIND it.** The
specialization through a function value builds, runs and answers CPython on
both architectures, single-module and across a dylib boundary; the next wall
for `tile.mojo` is its `*tile_size_list` variadic parameter, which is a
different construct with its own reason. The measurement at the end of this
document — "the dependency order for this row is four deep" — was RIGHT, and
the first of the four is now behind us: what the file's own "next step"
described as a declaration question turned out to be a representation
question, and the representation turned out to be one 64-bit word holding a
code address. Everything below the new section is history and is kept
because each step of it is a measurement somebody would otherwise repeat.

## What was run

    $ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
        --backend=$a -o .tmp/tl ../new-modular/Mojo/stdlib/std/algorithm/backend/tile.mojo; done
    build: workgroup_function[…](…) calls a name this unit does not compile,
    so the brackets cannot be bound. A comptime specialization's brackets are
    the generic's comptime parameters, and on this path those are ordinary
    leading arguments the call site evaluates and passes first — a decision
    about a signature, which needs a declaration and there is none in hand. If
    `workgroup_function` is a generic of another module then its instantiation
    is the boundary symbol, one per set of type arguments (doc/ABI.md
    §Generics), and this path does not monomorphize, so there is no callee here
    to pass them to; if it is an ordinary value then the brackets are a
    subscript, which is not a call this path can name. Refused rather than
    emitted with the brackets dropped: that builds, runs, and returns a number
    the source never wrote, with nothing on the link line to catch it

Identical on both architectures.

## The shape

`tile.mojo:48` declares the callee as a VALUE:

    workgroup_function: Some[Static1DTileUnitFunc]      # def[width: Int](Int) -> None

and `:83`, `:160`, `:165`, `:218` call it as a specialization:

    workgroup_function[tile_size](current_offset)
    workgroup_function[secondary_cleanup_tile](work_idx, primary_cleanup_tile)
    workgroup_function[tile_size_x, tile_size_y](current_offset_x, current_offset_y)

Two facts make this harder than the `formal/*_mlir` bracket cases: the callee
is not a NAME (it is a parameter holding a function value, so there is no
declaration in hand even in principle — the generic type is written
`Some[Static1DTileUnitFunc]`, in a *field/parameter type*, and this path
resolves parameter types to words); and the brackets carry comptime arguments
that the call site evaluates, so dropping them would silently call the
unparameterised function.

## The 4 files

`tools/formal_sweep_causes.py --min 4 .tmp/sweep-x86-4.txt` counts 4, and 4/4
name something tile declares:

| file | |
|---|---|
| `std/algorithm/backend/tile.mojo` | the refusal itself (`CODEGEN`) |
| `std/algorithm/backend/__init__.mojo` | imports `.tile` |
| `std/algorithm/backend/unswitch.mojo` | imports `.tile` |
| `std/algorithm/__init__.mojo` | imports `.functional` → `.backend` → `.tile` |
| `std/algorithm/functional.mojo` | imports `.backend` → `.tile` |

(the sweep counts 4 dependents plus the file itself; the chain reaches 5
sources in all.)

## Whose

This is GPU code and it sits inside another worker's claim —
`construct:mlir-and-gpu-globals`, whose subject is `std/gpu/**` and the MLIR
dialect constructs, and `workgroup_function` is a GPU launch abstraction. It is
recorded here rather than fixed so that claim is not duplicated and so the 4
files are not counted twice in the `other refusal` row: with `re.mojo` and
`hashlib.mojo` closed by `work/formal-re-refusal`, `tile.mojo` is what is left of
that row's module-caused entries, and it is the smallest of the three.

## Re-verified 2026-10-01 (`work/formal3-7`): the refusal stands, and "Whose"
## above is still the operative section

Measured again rather than assumed, because a refusal that has quietly started
building is the failure this document exists to prevent:

```
$ python3 tools/memslot.py --gb 8 --label tile -- python3 fire.py build \
      --formal --no-prove -o .tmp/esc/tile \
      ../new-modular/Mojo/stdlib/std/algorithm/backend/tile.mojo
build: workgroup_function[…](…) calls a name this unit does not compile, so the
brackets cannot be bound. […]
```

The same refusal, on arm64 (the x86-64 half not repeated this time), so the two
options below are still the two options and neither has been taken.

**And this is still not `formal/`'s to fix**, which is what "Whose" says and
what `tools/control.py claims` confirms: `construct:mlir-and-gpu-globals` is
held by `formal-mlir-gpu`, whose subject is `std/gpu/**` and the MLIR dialect
constructs, and `workgroup_function` is a GPU launch abstraction at
`std/algorithm/backend/tile.mojo:48`. The doc records it so that claim is not
duplicated and so the 4 files are not counted twice in the `other refusal` row.

The one thing a reader should take from the re-verification is negative and
worth stating: nothing has moved, so nothing here is cheaper or more expensive
than it was, and the second option (refuse it in the stdlib, which is a
`new-modular` tree edit outside every worktree here) is still the only one that
is not a construct.

## The next step

One of two, and which one is a decision rather than an implementation:

  * **Bind the brackets to a declared parameter list.** The module already
    writes the declaration — `comptime Static1DTileUnitFunc = def[width:
    Int](Int) -> None` — as a module-level alias of a function TYPE. Reading a
    function type's leading parameters at the call site, and passing the
    bracketed values as ordinary leading arguments, is what the refusal text
    already describes as the right lowering. It needs the call site's knowledge
    that `workgroup_function` has type `Some[Static1DTileUnitFunc]`, which means
    the specialization answer has to be reachable from a PARAMETER's declared
    type and not only from a name's declaration.
  * **Or refuse it in the stdlib.** `tile.mojo` is GPU-only code and every one
    of its 4 dependents is the `algorithm` package's own plumbing; a
    `@parameter`-free spelling (`workgroup_function` called with the width as a
    normal leading argument) is the same program. That is a stdlib edit, and
    the new-modular tree is outside this worktree.

Either way the refusal stays until one of them lands: emitted with the brackets
dropped it would build, run, and return a number the source never wrote.
## Measured 2026-10-03 (`work/formal10-5`): the wall below the brackets is a FUNCTION VALUE

The refusal above is unchanged, on both architectures, byte for byte. What moved
is what a reader is told NEXT, and it is the wall this document's "next step"
runs into.

**A function has no representation on this path at all.** Measured, both
architectures:

```python
def plain(v): return v + 100
def call_it(f, x): return f(x)
def main(n): return call_it(plain, 5)
```

```
build: main: 'plain' is a function of this module read as a VALUE, and there is
no value of a function on this path: a formal value is one 64-bit word, and every
callee this backend reaches is a NAME — a function of this module, a struct's
constructor, a type conversion, or an export on the link line. Nothing here can
call through a word, so the call that would use it has no form. …
```

(The message is `model.function_value_refusal`, landed in the same commit as this
measurement; before it the same program was refused with `'plain' has no home:
the register allocator collected no home for it …`, which names an internal table
instead of the construct. Pinned by `test_formal_specialization.py`'s
`a function read as a value is refused by name`, on both architectures, with a
shadowing local as the negative guard.)

**So the two options at the end of this document are not the two options.** The
first — "bind the brackets to a declared parameter list", reading
`comptime Static1DTileUnitFunc = def[width: Int](Int) -> None` and passing the
bracketed values as leading arguments — is necessary and not sufficient, because
the thing it would pass them to is a WORD this path cannot call through. This
document already says the half of that it could see ("this path resolves
parameter types to words"); what it does not say is that a word naming a
function has no call form either. `workgroup_function` is declared
`Some[Static1DTileUnitFunc]`, so the row needs, in order: a value for a function,
a value for an `Optional` of that value, and then the brackets.

**What that costs the row's estimate, honestly.** Three constructs, not one, and
the first is a language feature this backend has no lowering for at all (no
indirect call exists: every callee is reached by name through `_functions`, a
struct declaration, a dylib export table or a type constructor). The 4 files
below it are still 4 files blocked, and no file of them moves until the first of
the three lands. Anyone picking this up should measure the function-value
question FIRST — it is checkable on a five-line program, which is how it was
measured here — rather than binding brackets.

**And "Whose" needs replacing.** `construct:mlir-and-gpu-globals` is not in
`python3 tools/control.py claims` any more, and `workgroup_function` is a GPU
launch abstraction rather than an MLIR dialect construct, so this row is
unowned work rather than somebody else's. It stays out of the `other refusal`
row's module-caused count for the reason the original author gave — it is not
counted twice — which is still true and is why the row belongs to whoever takes
the function-value question.

## Measured 2026-10-03 (`work/formal13-6`): the refusal stands, its MESSAGE has
## changed, and the wall after the representation is an INSTRUCTION

Two facts, because both narrow what the next session does and neither is what
this document recorded.

**The refusal is unchanged in substance and its text is not the text quoted
above.** Re-measured on both architectures:

```
build: main: 'plain' is a FUNCTION, and a function is not a value on this path:
it has no representation here — a value is one 64-bit word and a function is a
code address, so there is nothing for that word to hold, and passing one as an
argument, storing one in a container, or returning one is refused rather than
answered with a number that means nothing. `formal/hostmods/` has no module that
hands back a callable f…
```

`model.function_value_refusal`'s message was rewritten after this document
recorded it — it now names the representation question directly ("a value is one
64-bit word and a function is a code address") rather than enumerating the four
callee kinds, and it adds the hostmod sentence. **So a reader grepping for the
quoted text will not find it**, and the conclusion is the same: the row's first
construct, "a value for a function", is still refused by name.

**The next wall after the representation is an instruction, and it is another
claim.** A function value is a code address, so `f(x)` is an indirect call, and
the two backends have no encoding for one in use and no model step for one:

```
$ grep -rn 'encode_blr_xn' formal/*.py | grep -v pycache
formal/arm64.py:129:def encode_blr_xn(xn: int) -> bytes:
```

`formal/arm64.py:129` DEFINES `BLR Xn` and **nothing calls it** — there is no
emitter path that reaches it — and `grep -n 'blr' lib/ProofLib.lean
lib/Refine.lean` is empty, so the model has no step to prove one with. On x86-64
`formal/x86_64.py:771` is `call [rip + offset]`, an indirect call through
MEMORY, and there is no call-through-a-register spelling beside it.

That is `bugs/FORMAL_arm64_instruction_coverage.md`'s claim, so the function-value
lowering cannot be finished here even though its representation half is
`formal/`'s. **The dependency order for this row is therefore four deep, not
three:** an indirect-call instruction on both backends, a model step for each, a
value for a function, an `Optional` of one, and only then the brackets. The
first of those is somebody else's file and the two middle ones are a
representation decision this document already argues correctly and cannot
settle alone.

## What landed 2026-10-03: a function value is a CODE ADDRESS, and the brackets are leading arguments

**Claim** `project18:tile-specialization` on
`work/formal18-tile-specialization`. Three decisions, all in `formal/model.py`
so the two architectures cannot answer one construct differently, and all
reachable from both emitters:

| what | where |
|---|---|
| a function of THIS image read as a value is its entry ADDRESS | each backend's `_load_var`: `ADRP`+`ADD` (arm64), `LEA r, [rip+d]` (x86-64) |
| a call through a bound word is `BLR X16` / `CALL R11` | each backend's `_emit_call`, beside the direct-call arm |
| the specialization's bracket items are ordinary LEADING arguments, in bracket order, expanded from a comma list | `formal/monomorph.py::supplied_bracket_args` — the ONE bracket reader, shared with the demand walk |

`monomorph.supplied_bracket_args` is deliberately NOT
`comptime.specialization_args`, which is the reader for every other
specialization on this path: that one binds the items to a DECLARED list (it
pads a short bracket with 0 and truncates a long one), and a callee reached
through a value has no declaration in either architecture, so there is nothing
to pad against and nothing may be truncated. `f[3](x)` reaches the callee as
`f(3, x)`. Putting the reader in `monomorph.py` rather than in either emitter
is the "do not write a second specializer" rule made structural:
`_bracket_type_args` (the demand walk's reader of the same bracket) now expands
the comma list through the same `bracket_items`, so the two cannot disagree
about what `f[a, b]` contains.

**Measured, both architectures, against the interpreter's answer:**

```
$ python3 fire.py run .tmp/tile/prog.mojo          # the oracle
27
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/t/xm-arm64 .tmp/tile/prog.mojo .tmp/tile/lib.mojo
Built: .tmp/t/xm-arm64  [arm64/macho]      $ .tmp/t/xm-arm64 ; echo $?    → 27, 0
… --backend=x86_64 …
Built: .tmp/t/xm-x86_64 [x86_64/macho]     $ .tmp/t/xm-x86_64 ; echo $?   → 27, 0
```

where `lib.mojo` is the tile-shaped generator (`workgroup_function[tile_size]
(current_offset)` inside a `while`) and `prog.mojo` is a consumer that passes
its own generic `work`. That is the sweep's shape: a library whose callers are
four `algorithm` plumbing files, and a function value that crosses the dylib
boundary as DATA.

Pinned by `test_formal_specialization.py`: a function passed as an argument, a
call through a parameter, the tile shape, the same call with the callee in a
linked module, and two brackets — each RUN and compared against CPython on both
architectures — plus a case for the three refusals that remain. The test file's
§5 and §5b pinned the two REFUSALS this replaces, so both were rewritten; the
§5 rewrite also clears a row that was red on `master` for an unrelated reason
(`bugs/FORMAL_function_value_refusal_is_defined_twice_and_the_later_one_wins.md`
— its assertion named the wording of the shadowed copy of a duplicated
function, and the construct it pinned does not exist any more).

### The bracket is ambiguous, and the annotation is what settles it

`f[3](x)` through a word is a specialization or an INDEX, and the two produce
different code: read as a specialization, `3` is passed as a leading argument to
the word `f` holds; read as an index, it is an element lookup and the call is of
something else entirely. `model.value_call_bracket_reading` reads it off the
caller's own DECLARATION, and it is a DEDUCTION rather than a pattern match:

* `Some[F]` / `Optional[F]` / a `def[…](…) -> …` — **cannot be subscripted on
  this path at all**, so the bracket cannot be an index and must be a
  specialization. That is `tile.mojo`'s own declaration,
  `workgroup_function: Some[Static1DTileUnitFunc]`;
* a container (`List[Int]`, `String`, `SIMD`) — can only be indexed, so the
  brackets are an index and an element is not callable here;
* a scalar (`Int`, `Bool`, `DType`) — neither, and the program is wrong;
* anything else, INCLUDING AN UNANNOTATED parameter — refused
  (`model.value_bracket_reading_refusal`), because `f[0](x)` on an untyped `f`
  is genuinely ambiguous.

That last arm is why `stdlib/std/algorithm/backend/cpu/map.mojo` (`func(i)`, a
BARE call) is unaffected: there is no bracket to read, and the bare call through
an unannotated parameter lowers.

**A parser limit worth knowing, because it is what the stdlib spelling has to
work around:** a comma inside a nested type application does not parse.
`Some[def[w: Int, h: Int](Int) -> Int]` is a `SyntaxError` — the parser reads
`Int` and `h` as two arguments of `Some` — and a multi-line annotation is a
`SyntaxError` too. `tile.mojo` sidesteps both by naming its function types in
`comptime` aliases, so the two-bracket form (`workgroup_function[tile_size_x,
tile_size_y]`, `tile2d`) has to be spelled with the function type at the top
level of the annotation to be written at all.

### What is still refused, and why each one has no answer here

Three shapes, three sentences, all asked from the same place in both backends,
and all three now in `tools/formal_sweep_causes.py` (they were in
`other refusal`, the bucket that means nobody has looked):

* **a keyword through a value** (`f(x=1)`, or a keyword item in the bracket) —
  a keyword names a PARAMETER, and there is no parameter list in hand;
* **a bracket this build cannot read** — the arm above;
* **a parameter whose declared type cannot hold a function** (`List[Int]`) — the
  declared type refutes it, so it is refused at build time rather than turned
  into a branch through whatever word the container held.

A function of ANOTHER image read as a value is still refused, by the unchanged
`model.function_value_refusal`: this unit has the DECLARATION (it is how the
callee's parameters are bound for an ordinary call into a linked library) and no
CODE, and materializing an address for it needs a GOT slot this assembler does
not fill for anything but a C symbol.

## Where `tile.mojo` stands now, and what is behind it

The file is still refused, and the refusal MOVED — which is the measurement:

```
$ python3 tools/memslot.py --gb 8 --label tile -- python3 fire.py build \
      --formal --no-prove -o .tmp/tile/real \
      ../new-modular/Mojo/stdlib/std/algorithm/backend/tile.mojo
build: tile: the body reads 'tile_size_list', its *-parameter, and this path
has no variadic ABI. …
```

So the 4 files of this row — and the 8-in-10 that
`bugs/FORMAL_sweep_work_map_2026-10-03_b9.md` §4.1 measured landing here once
the export gate lifts — now stop at the next construct, in this order:

1. **`*tile_size_list` — a variadic parameter** (`tile.mojo:99`, and
   `*primary_tile_size_list` at `:135`). Its own message is right: a formal
   value is one 64-bit word, so the arguments a caller passes past the fixed
   ones have nowhere to be packed, and a tuple of them is a container whose
   frame belongs to the function that built it. **This is a change to the
   calling convention both backends AND the Lean proof share**, so it is not a
   light worker's row.
2. **`Some[Static1DTileUnitFunc]` — an `Optional` of a function.** The
   parameter annotation is READ (that is what settles the bracket, above) and
   the word passes through, but nothing can ask whether the optional is empty:
   `None` and a value are one word here.
   `FORMAL_stdlib_optional_needs_a_representation.md` owns that, and it is 43
   files of its own.
3. **`comptime for tile_size in tile_size_list` over a `List[Int]`, and
   `secondary_tile_size_list[i]`** — a comptime loop over a value this path
   represents as a frame-allocated blob.

**And the proof path is not the first wall, which corrects the order this
document's last section gave.** It said the first thing needed was a model step
for an indirect call. Measured on this tree, a program that calls a SECOND
FUNCTION AT ALL cannot be proved, whatever the call looks like: a direct
`work[3](5)` from `main` raises the same

```
NotImplementedError: universal theorem: the call at 0x100000438 targets
0x10000044c, a second function in the same image. … that is interprocedural
walking: a return-address map in the framework, not a missing case here.
```

on `master` and on this branch (both measured). So a model step for `BLR` is
necessary and it is not what is in the way; the return-address map is. When
that lands, the new instruction needs its own step — `encode_blr_xn` has been in
`formal/arm64.py` since before any lowering called it, and `encode_call_r64` is
new here — and `bugs/FORMAL_arm64_instruction_coverage.md`, which counts an
encoder nothing emits as not-an-instruction, is where the arm64 half of that
count lives: `blr` moved from "encoded, never emitted" to emitted, which is that
survey's own measurement moving and not a claim about the survey.
