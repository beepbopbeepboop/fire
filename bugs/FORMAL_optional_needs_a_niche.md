# `Optional[T]` has a representation now, and the payloads it cannot answer are exactly the ones with no word left

**Status 2026-10-05 (`formal25-4`): §4 is FIXED, and it was a WRONG ANSWER on
both architectures rather than the limitation §4 called it — the gap was
writable the moment the link line existed, and what it wrote was `Some(0)`
where the program said `None`.** Read this before §4, whose "the next step is
for `formal/imports.py`'s per-module function tables to carry parameter
annotations, which is a project and not a patch" is the plan as it was written.

**What was wrong, measured on both architectures, byte-identical:**

    lib3.mojo   def tb(z: Optional[Bool]) -> int:
                    if z is None: return 100
                    return 1 if z else 2
    main3.mojo  from lib3 import tb
                printf("%d", tb(None))          ->  1
                                             CPython: 100

`optional_none_word` puts `None` at 2 for an `Optional[Bool]` payload and at
`1 << w` for a narrow integer, while `None` folds to `NONE_WORD` = 0 — which is
a payload VALUE. So the callee compared 0 against its own niche of 2 and took
the "has a value" arm, from a program that built green and exited 0.
`Optional[String]` was right, by accident: its niche IS 0.

**Why the identical program with the callee in the SAME file answers 100** is
what makes this a boundary defect rather than a question about `Optional`: the
two pipelines this tree runs must not answer one construct differently because
of where the callee was compiled. §4's own framing was right about the cause
and wrong about the severity — `apply_optional_none_representation` resolves a
callee's parameter annotations through `_callee_defs(functions)`, which is the
functions of THIS module, and it runs inside `_prepare_functions`, which runs
BEFORE `_resolve_imports`. So the imported declaration was not in hand. That is
why the gap existed, and it is exactly why it did not need guessing to close.

