# FORMAL_type_name_as_a_value: a bare TYPE name in a value position is refused as a name with no register

**Status: the COVERAGE half is landed and measured.** A type is a word on this
path and the word is a tag, so `t == Int32` is an integer comparison, a type
crosses a call boundary, and a `dtype: DType` field holds one. Both
architectures, tested against CPython and against the interpreter.

**Coverage: 0 of the 4 reachable files reach `pass`, and 1 of the 5 the 2026-09-30
sweep named is no longer reachable at all.** Both numbers are measured below, not
argued, and both are worth reading before anyone plans against this construct.
What the change buys is the construct and a diagnostic that is true of the file:
the reader was being sent to the register allocator for a fact about the
language.

---

## 1. What was wrong

A type name read as a VALUE was refused by `formal/build.py`'s name-placement
walk with `model.unresolved_name_refusal`:

```
$ cat a.mojo
def f(t):
    if t == bool:
        return 1
    return 0
def main(n):
    printf("a=%d", f(bool))
$ python3 fire.py build --formal --no-prove a.mojo -o a.arm64
build: main: 'bool' has no home: the module-level symbol table is empty for
this unit, and the reading function declares no local or parameter by that
spelling. This path places a name in a register or a spill slot allocated for
THIS function, a receiver field's frame, or a module-level constant the build
folded — and a name in none of them is refused rather than read out of whatever
register the allocator left behind, which is how one program returned 10 on
arm64 and 0 on x86-64 where the source says 5
```

Every clause of that sentence is false about this program. `bool` is not a name
that was left without a register: it is a TYPE, the source says so where it
stands, and there is no register question about it. This is the outcome
`test_refusal_taxonomy.py` calls the worst one — **a refusal
whose stated reason is entirely false** — and a reader sent to the allocator for
`bool` goes and looks at `_load_var` and finds nothing, because the walk is
asking the wrong question.

The interpreter already has an answer, and it is the right one: `myinterpreter.py`
binds `DType.int32` to the same `Int32` object the bare name is, and
`f(DType.bool)` where `f` tests `t == DType.bool` returns 1.

## 2. The decision: a type is a TAG

`formal/model.py`: `TYPE_VALUE_NAMES`, `_DTYPE_MEMBERS`,
`_DTYPE_MEMBER_PREFIXES`, `_dtype_member_type`, `type_tag`, `_tag_of_text`,
`type_value_tag`, `type_tag_for_name`, `type_value_name_space`,
`type_value_tags_are_distinct`, `is_dtype_member_access`, `dtype_object_refusal`,
`dtype_member_refusal`.

A type is one 64-bit word here, and the word is a 63-bit FNV-1a of the type's
**canonical name**. Three properties, each a separate decision:

| what has to be true | how it is met | what the alternative would cost |
|---|---|---|
| the same number in every unit of the image, including across a dylib boundary | a hash of the name, so it is a function of the STRING and of nothing else | an index into a per-unit discovery order — the "reflection table" the earlier note on this file called the blocker. It cannot work: two units compiled apart never meet to agree on an order |
| a function of the TYPE, not of the spelling | `type_value_tag` reads the spelling, canonicalises it, and hashes the canonical name, so `Int32` and `DType.int32` are one word and `DType.int`/`DType.index`/`Int64` are one word | hashing the spelling would make `f(DType.int32)` answer for `f(Int32)`, which the interpreter says is the same type |
| DISTINCT for distinct types | the tag is only ever asked about a name in the closed set `type_value_name_space()`, and injectivity over a closed set is a fact rather than a bound | a 64-bit collision is improbable, not impossible, and "improbable" is not an argument a value model gets to rest on. `type_value_tags_are_distinct()` is checked at import of `test_formal_run.py`, and `every_type_tag_is_distinct` compares all 1275 pairs **at run time in the emitted image** |

### Where the tag is materialised, and why that place

Both backends materialise it in `_load_var`, at the end, exactly where the arm64
X19 fall-through and the x86-64 immediate-0 fall-through were. The placement is
load-bearing and it was measured, not chosen:

