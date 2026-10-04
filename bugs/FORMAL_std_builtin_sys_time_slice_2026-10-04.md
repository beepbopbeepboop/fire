# FORMAL_std_builtin_sys_time_slice_2026-10-04: round 2 over eight `std/` directories — one root cause fixed, and the claim census that says why the other 74 files are not this slice's

**Slice:** the 85 `.mojo` files under
`../new-modular/Mojo/stdlib/std/{builtin,math,bit,random,format,utils,sys,time}`
(builtin 38, math 6, bit 3, random 4, format 4, utils 13, sys 15, time 2).
**Claim:** `sweep20:std-builtin-2` on `work/formal20-std-builtin-2`.
**Status:** swept complete on BOTH architectures, one root cause fixed with
tests, and **every one of the 13 remaining in-file refusals (of 14 measured)
and all 60 dependency refusals attributed to a named owner.** The headline is the last
part: this slice has no unowned row left in it, and §4 says which claim each
of the remaining walls belongs to, so the next worker on any of them starts
from the wall rather than from a re-measurement.

**This is round 2, and round 1's doc is `FORMAL_std_builtin_math_slice_2026-10-03.md`**
(`formal19-4`'s claim), which covered six of these eight directories and is not
duplicated here. The differences that matter:

* `sys/` (15 files) and `time/` (2) were **not** in round 1's scope at all, so
  every number about them below is new;
* the walls behind the slice **moved** since round 1, which is why §2's table is
  not round 1's: round 1's two blockers (`binary_heap.mojo`, 40 files, and
  `builtin_slice.mojo`, 11) are **gone from this slice's report**, replaced by
  one row that is 6 files of this slice and 123 files of the corpus;
* round 1 landed two fixes worth **0 files each** and said so. This round
  landed a third one, also worth **0 files here**, and §5 says plainly what it
  was worth instead. Three rounds of that on one slice is a fact about the
  slice, not about the workers, and §6 is the sentence to read before picking
  up anything here.

---

## 1. The run

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib/std
python3 tools/memslot.py --gb 8 --label sweep20-arm -- \
  python3 tools/formal_sweep.py -j 2 -t 120 $S/{builtin,math,bit,random,format,utils,sys,time} \
  > bugs/sweeps/sweep20-std-builtin-sys-time-arm64-BEFORE.txt 2>&1
# … the same command after §5's commit, twice more, and once with --arch x86_64
python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep20-std-builtin-sys-time-arm64-AFTER.txt
```

Three logs committed: `…-arm64-BEFORE.txt` (this tree before §5's commit),
`…-arm64-AFTER.txt` (after), and `…-x86_64.txt`. `peak 0.3 GB` against the 8 GB
reservation on every arm — this is a `--no-prove` codegen sweep, so no lean
runs, and `formal_sweep.py`'s own comment is the standing statement of what
that does and does not cover.

| class | arm64 | x86-64 |
|---|---|---|
| **pass** | **11** | **11** |
| built-with-admitted-contracts | 0 | 0 |
| **codegen** (a refusal IN this file) | **14** | **14** |
| **codegen/dependency** (refused one level down) | **60** | **60** |
| not-answerable / backend-crash / tool | 0 | 0 |
| **codegen coverage** | **11/85 = 12.9 %** | **11/85 = 12.9 %** |

**The two architectures are the same sweep, file for file and message for
message.** All **74** classified paths carry the same class, and **73 of the 74
carry byte-identical refusal text**; the 74th is `float_literal.mojo`, and the
reason is bookkeeping rather than arch drift — the arm64 log was taken before
§5's last refinement (the `other module` sentence), and re-running that one
file on both backends gives identical text (measured, quoted in §5). That is
the standing measurement of `FORMAL_sweep_work_map_2026-10-03_b9.md` §2.2,
re-measured over a slice that is a third of the corpus.

The 11 passes: `builtin/{__init__,_closure,floatable,identifiable,inline_level,swap}.mojo`,
`math/constants.mojo`, `utils/{_select,_visualizers}.mojo`, and one more — the
pass list is `formal_sweep.py`'s, and it is the number in its log rather than
restated here.

---

## 2. What moved since round 1, and it is the reason this doc exists

Round 1 §3 tabulated the blocking module per file. Re-measured on this tree:

| round 1's blocker | round 1's files here | this round |
|---|---|---|
| `collections/binary_heap.mojo` — one-field mutator with a return convention | 40 | **0** |
| `builtin/builtin_slice.mojo` — `StridedSlice___init__` rebinds its receiver | 11 | **0 as a wall** (it is 1 of the 6 files in the new row below, refused on its own construct) |
| `utils/_select.mojo` — the dylib exports nothing | 1 | **1**, unchanged |
| — | — | **`std/memory/alloc.mojo`'s bare `FormatStruct(writer, …)` / `dealloc(…)`, 6 of this slice's files and 123 of the corpus** |

**Both of round 1's walls are gone from this slice's report**, and neither was
fixed in this slice: `binary_heap.mojo`'s row emptied because
`formal18-export-gate`'s per-edge rule landed, and `builtin_slice.mojo`'s
because `formal16-7`'s Optional representation work landed. The consequence for
a reader is the important part: **the per-file cause table from round 1 is
stale, and every number in it has to be re-measured before it is quoted.** That
is what this table is.

The new top row is `bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
— a bare call to a name the defining module cannot export because the name is a
generic and the call spells no type argument. It is `formal19-1`'s claim and it
is **not** this slice's; §4 says what the six files here are doing.

---

## 3. The 14 in-file refusals, each against what is behind it

**The fourteenth is §5's** — `builtin/float_literal.mojo`, the one this round
worked on — so the table below is the thirteen that remain. **Six of the
fourteen are the bare-call row of §2**, and they are one feature, not six bugs:

| # | file | the construct | behind it, and whose it is |
|---|---|---|---|
| 1 | `bit/bit.mojo` | `is_negative(value)` — bare call to a template | `FORMAL_a_bare_call_to_a_template_…`, `formal19-1` |
| 2 | `builtin/_format_float.mojo` | `isnan(value)` | same |
| 3 | `builtin/builtin_slice.mojo` | `FormatStruct(writer, "Allocation")` | same |
| 4 | `math/uutils.mojo` | `align_up(x)` | same |
| 5 | `random/_rng.mojo` | `PhiloxRandom(seed)` | same |
| 6 | `utils/variant.mojo` | `FormatStruct(writer, …)` | same |
| 7 | `builtin/len.mojo` | a `...` body where instructions are needed | the body is `@unavailable`'d. Round 1 §4 measured that **giving it a body gains nothing**: the next refusal is `value.__len__()` on a string, `FORMAL_string_value_model` (`formal16-8`) |
| 8 | `builtin/none.mojo` | `writer.write_string("None")` on a `Some[Writer]` | deliberate and correct: a multi-field struct's receiver is a frame address, and lowering it as `write` would pass that address as `fd(2)`. Needs a `Writer` value model — `FORMAL_wide_receiver_by_reference` (`formal16-8`) |
| 9 | `builtin/type_aliases.mojo` | `comptime Never = __mlir_type.\`!kgen.never\`` | an MLIR TYPE bound to a module-level `comptime`. `FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops` (`formal19-4`) |
| 10 | `format/repr.mojo` | `value.write_repr_to(string)` on a type parameter | a generic body is never specialized, and behind it `return string^` returns a 3-field `String`. Written up in `FORMAL_sweep_work_map_2026-10-02_std-b.md` §6 |
| 11 | `math/polynomial.mojo` | `comptime num_coefficients = len(coefficients)` | `coefficients` is a comptime parameter, and on this path a comptime parameter is an ordinary leading ARGUMENT — so there is nothing to fold. `FORMAL_known_limits.md` §1.2 (monomorphisation) |
| 12 | `sys/arg.mojo` | `Span[StaticString, ImmStaticOrigin]()` — an explicit-parameter list naming a TYPE and a comptime VALUE | the same monomorphisation wall as 11, from the other side: the brackets are types and comptime values, neither of which is a word. **New in this slice** (`sys/` was out of round 1's scope) |
| 13 | `utils/_serialize.mojo` | `p.unsafe_load(off)` — a read at an OFFSET | round 1 §2.2 fixed the name; what is left is the POINTE's width, and the pointee is `Scalar[dtype]` with `dtype` a comptime parameter, so no width is established. Same wall as 11 |
| — | `builtin/float_literal.mojo` | `self.__int_literal__().__int__(…)` | **§5.** The receiver's type is in a `-> T` and the callee is in another module |

**Every one of the thirteen is a feature someone else's claim is already
written down against.** That is the finding of this round, and it is the reason
no in-file row is fixed here except §5's.

---

## 4. The 60 dependency refusals, by cause and by owner

`formal_sweep_causes.py` on the AFTER log, trimmed to the rows a reader needs:

| files | the blocking module | the cause | whose |
|---|---|---|---|
| **8** | `sys/_io.mojo` | a constants-only module: the dylib has no public functions | `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib` (`formal16-2`). The census says **0 of the 8 name anything it declares** |
| **7** | `math/constants.mojo` (as `std.math`'s) | the same shape, same doc | same. `math/constants.mojo` **passes as a sweep target and fails as a dependency** — worth knowing before anyone reads the pass list as a claim about the module |
| **4** | `collections/string/string_span.mojo` | `FormatStruct` (the bare-call row) | `formal19-1`; the module itself is in `formal20-std-collections-2`'s slice |
| **4** | `std/ffi` | `dealloc` | `formal19-1` |
| 3 each | `builtin/variadics`, `builtin/constrained`, `format/_utils`, `std/memory` | the same two callees | `formal19-1` |
| 2 each | `std/hashlib/hasher`, `std/traits`, `sys/.defines`, `builtin/device_passable` | the same | `formal19-1` |
| **1** | `utils/_select.mojo` | every declaration is private (`_select_register_value`), so the export trie is empty | the private-import row: **147 library files** across the stdlib, measured by round 1 §6. The export rule is `FORMAL_dylib_export_audit_adds_a_second_underscore` / `FORMAL_per_export_contracts` (`formal13-5`/`formal13-3`) |
| **1** | `time/time.mojo` | `CompilationTarget` — a module-level name of ANOTHER module, not exported as a word | `FORMAL_type_name_as_value` (`formal16-8`) |

**The largest dependency row in this slice (15 files) is two constants-only
modules, and both are inside this slice.** That is worth stating plainly
because it is the only place where a fix *in these eight directories* would
move files, and it is still not available: the feature is "let a module with
no public exports build as an empty library", which `formal16-2`'s doc names
as one half of a single feature owned by `FORMAL_module_state_no_storage`
(`formal19-4`).

---

## 5. What landed, and what it was worth

One commit, `26f0ee62`. **Worth 0 files in this slice, and the 85-file sweep is
the measurement** (`…-arm64-BEFORE.txt` vs `…-arm64-AFTER.txt`: 11 / 14 / 60
before, 11 / 14 / 60 after, and the file lists are identical).

`builtin/float_literal.mojo`'s `self.__int_literal__().__int__(…)` was refused
with **"What is missing is the receiver's TYPE: this path has no inference that
answers which struct does `self.__int_literal__()` hold?"** — and the type was
written in the source, in `__int_literal__`'s own `-> IntLiteral[…]`.
`model.receiver_struct` already had a CALL row that reads a declared return
type; nothing connected it to the lift, so a receiver whose type the source
STATES was treated as a receiver whose type nothing states.

The fix lifts `f().m(x)` when the callee's `-> T` names a one-field struct of
this unit, passing the receiver as the call itself (`IntLiteral_take(f(), x)`)
rather than binding a temporary — which is also why the refusal's old advice
("give the receiver a local of a declared struct type") was a workaround for a
gap in the compiler and not a property of the program. `visit` recurses into
the receiver first, because `model.rewrite_tree` does not descend into a
construct it has consumed and the receiver of a method call is usually another
method call.

**Why 0 files, measured rather than argued:** the one file in this slice with
that shape is `float_literal.mojo`, and `IntLiteral` is declared in
`std/builtin/int_literal.mojo`, which `float_literal.mojo` neither imports nor
compiles — so there is no callee in that unit to bind. The commit therefore
also **replaced that file's message with a true one**, which is the part worth
having on its own:

```
build: FloatLiteral___int__: `self.__int_literal__().__int__(…)` cannot be
lowered: `self.__int_literal__()` is a `IntLiteral`, and that IS established —
this is not a missing-type refusal. What this path cannot do is use it as the
receiver here, because this module declares no struct of that name. A method of
a struct another module declares is a symbol in THAT module's library, and this
unit neither imports it nor compiles it, so there is nothing here for the call
to bind — the receiver's type is written down and the CALLEE is what is
missing.
```

Byte-identical on arm64 and x86-64 (measured, §1). Six refusal sentences now
exist for "the type is known and it still is not a receiver" — a CONSTRUCTION
(`Box()` names its struct, but a one-word struct's frame is never built at an
argument position; measured: lifting it reads address 0 and answers 0), a
multi-field struct, a method the struct does not declare, an overloaded one, a
derived one, and a type this unit does not declare. Before this commit the
CONSTRUCTION case and this one got the SAME sentence, and for both of them it
was false.

**One cross-reference for whoever owns the construction case.**
`bugs/FORMAL_method_call_on_a_construction_is_not_rewritten.md` (`formal13-4`)
quotes the OLD sentence for `Box().get()` in its Status, twice, and says the
advice it gives is the shape that crashes. All three halves of that still hold —
the construct is still refused, for the same reason, by the same rule — but the
message it quotes no longer exists, and the new one names the REPRESENTATION
(`… because a CONSTRUCTION is not a value this path can pass as a receiver: the
struct is named, and a one-word struct's fields live in a frame that the
construction in an argument position never builds`) instead of asking the reader
for a type the source already states. That doc is not this round's to edit; this
paragraph is the note its next reader needs.

Verified: `python3 test_formal_run.py` **PASS=956 FAIL=0** and
`python3 test_formal_receiver_position.py` **PASS=37 FAIL=0**, each on BOTH
architectures — the first including three new CPython-pair rows for the lift
(a function's `-> T`, a method's `-> T`, and a two-hop chain so the recursion
is pinned at depth 2) and the second five new refusal rows for the guards.
`python3 test_refusal_taxonomy.py` 216/216.

---

## 6. What a worker should take from three rounds on this slice

Round 1 fixed two things for 0 files. This round fixed a third for 0 files.
**The reason is not that the fixes were small — it is that this slice's files
are behind other people's features, and the fix that moves a file here is
almost never a fix in these eight directories.** §2's table is the proof: both
of round 1's blockers were cleared by work in `formal/` for a module in
`std/collections` and a value model for `Optional`.

So the two things worth doing here are both cheap and neither is a fix:

1. **anything that makes the bare-call row land** (§2, `formal19-1`) moves 6
   files of this slice and 123 of the corpus in one commit. It is the single
   highest-leverage thing in this doc and it is not this slice's;
2. **`sys/` and `time/` are new to the map.** 17 files, one in-file refusal
   (`sys/arg.mojo`, §3 row 12), and the rest behind `sys/_io.mojo` (8) and
   `time/time.mojo` (1). Round 1 said nothing about them because they were not
   in its scope; that is the whole of what §1 and §3 add.

## 7. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib/std
python3 tools/formal_sweep.py -j 2 -t 120 $S/{builtin,math,bit,random,format,utils,sys,time}
python3 tools/formal_sweep.py -j 2 -t 120 --arch x86_64 $S/{builtin,math,bit,random,format,utils,sys,time}
python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep20-std-builtin-sys-time-arm64-AFTER.txt

# §5's file, both architectures, the message the commit changed
for a in arm64 x86_64; do
  python3 fire.py build --formal --no-prove --backend=$a -o .tmp/fl \
    $S/builtin/float_literal.mojo
done

# the tests that cover §5
python3 test_formal_run.py call_result_receiver_lifted_from_a_return_type \
  call_result_receiver_of_a_method_call call_result_receiver_chain_of_two_calls
python3 test_formal_receiver_position.py
```

Editing anything under `formal/`, the parser or `mojo/middle/` invalidates the
sweep CAS (`tools/formal_sweep.py`'s own bytes are in every key), so a
re-measurement of these numbers is a real rebuild of the slice.