**What landed.** `model.imported_optional_param_annotations` is the PARAMETER
half of the reader `imported_callee_kind` already was for the RETURN, keyed by
ARGUMENT index with the receiver offset applied in the reader — a method's
receiver travels by pointer (`doc/ABI.md`, "The formal backend's receiver
convention") and is not argument 0, so numbering it as parameter 0 would
substitute the niche for the RECEIVER, whose declared type names no `Optional`,
so the substitution would never fire and the shape would read as answered while
doing nothing. `build.substitute_none_into_an_imported_optional` is the pass,
asked from `_run_late_checks` beside the other published-declaration consumers
because that is where `link_line` exists; it reads `external_declarations` (the
callee's own source, so the parameter list cannot disagree with the library on
disk) and reuses `_replace_none_with_niche`, so the niche word is asked of the
ONE table the in-unit pass asks. **The callee's DECLARATION names the payload,
never the call** — which is why `Optional[String]` is unchanged and correct.

`test_formal_module_attr.py` is 35/34: three payloads (`Bool`'s niche 2,
`Int8`'s 256, `String`'s 0) through `agrees_with_cpython`, three SPELLINGS (a
free function, `or_else`, and a method whose receiver is not an argument), and
the reader asked with no build at all for the case a build cannot show — an
argument index that is not an `Optional` one. The new row REDS without the fix.

**What is left is §2 (the two-word value, for `Int`) and §3 (an unstated
payload).** §3's own reasoning is unchanged and still correct: closing it needs
the same inference `FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_
inferrable`'s neighbour provides, which is not this row's claim.

**Claim** `project21:optional` on `work/formal21-optional`. **PARTIALLY
FIXED**, and the remainder is one payload family rather than the 43-file row the
sweep map names — measured, below, and the measurement is the most useful thing
in this document. **§5 is FIXED as of 2026-10-04** (`work/formal29-3`): the
register-passable sibling is out of the table and refused by name, because read
from the stdlib's own source its storage is a PAIR and the table's own argument is
about a word. **§4 is FIXED as of 2026-10-05** (`formal25-4`), and it was a wrong
answer rather than the limitation §4 recorded — see the Status above. What is
left is §2 (the two-word value, for `Int`) and §3 (an unstated payload) — each
written below with its own next step.

## What landed, and what it is

**A formal value is one 64-bit word, and `None` was the word 0 — which is also
the integer 0.** So `Some(0)` and `None` were the same word, and the two
answers disagreed with no diagnostic anywhere. Measured on both architectures,
before the change:

```console
$ cat z.mojo
def main() -> Int:
    var z: Optional[Int] = 0
    if z is None:
        printf("WRONGLY none\n")
    return 0
$ python3 fire.py build --formal --no-prove --backend=arm64 -o z z.mojo
Built: z  [arm64/macho]
$ ./z
WRONGLY none
```

`x is None` / `x == None` / `!= None` / `is not None` and `if x:` on an
`Optional` were all answered from that folded word, on both backends, and CPython
says `Some(0)` is not empty. **The null was not merely unavailable; it was
ambiguous, and an ambiguous null is the one outcome this backend's own rule
forbids** (`formal/build.py::refuse_none_comparisons` states the rule and could
not discharge it for a typed receiver).

**The representation.** An `Optional[T]` value is the payload word, and `None`
is a word `T` cannot produce — a **NICHE**. `formal/model.py`'s
`optional_none_word` is the one table that says which word per payload type:

| payload | `None` | why |
|---|---|---|
| a string, a pointer, a container, a frame address, any struct of this module | 0 | an address, and no address a program can hold is 0. This is also the word `x is None` **already** means for a reference on this path, so the Optional answer and the reference answer are one answer |
| `Bool` / `bool` | 2 | a `Bool` is a word holding 0 or 1 |
| `Int8`/`Int16`/`Int32`, `UInt8`/`UInt16`/`UInt32` | `1 << w` | a `w`-bit value lives in a 64-bit register sign-extended, so the set of WORDS it can hold is its own VALUE range and `2^w` is outside every one |
| `Int`, `Int64`, `UInt`, `UInt64`, `Float64`, `Float32`, `DType`, an unstated payload, a struct of another module | **refused** | every word is a value of it, or nothing here says what a value of it is |

So the four lowerings, all of them a compare against an immediate and a
conditional:

```
x == None          x == niche
x != None          x != niche
x is None          x == niche
x or_else(d)       x == niche ? d : x
x.value_or(d)      the same
x.or(d)            the same
x.unsafe_value()   x
bool(x)            x != niche          (Mojo's Optional.__bool__ is "does it HAVE a value")
```

**Where the code is**: `formal/model.py` for the table and the readers,
`formal/build.py::apply_optional_none_representation` for the ONE site that puts
the niche into the value stream, and `_optional_receiver_annotation` +
`_emit_optional_unwrap` in both backends. `lib/ProofLib.lean` mirrors the table
(`OptionalPayload`, `optionalNoneWord`, `optionalOrElse`, and the domain
theorems) and needs **no new step rule**, because every lowering above is a
compare against an immediate plus a conditional — which is why the niche was
chosen over the two-word form and not merely preferred to it.
`test_formal_optional.py` is 21 cases: 13 CPython-oracle, 3 pinned (Mojo's
`__bool__` deliberately disagrees with CPython's), 5 refusals (where a build that
succeeds is the failure), and the table's five properties as failures.

## What this does NOT do, measured

### 1. The 43-file row is not behind this any more, and was not

**The row's terminal cause is `FormatStruct`, which is `formal21-1`'s claim.**
Measured on four of the row's 41 files (`-9` counted 43; this tree's list is 41
— the `b10` round of `bugs/FORMAL_sweep_work_map.md` §2.4 says the row went 43 → 0
and every file moved one layer out), arm64, on this branch:

```console
$ for f in std/builtin/builtin_slice.mojo std/benchmark/__init__.mojo \
           std/builtin/int.mojo std/utils/_nicheable.mojo; do
    python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/row \
      /Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/$f
  done
build: builtin_slice.mojo imports 'std.format._utils', which cannot be built
either: `FormatStruct` is called, and it is imported from `std.format._utils`, so
the call has to bind a symbol `std.format._utils` exports. … If the call names no
type argument at all, the SOURCE is right and this path is short … in
bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md
```