* **Earlier is wrong.** An arm in `_emit_expr` ahead of `_load_var` made
  `Int = 7; printf("%d", Int)` print the tag of the type `Int` (`-913451874`)
  and exit 0, on both architectures — silently, on every program with a local
  whose spelling is a type name. The cause is structural: `_load_var` is the
  only reader of "does this name have a home" in the file, so any earlier arm is
  a second reader that cannot see the first one's tables.
  `a_local_named_like_a_type_still_wins` is the row that says so.
* **A type APPLICATION is not a type value.** The walk asks the tag only for a
  name that is not the base of a subscript. Without that exclusion the
  `List[Self.T]()` in `std/collections/binary_heap.mojo` stopped being examined
  at all: its refusal moved from `BinaryHeap___init__: 'List' has no home` to a
  refusal in a LATER FUNCTION, which is the signature of a construct that has
  stopped being looked at rather than one that has been answered. `f[a, b](x)` is
  a specialization of `f`, not a read of a value named `f`, and that is a
  different question with its own answer (`model.subscript_callee_names`).

One side effect worth stating because it is easy to assume and was measured not
to be there: `len()` of a type name. `len(List)` and `len(bool)` are refused by
the length machinery with **byte-identical messages before and after** this
change, on both architectures (the four production files reverted in place and
the same two programs rebuilt), so this construct neither introduces nor repairs
that refusal. It is a pre-existing imprecision and §5 has it. What is *not*
claimed here is anything about what another branch's test pins for it — that is
answerable by running that branch, not by reading this one.

### What is admitted, and what is refused

