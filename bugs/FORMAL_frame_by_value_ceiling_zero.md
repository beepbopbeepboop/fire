# FORMAL_frame_by_value_ceiling_zero: rows 7 and 8 of the sweep map, measured — 0 of 26 files move, and the 7 that leave row 7 land in five other causes

**Status: the ceiling is measured at 0, three sub-shapes are fixed
(`origin_of`, commit `14a2e42d`; the subscript argument list, commit
`30e5e2e9`, which is the neighbouring gap this document used to file and
which has been closed; and `type_of`, the `missing builtin` the landing table
below ends on, which is now named as the builtin it is rather than as a
function this file failed to declare — see "The one diagnosis left in this
table" at the end), one remaining limit is filed, and the rest of rows 7
and 8 is not work.** RE-CHECKED 2026-10-01, and the ceiling still holds: of the
seven row-7 files this document's landing table ends with, every one is now
refused by a DEPENDENCY before its own body is reached — `tuple`,
`linked_list` and `set` on `builtin_slice.mojo`, `deque` on
`binary_heap.mojo`, `unsafe_pointer` and `base64` on
`formal dylib has no …` — so **neither row 7's nor row 8's sentence is any of
their terminal causes any more.** 0 reach `pass`, as measured. Re-checked on the
seven this document names by name, not on all 26; the other 19 were row-8 or
row-3/1 files whose recorded terminal causes are documented permanent limits, and
the 26 are re-derivable with the `tools/formal_sweep_causes.py` the map's author
committed on `work/formal-sweep-next` rather than on this tree. This is the
measurement the work map asked for before
anything was built (§3 of `FORMAL_sweep_work_map_2026-09-30.md`, on
`work/formal-sweep-next`), carried out on the 26 files those two rows name. The
map's warning was that "files blocked" is an UPPER BOUND and that rows 2 and 3
were 68 files of not-work; this is the same measurement for rows 7 and 8, and
the answer is the same.

Rows 7 and 8 as the map has them:

| row | cause | files | in-file | one example |
|---|---|---|---|---|
| 7 | frame address passed where a value is wanted | 14 | 14 | `std/builtin/tuple.mojo` |
| 8 | callee has no definition on this path | 12 | 12 | `std/base64/base64.mojo` |

## What was run

The terminal file of each row, then the 26 files, on this tree
(`53f89ae7` + `formal/`: `origin_of`):

```
$ python3 tools/memslot.py --gb 8 --label sweep-26 -- \
      python3 tools/formal_sweep.py -j 4 -t 200 <the 26 files>
[arm64] 26 files: PASS=0 not-pass=26
  <- codegen  26
  codegen by family: frame address passed where a value is wanted x14,
                     callee has no definition on this path x12
```

The map's own numbers reproduce exactly, so the 26 are still the 26 (and the two
exemplars are still refused with the same sentences — `origin_of` on
`std/builtin/tuple.mojo`, `_b64encode` on `std/base64/base64.mojo`).

**The ceiling was measured by lifting the refusals, not by reading the code.**
Two temporary guards in `formal/build.py` (a `FORMAL_HACK_ROWS7_8` env var on
the value-only branch and on the not-in-this-image branch of
`_check_frame_escapes`) turned both rows off for the same 26 files:

```
[arm64] 26 files: PASS=0 not-pass=26
  <- codegen 13, codegen/dependency 10, not-answerable/host-import 3
```

**0 of 26 reach `pass`.** Every one moves to a different refusal, and 13 of the
26 land in-file, so the next thing wrong with each of those 13 is a fact about
that file and not about these two rows.

## Where the 26 land, with both rows lifted