Byte-identical on the other three and on x86-64. `FormatStruct(writer, "…")` is
the stdlib's own spelling against `struct FormatStruct[T: Writer, o: MutOrigin]`
— a bare call to a generic template, which this path does not infer type
arguments for. That is `formal21-1`'s claim, and it is 111 of the 170 files in
the b10 map's `other refusal` bucket, so it is not a small thing sitting beside
this row.

**The honest accounting is therefore: 0 of the 43 files gained a PASS, and the
Optional unwrap was not what they were blocked on.** What changed is that the
refusal behind it is now a **decision** (`optional_no_niche_refusal`, naming
`Optional[Int]` and the tagged two-word answer) rather than an admission that
no representation exists — which is what `UNWRAP_METHODS` has been saying on
both architectures for the row.

### 2. `Optional[Int]` — the row's own payload — is still refused, and the
### next step is the TWO-WORD value

`builtin_slice.mojo`'s fields are `Optional[Int]`, and `Int` is a full 64-bit
signed word (`formal/types.py`: values live in 64-bit registers, sign-extended),
so every one of the `2^64` words is a value of it and **there is no niche**. The
only sound one-word answer does not exist, and the two sound alternatives are:

* a **reserved sentinel under a stated exclusion** — sound for a `T` whose
  domain provably excludes it, which `Int` is not, and it is the one that made
  `Some(0)` wrong in the first place. **Not taken, and the table says why.**
* a **tagged TWO-WORD value** `{tag, payload}`, with `Optional[T]` the address of
  the pair. This covers every `T` including `Int`, and this target already has
  the machinery for a multi-word value — a struct of two fields IS a frame, and
  `struct_is_framed` / `struct_constructor_sites` / `receiver_writeback_name`
  are the whole of it. It follows the landed receiver convention rather than
  inventing a parallel one (no second return register; the receiver is a
  pointer and the callee writes back through it), which is exactly what
  `doc/ABI.md`'s "The formal backend's receiver convention" section records.

**Three measured reasons it is not a one-line change**, each of which a session
picking it up should check rather than take on trust:

1. **`Optional` is a stdlib struct this image does NOT compile**, so its frame is
   in no module's `structs_by_name` — and `struct_frame_block_bytes` sizes a
   construction site's reservation out of `decls`, so nothing is reserved for a
   block whose struct the table does not know. It needs an entry that says "a
   stdlib struct of N slots", not a struct declaration.
2. **`x is None` where `x` is a LOCAL holding the pair's address is a frame-slot
   read through a word that is not a receiver.** Every frame read this path has
   lowers from a RECEIVER (`self.f`) or from a name whose candidate struct is in
   `fn._frame_candidates`; a name declared `Optional[…]` has no candidate struct
   because `Optional` is not in this module's table. See
   `FORMAL_a_subscript_on_a_frame_slot_is_a_pointer_dereference_and_the_two_
   backends_disagree.md` for the shape, and note that this pass already needed
   `_frame_receivers`' census for the same reason (`h.<field>`), so the
   mechanism exists and the missing piece is a stdlib-struct entry.
3. **`x = None` becomes a store of a FRAME into a slot**, which is
   `_refuse_holder_use`'s case ("it outlives the frame it names"), and that
   refusal is `formal13-5`'s claim to answer. `Slice.__init__` is exactly this
   shape (`self.step = None`).

The niche table is what makes this row decidable rather than open-ended: it says
**which** `T` need the two-word form (`Int`, `Int64`, `UInt`, `UInt64`,
`Float64` — plus anything whose layout this build cannot see), so that work is a
list and not a project.

### 3. An UNSTATED payload type still folds to `== 0`, and that is a residual