| spelling | verdict | why |
|---|---|---|
| `bool`, `int`, `Int32`, `NoneType`, `Self`, `String`, `List`, `SIMD`, … | a tag | a type name this path knows. The set is DERIVED from the six tables that already know type names (`POINTEE_WIDTHS`, `POINTEES_REFUSED`, `INT_TYPE_CTORS`, `IDENTITY_TYPE_CTORS`, `UNREPRESENTABLE_TYPE_CTORS`, `POINTER_TYPE_CTORS`) plus three the tables do not have: `BFloat16` (the fourth of the language's four floats; `POINTEES_REFUSED` lists three), `Self` and `bool` |
| `DType.int32`, `DType.uint8`, `DType.bfloat16`, `DType.bool` | a tag, the same word as the bare name | the spelling convention, as five PREFIXES (`uint8` is `UInt8`, where the capital `U` is the unsigned marker — a "capitalise the first letter" rule gets that one wrong and no test of `int8` would notice), plus three exceptions where the member is not named after its type (`int`/`index` are `Int64`, `uint` is `UInt64`) |
| `DType.float8_e4m3fn` and its six siblings, `DType.uint128` | **refused, by name** | 202 spellings in the corpus. Their type names are in no table here, and admitting them by SHAPE would make the name space a tag is asked about unbounded — which is exactly what the injectivity argument needs it not to be. The refusal says which members do work and that naming the type instead of the member is the same value |
| a bare `DType` | **refused, by name** | `DType` is the type OF a type. A formal value is one word and there is nothing in a freestanding image for a word to point at that would answer "what type is this". The two things that do work are named in the message: a member, or a parameter annotated `DType` whose value is the member's tag by the caller's doing |
| `len(bool)` | refused, by the length machinery | see §5 |

## 3. The measurement, and it is not good news

`tools/formal_sweep.py` on eight files, on this tree, before and after, same
machine, same day. "before" is this branch's parent (`53f89ae7`) with the four
production files reverted in place; the sweep's own CAS was cleared between the
two runs (`0 hit / 8 miss` then `5 hit / 3 miss`) so neither run was answered
from the other's cache.

| file | class before → after | terminal before → after |
|---|---|---|
| `std/testing/prop/random.mojo` | codegen/dependency → codegen/dependency | `Rng_rand_scalar: 'DType' has no home` → **`Rng_rand_scalar: 'rebind' has no home`** |
| `std/testing/prop/__init__.mojo` | codegen/dependency → codegen/dependency | as above, through `.random` |
| `std/testing/prop/runner.mojo` | codegen/dependency → codegen/dependency | as above, through `.random` |
| `std/gpu/host/func_attribute.mojo` | codegen → codegen | `FuncAttribute_MAX_DYNAMIC_SHARED_SIZE_BYTES: 'DType' has no home` → **`Attribute_write_to: 'Attribute' is read at line 156 before anything in this function stores it`** |
| `tools/detrace_diff.py` | codegen/dependency → codegen/dependency | **UNCHANGED, and the reason is §3.1** |
| `std/collections/binary_heap.mojo` | codegen → codegen | unchanged — my change does not touch the `L[T]()` spelling, and §2's subscript exclusion is what keeps that true |
| `std/collections/__init__.mojo` | codegen/dependency → codegen/dependency | unchanged (binary_heap) |
| `std/algorithm/__init__.mojo` | codegen/dependency → codegen/dependency | unchanged (binary_heap) |

`PASS=0` before and after, `codegen coverage 0/8` before and after.

### 3.1 The map's fifth file is not reachable on current master

`tools/detrace_diff.py` was the fifth file the 2026-09-30 sweep filed under this
cause, refused at `main: 'int' has no home` — its `type=int` argument to
`argparse`. On this tree it is refused **before the walk looks at it at all**:

```
$ python3 fire.py build --formal --no-prove tools/detrace_diff.py
build: detrace_diff.py imports 'argparse', which cannot be built either:
argparse.mojo: `_name_len(...) == nlen` compares two values this path can only
call numbers …
```

Verified in both directions by reverting `formal/model.py` and `formal/build.py`
in place and re-running: byte-identical refusal with and without this change. So
the count for this cause on current master is **4 reachable files, not 5**, and
the map's 5 is a snapshot of `24f96604`, where the import check came later in the
build than the name walk. Worth recording because a plan that budgets five files
here is budgeting one that cannot be reached.

### 3.2 Where the four land, and it is the same lesson as `L[T]()`

* **`rebind[Scalar[dtype]](Scalar[DType.bool](…))`** — `std/testing/prop/random.mojo:122`,
  and it is on the SAME LINE as the `DType.bool` this change answers. `rebind` is
  a bracketed callee on a name the module does not define, and the type
  application around it is a second bracketed callee (`Scalar[DType.bool](…)`).
  Both are the `subscript_callee_names` construct, which is a different question
  with its own answer; neither is a type value.
* **read-before-store** — `func_attribute.mojo:156` reads the `Attribute` enum
  value `self` was bound to and nothing in that function stores. A flow question
  in a file that is refused one question at a time.
* **`argparse`** — where `tools/detrace_diff.py` already was, and still is; §3.1.

So: of the four reachable files, the three that moved share ONE next question
(the bracketed callee in `random.mojo`, which they reach through the same import
chain) and the fourth has another (a read-before-store). **None of them is this
construct.** The honest reading of the count is the same one
`bugs/FORMAL_sweep_work_map_2026-09-30.md` §3.1 reached for the `L[T]()` half of
the same row: the row's "41 files" was one false diagnostic, a dylib export rule,
a bare-type-name rule and premise B2 — and this document is the bare-type-name
rule, which is the smallest of the four.

## 4. What the other two branches touching this construct should know

Recorded so a merge is a decision rather than a surprise. Every case in this
document was built on this tree alone, with neither branch present; what these two
notes are for is the merge, and each says which way it cuts.

* **`work/formal-sweep-next`'s `L[T]()` half** (`model.subscript_callee_names`,
  `empty_blob_constructor`) is the other spelling of row 2 and is orthogonal: it
  lowers the zero-operand container constructor, this one makes the type NAME a
  value. The subscript exclusion in §2 is what keeps the two from colliding — it
  holds `List[Self.T]()` at "'List' has no home" and `List()` at "constructing
  List has no representation", the two spellings exactly as they were, so that
  branch's `subscript_callee_names` is still the thing that decides them.