| files | new terminal cause | whose it is |
|---|---|---|
| 4 | `builtin_slice.mojo`: `Slice___eq__`: `'other.start' is a field access through 'other'` | map row 3, and its own doc already measures that row's ceiling at 0 |
| 2 | `binary_heap.mojo`: `'List' has no home: the module-level symbol table is empty` | map row 2 (fixed on the map's own branch, ceiling 0) |
| 2 | `_assembly.mojo`: `inlined_assembly` | map row 6, a **documented true limit** (`FORMAL_known_limits.md` §1.1, `inlined_assembly`) |
| 2 | `function.mojo` / `dtype.mojo`: `__mlir_attr` / `__mlir_op` | map row 1, a **documented true limit** (`FORMAL_known_limits.md` §2, the MLIR attribute templates) — 107 files, the largest row in the table, and not work |
| 3 | a CPython host import (`ast`, `copy`, `re`) | out of reach for this backend whatever its codegen says |
| 6 | `a X receiver is passed to other.m(…) in argument position 0` — a method call on a VALUE receiver, dispatched by name | map row 4, `formal-receiver-position`'s claim |
| 4 | `F() takes a X receiver at argument k — here, and something that is not a frame address there. One parameter, two kinds of value` | `_check_holder_agreements`, and its own message carries the SIGSEGV that makes it a refusal rather than a note |
| 2 | `self.<f> hands the word in the slot to G.m(), whose receiver is the ADDRESS of a frame — so the slot would have to hold a frame address` | map row 12 ("a field of a nested frame that the struct does not declare") |
| 1 | `a X receiver is returned from a method of X, which did not create the frame` | map row 5 |
| 1 | a SUBSCRIPT's argument list read as a container store | **the neighbouring gap filed from this session**, see below |

Nothing in that table is rows 7 or 8. **Rows 7 and 8 are 26 files of not-work**,
for the same reason rows 2 and 3 were: they are one refusal in front of a stack
of two to four others, and in 10 of the 26 the next thing is a documented
permanent limit.

## Row 8 decomposed: 12 files, and 5 of them are behind row 1

The two rows are not one cause each, and row 8's 12 files sort into four shapes
that have nothing in common:

| shape | files | what it is |
|---|---|---|
| `__get_mvalue_as_litref(self)` | 5 | **the only caller of the call is `__mlir_op.lit.ownership.mark_initialized(…)`** — i.e. a row 1 construct, a documented permanent limit. The refusal names a missing callee; the real blocker is the dialect operation it is an argument to. |
| a callee this unit does not compile | 4 | `_b64encode` (another module's function), `discover_closures` (a host-side function of this compiler's own build), `ElementFn` (a closure type parameter), `getattr` / `hasattr` (builtins this model does not lower at all). Each is unbound before the receiver's type is a question, and the refusal says so. |
| a wrong argument for a callee that does exist | 2 | `debug_assert(Interval)` — a struct as a condition; `iter(List)` — a method on a result. |
| `origin_of` | 1 of row 7's 7, see below | the one false diagnosis in either row. |

So row 8 is 11 correct refusals and 1 that is not, and 5 of the 11 are blocked
behind a limit the map already says is permanent.

## The one false diagnosis, and it is fixed

Row 7's 14 files, by callee:

| callee | files | verdict |
|---|---|---|
| `origin_of` | 7 | **A FALSE DIAGNOSIS, and now fixed** (`14a2e42d`). The sentence said the callee "wants the object itself … so what would arrive is the address `origin_of()` would then dereference as one". `origin_of` is a compile-time intrinsic with no body on this path: there is no call to emit and nothing dereferences the word. `myinterpreter.py`, this project's reference for the language, defines it as `lambda x, *args, **kwargs: x`, so the identity is an oracle in the tree rather than a judgement call. |
| `String` / `StringSlice` | 4 | correct. The word becomes a `char *` that every `%s` and every string method dereferences, and a `String(...)` overload set of its own is what those 4 files need first. |
| `list`, `isinstance`, `fcntl` | 3 | correct, and each is refused for its own reason (a container/scalar reading of a frame; a C entry point wanting a `char *` or a descriptor). |

Re-sweeping the 26 with the fix in place:

```
[arm64] 26 files: PASS=0 not-pass=26
  <- codegen 25, codegen/dependency 1
  codegen by family: callee has no definition on this path x13,
                     frame address passed where a value is wanted x7,
                     receiver stored in a container x4,
                     receiver passed as an argument x1
```

**7 files leave row 7 and 0 reach `pass`.** Where they land, measured again
after the second fix (`30e5e2e9`, the subscript argument list below) — the
right-hand column is the state on this tree, and the middle one is the state
between the two fixes, which is what made the second fix worth landing:

| file | after `origin_of` (`14a2e42d`) | after the argument list (`30e5e2e9`) | whose |
|---|---|---|---|
| `std/builtin/tuple.mojo` | `a Tuple receiver is stored in a container` | `a Tuple receiver is passed to type_of()` | map row 8, `formal-callee-no-def` |
| `std/collections/deque.mojo` | same | `Deque__physical_index() takes a Deque receiver at argument 0 … one parameter, two kinds of value` | `_check_holder_agreements` |
| `std/collections/linked_list.mojo` | same | dependency: `builtin_slice.mojo`: `'other.start' is a field access through 'other'` | map row 3 |
| `std/collections/set.mojo` | same | `Set_issubset() takes a Set receiver at argument 1 … one parameter, two kinds of value` | `_check_holder_agreements` |
| `std/collections/counter.mojo` | `a Counter receiver is passed to other.lt in argument position 0` | **unchanged** | map row 4, `formal-receiver-position` |
| `std/memory/unsafe_pointer.mojo` | `a Pointer receiver is passed to type_of()` | **unchanged** | `type_of` is a missing builtin, on any receiver |
| `std/gpu/host/_device_context_metal.mojo` | dependency: `function.mojo`: `__mlir_attr[...]` | **unchanged** | map row 1, permanent |

The before/after of the whole seven, one sweep each, same tree, the change
reversed with `git apply -R` for the first column and re-applied for the
second:

```
$ python3 tools/memslot.py --gb 8 --label sweep-7-before -- \
      python3 tools/formal_sweep.py -j 4 -t 300 <the 7 files>
[arm64] 7 files: PASS=0 not-pass=7
  codegen by family: receiver stored in a container x4,
                     callee has no definition on this path x1,
                     receiver passed as an argument x1
  codegen/dependency by family: function.mojo: MLIR construct x1

$ … the same command with 30e5e2e9 in place …
[arm64] 7 files: PASS=0 not-pass=7
  codegen by family: callee has no definition on this path x2,
                     self has two kinds of value across call sites x2,
                     receiver passed as an argument x1
  codegen/dependency by family: builtin_slice.mojo: other refusal x1,
                                function.mojo: MLIR construct x1
```

**4 files move and 0 reach `pass`,** which is the ceiling this document has
measured from the start. What moved is the SENTENCE: the four were refused for
storing a frame address in a container that does not exist, and each is now
refused for something that is true of it — a callee with no definition, a
parameter that is a frame address at one call site and a copy at another, and a
module it imports. `linked_list.mojo` also changes CLASS, from an in-file
`codegen` finding to `codegen/dependency`, which is the sweep saying the file's
own refusal is no longer the one in front of it — not that its body is clean,
which nothing here establishes.

## The fix's verdict footprint is exactly those 7 files

Worth stating, because a rewrite in `formal/` is a wide change to make on trust.
59 stdlib files call `origin_of`, and the question is how many of the other 52
could have had it as their reported refusal. Answer: none of them could have,
and the reason is structural rather than lucky — the only place this construct
could ever be a file's terminal cause is the value-only sentence in
`_check_frame_escapes`'s argument loop, and on the 2026-09-30 sweep log
`origin_of` appears **7 times in 628 files' verdicts, and all 7 are that
sentence**:

```
$ grep -c origin_of .tmp/sweep_20260930.log        # lines, i.e. files
7
$ grep origin_of .tmp/sweep_20260930.log | grep -vc "lowered as an operation on a VALUE"
0
```

7 files and 21 textual occurrences of the name, every one of them in that one
sentence.

The other 52 were already refused earlier — by a host import, a dependency, or a
refusal the walk reaches before the argument loop — and none of those moves. So
the change cannot move a file outside these 7, and a full re-sweep after it
should find exactly the 7 verdicts the table above lists, with 0 reaching
`pass`. (That re-sweep is a large run and was not done here; it belongs to the
gate.)

`30e5e2e9` has the same property and the same argument, in the other
direction: it can only change a file whose verdict is one of two sentences —
`is stored in a container` from the escape check's container branch, or `is a
subscript whose index is a tuple` from `model.multi_index_kind` — and both of
those are refusals before and after, so no file that built before it does. The
measured before/after above is the check: 4 of 7 files, and the 3 that did not
move were refused by a callee table, a parameter position and an import chain,
none of which this change reads.

## The neighbouring gap, closed: a subscript's argument list is not a container

`_check_frame_escapes`'s container branch could not tell a `TupleExpr` that is a
subscript's INDEX from a `TupleExpr` that is a container literal, and
`iter_nodes` does not give it the parent. So `Pointer[Deque[T],
origin_of(self)]` was refused as a store — a sentence about a lifetime the
program does not have, which is the false diagnosis that costs most, because it
sends the reader after an escape that is not there. The reproducer has no
`origin_of` in it at all:

```python
struct S:  a, b
struct Box[T: AnyType, U: AnyType]:  v
def main(n):
    s = S(); s.a = 3; s.b = 4
    return Box[Int, s].v
```

Fixed by `30e5e2e9`. `model.subscript_index_is_a_comptime_parameter_list` is the
one answer to "is this bracket list a comptime parameter list", and both
consumers ask it: the escape check skips those indices, and `multi_index_kind`
answers `MULTI_INDEX_COMPTIME_PARAMS` for the same bases. Both classes are
refusals before and after, so nothing is let through by the skip — the
sentence that replaced the false one is
`Box[Int, s] is a compile-time explicit-parameter list on a generic, not a
subscript: the brackets name types and comptime values, none of which is a
runtime word`, which is true.

Two things in the original doc's plan were wrong or unfinished, and both are
recorded here rather than left in the commit message:

* **the undecidable case is not the one it named.**
  `IteratorType[origin_of(self)]` has a **single** index, so the container
  branch never saw a bracket list to mistake and there was nothing to decide.
  What is undecidable is the DOTTED base, and it is still undecidable — see the
  remaining limit below.
* **`Box[Int, s]` still does not build,** and should not: a type application is
  a construct this backend does not lower at all (it has no parameter binding),
  and the honest answer for it is the model's own refusal. The original doc's
  "what to measure" asked for a build, which would have meant monomorphization
  — `FORMAL_known_limits.md` §1.1, `doc/ABI.md` §Generics — and not a
  narrowing of a check.

## The limit that remains, filed

`bugs/FORMAL_dotted_base_bracket_list_is_not_classified.md`: a subscript over a
base this unit cannot classify — `Self.IteratorType[origin_of(self)]`,
`external_call["setenv", c_int]` — is not asked the question, and keeps
today's refusal. Deciding it needs the imported module's declarations, which is
`formal/imports.py`'s, and the other half of it
(`FORMAL_known_limits.md` §6.2, 55 files) belongs to `formal-extcall-tuple`.

## What a planner should take from this

* **Rank by "files that would reach `pass`", not by "files blocked".** Rows 2, 3,
  7 and 8 are 100 files of not-work between them, and all four were believed to
  be work until measured. Rows 2 and 3 were measured by the map's author; rows 7
  and 8 here.
* **A false diagnosis is worth fixing even at a measured ceiling of 0**, and the
  two things that make it landable are that the answer has an ORACLE in the tree
  (`myinterpreter.py`) and that the fix needs no new lowering — `origin_of(x)` is
  `x`, so a build-pass rewrite is the whole of it and no emitter is taught
  anything.
* **The next refusal is the deliverable when the ceiling is 0.** The table of
  where 26 files land is worth more than the 26 findings, and it is re-derivable
  in about four minutes with the guards described at the top.
* **A false diagnosis in the NEXT refusal is worth one round of its own,** and
  the reason the second fix could be written at all is that the first fix put
  four named files in front of it. Measuring the landing is not just a report;
  it is how the next defect becomes findable.

## Reproducing

The 26 files are the ones `tools/formal_sweep_causes.py` prints for "frame
address passed where a value is wanted" and "callee has no definition on this
path" (`14 + 12`) — that tool is committed with the work map on
`work/formal-sweep-next` (`git show
work/formal-sweep-next:tools/formal_sweep_causes.py`), not on this tree, because
it is the map author's file and not this session's. Re-deriving the table needs
its sweep log; the two commands at the top of this document are the measurement,
and each printed every file's verdict.

## The one diagnosis left in this table, fixed (2026-10-02)

The landing table's last row is `std/memory/unsafe_pointer.mojo`, and its
"whose" column says: "`type_of` is a missing builtin, on any receiver". The
sentence the sweep recorded for it is `a Pointer receiver is passed to
type_of()`, which is `frame_undefined_callee_refusal`'s LAST arm — the one that
says *"this module defines no FUNCTION of that name — a method declared here is
reached as `recv.type_of(…)` … — and no `from … import …` in it binds the name
either"*.

For `type_of` that sentence is not true, and it is false in the direction that
costs the reader most: it sends them to look for a missing `def` and a missing
import, and `type_of` is a Python **builtin** — a name the language provides,
so there is nothing to declare and nothing to import. Reproduced and measured
on this tree (two fields, so the receiver is a frame address and the argument
loop is reached at all; a one-field struct's receiver IS its field, so nothing
is a frame there and the bind audit answers instead):

```
$ python3 fire.py build --formal --no-prove -o tof.aout tof.mojo     # type_of(self)
build: a P receiver is passed to type_of(), which is a name with no definition
in hand in this image: this module defines no FUNCTION of that name …
```

`formal/model.py` now has `UNIMPLEMENTED_BUILTINS` — `{name: why there is no
answer here}` — as the sixth arm of that function, beside
`COMPTIME_REFLECTION_INTRINSICS` and for the same reason (a name that is not a
function of this image's making, so "this file declares no function of that
name" cannot be the reason). `type_of` is on it on this document's
measurement; `getattr`, `setattr`, `hasattr` and `delattr` are on it because
`bugs/FORMAL_frame_receiver_handoff.md` records them reaching the same branch
and says what naming them needs ("a table of what the backend DOES implement").
One table, and it is the place to add to.

Two things deliberately unchanged:

* **The refusal, not the verdict.** A frame address handed to any of these is
  unsound whichever way you read it — none of them has a compiled body to hand
  an address to — so this changes a diagnostic and nothing else.
* **The opening clause.** Every arm opens with "which is a name with no
  definition in hand", and two taxonomies key on that exact substring
  (`tools/formal_sweep.py`'s `_FRAME_ESCAPES` and
  `tools/formal_sweep_causes.py`'s `callee has no definition on this path`). An
  arm that reworded the opening would move every file it names out of the
  family they are counted in, into whichever family matches next, with no test
  failing. Measured after the split that introduced the other arms: 41 files,
  all 41 still classified by both tools.

Pinned both ways in `test_formal_run.py`'s `BYREF_REFUSALS`:
`byref_refuse_type_of_names_the_builtin` and
`byref_refuse_getattr_names_the_builtin`, one per family the table carries,
each asserted on BOTH backends (a `refuse:` case refuses identically on arm64
and x86-64), beside the two neighbouring arms they must not be confused with —
`byref_refuse_invisible_callee` for a name that really could be declared here,
and `byref_refuse_reflection_intrinsic` for a compiler intrinsic.