`var z = None; if z is None:` still compares against 0, because the pass's
obligation is discharged only where the SOURCE stated an `Optional[T]`.
Refusing it would refuse every unannotated predicate in a corpus that annotates
almost nothing, and the two directions are not symmetric: the **unwrap** on an
unstated receiver IS refused (it needs the receiver's `Optional` type and there
is none — `UNWRAP_METHODS`' message, which is the right one), while the bare
comparison still folds. Measured both, and both are pinned in
`test_formal_optional.py` (`unstated_payload_cannot_be_unwrapped`).

Closing it needs the same inference the `or_else` path needs — a name's type
from a call's return type — and that inference is
`FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable`'s
neighbour. **Not this row's claim.**

### 4. A `None` ARGUMENT to an IMPORTED function's `Optional` parameter —
### FIXED 2026-10-05 (`formal25-4`), and it was a WRONG ANSWER

The paragraph below is the diagnosis as it stood, and the DIAGNOSIS was right
while the severity was not: it said the folded 0 "keeps" and measured it as a
limitation, where the measurement is that the callee then takes the "has a
value" arm and answers as though it had been handed `Some(0)`. Read the Status
at the head of this file for the numbers, the two architectures, and what
landed. Kept as the statement of what was believed, which is what made it
actionable: the paragraph says the alternative is guessing a parameter's type
from the call, and the fix is the one thing that is NOT a guess — the callee's
own declaration, read through `formal/imports.py`'s `external_declarations`,
which the emitters already read for exactly this class of question.

`apply_optional_none_representation` resolves a callee's parameter annotations
through `_callee_defs(functions)` — the functions of **this** module, because a
build compiles each module nested and an imported signature is not in hand. So
`h.put(None)` where `put` is declared here works, and `h.put(None)` where `put`
comes from another module kept the folded 0. **What is missing was never the
DECLARATION** — `external_declarations` has carried it since a defaulted
parameter arriving as a stack address was measured — but the LINK LINE, and the
one pass that reads it runs after `_prepare_functions`, which is where the
substitution has to happen because it rewrites the `None` NAME before it folds.

### 5. `OptionalReg` was in `OPTIONAL_TYPE_NAMES` on the strength of the
### spelling alone — FIXED 2026-10-04, and the second half of the fix was the
### part that mattered

**It is no longer in `OPTIONAL_TYPE_NAMES`, and it is now REFUSED BY NAME.** The
doc's own two options were "drop it, or give it its own representation keyed on
`_OptionalRegStorageFor[T]`", and the measurement settles which: read
`std/collections/optional.mojo` rather than its spelling.

```mojo
struct OptionalReg[T: TrivialRegisterPassable](…):
    comptime _Storage = _OptionalRegStorageFor[Self.T]
    var _value: Self._Storage

comptime _OptionalRegStorageFor[T: TrivialRegisterPassable]: _OptionalRegStorageTraits =
    _NicheableOptionalRegStorage[T] if conforms_to(T, UnsafeNicheable)
    else _DefaultOptionalRegStorage[T]

struct _NicheableOptionalRegStorage[T](…):
    var storage: Self.StorageType        # StaticTuple[T, 1] — the payload + an index

struct _DefaultOptionalRegStorage[T](…):
    var _value: !kgen.variant<T, i1>     # a TAGGED value
```

**Both storages are TWO WORDS.** So `OptionalReg[T]` is a pair for every `T` whose
`UnsafeNicheable` conformance this build cannot see, and reading it as the one-word
`Optional[T]` is a WRONG ANSWER rather than a missing one: `x is None` became
`x == niche`, and a niche is a word of a value that has two — `2` for a `Bool`
payload, `0` for a `String`, neither of which is what an empty `OptionalReg` holds.
Which storage applies is a `conforms_to(T, UnsafeNicheable)` decided inside the
stdlib module; a build reads declarations rather than resolving conformances, so
the fact that decides the layout is one it has no source for.

**Dropping the name ALONE would have been worse than the bug**, and that is the
half worth recording: with nothing recognising the annotation,
`apply_optional_none_representation` substitutes nothing and `x is None` folds to
`== 0` — the `Some(0) == None` ambiguity this whole representation opened to
remove, back through a different door. So the two halves are one change:
`model.OPTIONAL_REG_TYPE_NAMES` + `model.optional_reg_base_name` (the BASE, so the
bare `OptionalReg` is refusable too — a type with no argument is still a pair) +
`model.optional_reg_refusal`, and `formal/build.py::refuse_optional_reg_annotations`
asked where `apply_optional_none_representation` is asked and for its reason.

**A FIELD is included in the refusal even when nothing reads it as an
`OptionalReg`**, because a field holding a pair is a frame whose layout this path
cannot describe — the same argument `struct_default_word`'s `("nested_frame", …)`
arm makes for a one-word holder of a frame. That is why the pass walks the whole
unit rather than the comparisons.

Measured, both architectures, all four declaration spellings refused with the
construct in the message: a local, a field (`Holder.slot`), a parameter
(`take(z: OptionalReg[Int32])`), and the bare `OptionalReg`.
`test_formal_optional.py` is 25 cases — 22 before, three new REFUSAL rows, where
the refusal-is-a-failure rule is theirs — and `test_formal_value_model.py` is 82/82.
`doc/ABI.md`'s `Optional[T]` section says the same thing where a client binding the
symbols reads it.

Cost in files: **zero**, measured — `OptionalReg` appears in no file in this
repository and in no `formal/hostmods/` module, and in the stdlib only in six
modules (`std/collections/optional.mojo` and `__init__.mojo`,
`std/collections/check_bounds.mojo`, `std/memory/unsafe_pointer.mojo`,
`std/_plugin/_trait.mojo`, `std/ffi/__init__.mojo`), none of which this build
compiles. So this was a claim about a NAME, and it is now a claim about a
REFUSAL, which is the same claim with a diagnostic.

**What this does not do:** it does not give `OptionalReg` a representation. The
two-word answer is `OPTIONAL_TWO_WORD`'s, priced once above and needed by both
`Optional[Int]` and `OptionalReg[T]`, so it is the same project either way — and
`OptionalReg`'s case additionally needs the trait conformance resolved, which the
niche table's argument does not have.

## What was verified, and how

Every row above is a `fire.py build --formal --no-prove` on both architectures,
or a run of the image, or a unit read of `formal/model.py`. Specifically:

* `python3 test_formal_optional.py` — **21 PASS / 0 FAIL** (13 CPython oracle,
  3 pinned, 5 refusals, plus the table's 5 properties and the Lean mirror).
* `python3 test_formal_run.py` — **960 PASS / 0 FAIL**.
* `python3 test_formal_value_model.py` — **61 / 0**.
* `python3 test_formal_method_param_field.py` — **26 / 0**.
* `python3 test_dataclasses_formal.py` — **84 passed / 0 failed**.
* `python3 test_formal_frame_len.py` — **10 / 0**;
  `python3 test_formal_globals.py` — **56 / 0**.
* The four row files above, arm64 and x86-64, with the refusal text diffed.

**Not verified here, and it needs the integrator:** `make gate` (this branch
touches `formal/model.py`, `formal/build.py` and BOTH backends, which the
project's own rule makes a full gate), a `formal_sweep` over the corpus (so the
BUILT count's movement is unmeasured — the direction is BUILT → CODEGEN for the
files that used to build a WRONG `Optional[Int]` answer, which is the correct
direction but a count the reader should see), and a `lean` build of
`lib/ProofLib.lean`, which is only reached through `formal/lean.py` and must not
be launched from a test.

## The existing docs, and what is now stale in them

* `FORMAL_stdlib_optional_needs_a_representation.md` — **its subject is
  answered and its history is not**: it records three revisions of a dependency
  chain whose first arrow has moved four times, and its §"The next step" names
  the tagged tag as the answer. It is kept because the measurements in it (the
  `Variant` layout, the `__mlir_op` path, the three chain revisions) are how the
  two-word row's cost was arrived at, and because a reader who wants the
  two-word form needs the history of why the niche was chosen first. **Its
  "NOT FIXED" headline is wrong as of this commit.**
* `FORMAL_builtin_slice_optional_field_is_a_frame_holder.md` — unchanged and
  still accurate; it is the `struct`-typed-field question, which this
  representation does not touch.
* the `b10` round of `bugs/FORMAL_sweep_work_map.md` §2.4 — the row it names is not
  blocked on this any more, and was not (§1 above).