* **`work/frontend-silent`'s `f5bcb0a1`** (a bare TYPE name in a value position is
  refused as a type, not as a register) rewords the same refusal this change
  LIFTS, and it defines a recogniser over the same four tables this change
  derives `TYPE_VALUE_NAMES` from. Its message ("a type is not a value on this
  path … an interned tag per type … which is reflection-table work this path does
  not have") is now **false about the program on this tree**: a type IS a value
  here and the tag exists. The coverage half it explicitly left open is what
  landed. Its two boundary guards have equivalents in this branch's
  `TYPE_VALUE_CASES` — `a_type_name_as_a_callee_is_still_a_construction` (a type
  name in callee position is a construction: `int(int(5))` → 5) and
  `a_local_named_like_a_type_still_wins` (a local of the same spelling wins) —
  and both pass; its two refusal cases are answered here, which is the point.

## 5. What is still open, each with its next step

**The first two entries below CLOSED on 2026-10-01**, together, because they are
one decision: a type is a value, so it is a KIND. `formal/model.py` has
`TYPE_KIND`; `ValueKinds.name_kind` returns it for a name no local and no module
global binds (last, which is the guard — `a_local_named_like_a_type_still_wins`
cannot regress); `len_refusal` has the row the `None` branch was faking; and
`model.type_index_refusal` is the sibling of `string_index_refusal` one level up.
`test_formal_run.py`: `len_of_a_type_is_refused` is now `refuse_without:` (the
same program, asserting the false sentence is GONE and a type-specific one
replaced it), plus a bound-local `len` row, three index rows (list, bound local,
string base) and `TYPE_VALUE_NUMBER_CASES` — two `print` rows whose expected
answer is `type_tag("bool")` read from the model, because a tag IS a word and
`print()` must keep printing it (`model.is_number_kind`).

**The filing's prediction for the subscript half was wrong in a way worth
recording: it is not a wrong number.** §5 below said `xs[bool]` "would read a
blob at a tag-derived offset instead of refusing". Measured on this tree, both
architectures, before the change:

| program | arm64 | x86-64 |
|---|---|---|
| `xs = [10, 20, 30]; printf("%d", xs[bool])` | exit **1**, nothing printed | exit **1**, nothing printed |
| `s = "abc"; printf("%d", s[bool])` | **SIGSEGV** | **SIGSEGV** |

The bounds check gets there first — a tag is a large positive 63-bit hash, so it
is out of range for a three-element blob and takes the out-of-range exit. So the
defect was a silent *exit* on a program a reader can write, which is still a
defect (no diagnostic at all, on both architectures, for a program whose failure
is at build time on CPython with `TypeError: list indices must be integers or
slices, not type`) but is not the plausible-looking wrong number the rest of
this file is about. `s[bool]` segfaulting is the worse half and it is the one
that made the fix worth doing: a string index is `s + i` on a bare `char *` and
there is no bounds check to catch a tag.

Also measured while doing it, and **a widening this change introduced on purpose**:
`print(bool)` in the BARE position was refused outright before it ("print()
cannot tell whether IdentExpr is a string or a number") and now prints the tag,
which is the same word `print(t)` for `t = bool` already printed. That is the
same widening the construct already made for `t`, so leaving the bare spelling
refused would have been the inconsistency rather than the safety.

### Still open

* **`DType` as a value is a refusal, and that is a real limit.** A program that
  wants the runtime type object — `DType(Int32)`, `dtype.name`, `dtype.is_signed()`
  — still has no answer, and `formal/model.py`'s `POINTEES_REFUSED` already
  refuses the method calls for the float half of that. **Next step:** a type
  object needs storage this image does not have (it is a pointer to something),
  so it is the same class of question as `FORMAL_string_value_model.md` and
  belongs to whoever owns the value model.
* **A `DType`-ANNOTATED field is still not `TYPE_KIND`.** `declared_type_kind`
  answers `String` and the integer names and a framed struct and a blob, and
  `DType` is none of those, so `b.t` for `var t: DType` is unclassified while
  `t = DType.int32` in a local is now a tag. **Deliberately left**, and the
  reason is the direction of the risk: the annotation is the one thing this path
  trusts about a slot, so making a declared `DType` field a tag would let
  `len(self.t)` and `self.t[i]` take a new branch on a shape the corpus uses
  (`std/testing/prop/random.mojo` and `func_attribute.mojo` both declare
  `dtype: DType`) for no gain — the two operations are refused either way, only
  with different sentences. **Next step**, if a reader wants it: a row in
  `declared_type_kind`, agreed over the holder's candidates like every other row
  there.
* **The float8/float4 family and `uint128`** (§2's table). 202 corpus spellings,
  one entry each in `TYPE_VALUE_NAMES`, and the distinctness check grows with it
  by construction.

## 6. Verification

| command | this change | the 2026-10-01 follow-up (`TYPE_KIND`) |
|---|---|---|
| `python3 test_formal_run.py` | **PASS=401 FAIL=0**, of which 13 are the new cases below | **PASS=533 FAIL=5** — the same five fail on `master` (four `byref_cross_module_*`, one `a_mutated_module_global_is_refused`), measured by running those case names against `git archive master`; they belong to other claims. 6 of the new rows are the ones in §5 |
| `python3 test_formal_imports.py` | PASS=41 EXPECTED=0 FAIL=0 | PASS=43 EXPECTED=0 FAIL=0 |
| `python3 -m unittest test_formal_sweep_truth` | Ran 31 tests — OK | Ran 31 tests — OK |
| `python3 test_formal_link_accounting.py` | 133 passed, 0 failed, 133 checks | 174 passed, 0 failed, 174 checks |
| `python3 test_refusal_taxonomy.py` | — | PASS (156/156 checks, 33 families, 53 causes) |
| `python3 -m unittest test_formal_sweep` | — | Ran 76 tests — OK |
| `python3 test_formal_value_model.py` | — | PASS=19 FAIL=0 |
| `python3 test_formal_target_queries.py` | — | PASS=25 FAIL=0 |
| `python3 test_formal_toplevel.py` | — | PASS=85 FAIL=0 |

The answered cases' expected values are what CPython prints for the same text
(`a=12 b=10 c=1 d=1 h=7`, and exit 5 for `int(int(5))`), run with a `printf`
shim; the `DType` spellings' expected values are what `python3 fire.py run`
prints for the same text (`e=11 f=7 g=1`). Both are quoted in the test file, and
both agree with what the backends execute on **both architectures** — the
x86-64 answers were measured for every case as well, since `run_case` builds the
host architecture for an answered case and both only for a refusal.

## 7. Files changed

| file | one line |
|---|---|
| `formal/model.py` | the tag, the name space, the `DType` member spelling rule, the two refusals, and the injectivity check |
| `formal/build.py` | the name-placement walk places a type name (and only a bare type name, never a subscript base) and refuses the two type shapes by name |
| `formal/arm64_codegen.py` | `_load_var`'s last resort; the `DType.<member>` arm in `_emit_expr` |
| `formal/x86_64_codegen.py` | the same two, x86-64 |
| `test_formal_run.py` | `TYPE_VALUE_CASES` (6), `TYPE_VALUE_DTYPE_CASES` (3), `TYPE_VALUE_REFUSALS` (3), `TYPE_VALUE_TAG_CASES` (1, generated) |
| `formal/model.py`, both backends, `test_formal_run.py` (2026-10-01) | `TYPE_KIND`, `is_number_kind`, the `len_refusal` row, `type_index_refusal`, the `print()` conversion switch and the subscript choke point; `TYPE_VALUE_REFUSALS` (7, one of them reworded to `refuse_without:`) and `TYPE_VALUE_NUMBER_CASES` (2) |

## 8. Why it is NOT the same construct as the one that was fixed

Kept from the original filing, because the distinction is the reason this
document exists and neither §2 nor §5 states it: the specialisation fix that
landed alongside changed *which* refusal fires, and that is a different thing
from this. This is about the refusal that fires being **false about the file**
— the project's own rule (`FORMAL_known_limits.md`, "a message that is false
about the file is worse than no message"). Compare the two shapes:

* a *read* of `NoneType` really is a value read, and the storage enumeration
  is the right story — `model.module_global_refusal` says the same thing in its
  own words for the neighbouring case ("a name in none of them has no address
  to read");
* a *type name in a type position* is not a read of anything, so no
  enumeration of value storage can be right about it.

The second needs its own answer, and there are two honest ones.
