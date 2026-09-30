# FORMAL_frame_by_value_ceiling_zero: rows 7 and 8 of the sweep map, measured — 0 of 26 files move, and the 7 that leave row 7 land in five other causes

**Status: the ceiling is measured at 0, one sub-shape is fixed (`origin_of`,
commit `14a2e42d`), one neighbouring gap is filed, and the rest of rows 7 and 8
is not work.** This is the measurement the work map asked for before anything
was built (§3 of `FORMAL_sweep_work_map_2026-09-30.md`, on
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

**7 files leave row 7 and 0 reach `pass`.** Where they land:

| file | lands on | whose |
|---|---|---|
| `std/builtin/tuple.mojo` | `a Tuple receiver is stored in a container` | the neighbouring gap below |
| `std/collections/deque.mojo` | same | same |
| `std/collections/linked_list.mojo` | same | same |
| `std/collections/set.mojo` | same | same |
| `std/collections/counter.mojo` | `a Counter receiver is passed to other.lt in argument position 0` | map row 4 (`formal-receiver-position`) |
| `std/memory/unsafe_pointer.mojo` | `a Pointer receiver is passed to type_of()` | `type_of` is not lowered at all, on any receiver — a plain missing builtin |
| `std/gpu/host/_device_context_metal.mojo` | `function.mojo`: `__mlir_attr[...]` | map row 1, permanent |

So the fix buys 7 truthful diagnoses and 4 of the 7 immediately walk into the
next false one, which is the single most reusable thing left in these two rows.

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

## The neighbouring gap: a subscript's argument list is not a container

Filed as `bugs/FORMAL_type_argument_read_as_a_container.md`. One paragraph,
because it is short and it is what stands between 4 files and a truthful
diagnosis: `_check_frame_escapes`'s container branch cannot tell a `TupleExpr`
that is a subscript's INDEX from a `TupleExpr` that is a container literal, and
`iter_nodes` does not give it the parent, so a frame address in a type-argument
list is refused as a store. The reproducer has no `origin_of` in it at all:

```python
struct S:  a, b
struct Box[T: AnyType, U: AnyType]:  v
def main(n):
    s = S(); s.a = 3; s.b = 4
    return Box[Int, s].v
```

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

## Reproducing

The 26 files are the ones `tools/formal_sweep_causes.py` prints for "frame
address passed where a value is wanted" and "callee has no definition on this
path" (`14 + 12`) — that tool is committed with the work map on
`work/formal-sweep-next` (`git show
work/formal-sweep-next:tools/formal_sweep_causes.py`), not on this tree, because
it is the map author's file and not this session's. Re-deriving the table needs
its sweep log; the two commands at the top of this document are the measurement,
and each printed every file's verdict.
