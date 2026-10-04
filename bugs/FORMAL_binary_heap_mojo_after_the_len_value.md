# `std/collections/binary_heap.mojo` builds nothing yet, and the 165 files behind it have TWO walls

**Status: §3 rows 0, 0a and 1 are FIXED; rows 2-5 are not, and the row's
conclusion is unchanged.** Row 1 (`List.clear`) landed 2026-10-04 on
`work/formal21-3` and **it was the one-store change §3's table said it was**,
which corrects §3a's reasoning below — that section concluded the receiver made
it something else, and the measurement says the receiver is fine. The file's
reported verdict is now row **2** (`self.unsafe_ptr()`, the pointer model),
measured on both architectures, and **the 165 files behind it still do not
move**, for the reason §2 gives and has always given: wall two is the export
gate, and wall three behind it is `tile.mojo`, and neither is about how well
this file lowers.

Written on `work/formal12-binary-heap`, claim `sweep12:binary-heap`.

The refusal that stood where row 1 now stands, measured on both architectures
after row 0 landed and before row 1 did:

```
build: self.clear() is a method call on a value, and this backend lowers only
append, close, write (on a file descriptor) and the string methods count,
endswith, find, lstrip, startswith — the receiver is a name on this path, and
'clear' is not one of those methods of those receivers, so adding it to either
table would be a guess about what it means on 'list'.
```

and the one that stands there now, from the same command on both architectures:

```
build: self.unsafe_ptr() is a method call on a value, and this backend lowers
only append, clear, close, write (on a file descriptor) and the string methods
count, endswith, find, lstrip, startswith — the receiver is a name on this
path, and 'unsafe_ptr' is not one of those methods of those receivers …
```

---

## 0. What landed, and what it was (2026-10-03)

The decision was **not** a second return register. The shape this file is filed
under is `print(heap.pop())` — a mutator call whose RESULT is used — and a second
register only moves the problem: the receiver still has to land somewhere the
caller's next read can see, and the return register is the one place a one-word
value can be. So the receiver is not returned at all. **A mutating method of a
one-field struct receives the ADDRESS of the caller's own storage and writes the
receiver back through it on every exit**, and the return register carries only
the declared return value. That is the convention the multi-field path has always
used (its receiver IS a frame address) and the one `doc/ABI.md` already
documents for the compiled backend (`R Struct_method (Struct *self, args…)`).

Three shapes were dropping the write-back when it travelled in the return
register, each measured on BOTH architectures before the change, and each built,
ran, and printed the value the caller had:

| was | measured | is |
|---|---|---|
| a mutator that also returns a value | `mutating_receiver_return_refusal` — **this file's verdict for months** | builds |
| a mutator call in a VALUE position | `sink(c.bump(5))` printed 15 and left `c` at 10 | builds |
| a mutator call whose callee is in ANOTHER MODULE | `from cellmod import Cell; c.bump(5)` printed `c=10` | builds (`c=15`) |

Three refusals SURVIVE, each a real boundary: a mutator whose result is used and
which declares no return type (there is nothing to put in the expression
position); a mutator call and a read of the same receiver in one argument list
(`f(c.pop(), c.field)` — this path evaluates arguments before making the call, so
the read would see the old word); and a mutator that also returns a FRAME (two
hidden-word conventions with no measured order between them).

What is left in this file is §3's table with row 0 struck; row 0a is the verdict
now, and it is **not** in this worker's claim.

## 1. What landed before this, and what it was

The sweep (`bugs/sweeps/sweep-arm-7.txt:85`) filed this file as:

```
CODEGEN: …/std/collections/binary_heap.mojo  (build: len(self._data) — this
slot's DECLARED type is 'List[Self.T]' … What is missing is the VALUE. `S()`
does not run `__init__` on this path (premise a struct that declares no
__init__ has no body to run), so a fresh instance's slot holds the class-level
default, and a field with no class-level default is a word of zeros: the count
word would be read from address 0. …)
```

and `bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3.1 measured 164 of the 165
files in that row as closure behind it. That refusal is gone. It was **three**
defects, none of them the refusal's own text:

| was | is | commit |
|---|---|---|
| `struct BinaryHeap[T: Copyable & Comparable & Deinitable]` produced a real `VarDecl` field named `T`, because `_parse_struct_params_as_fields` recognised a comptime bound only when the annotation was a SINGLE bare trait name. `BinaryHeap` has one field (`_data`) and measured two, so `struct_is_one_field` said no and a one-word value's receiver became a FRAME ADDRESS | `_struct_param_is_bound`: a `&` at bracket depth zero cannot occur in a data type, so an annotation carrying one is a constraint on the type parameter. **14 stdlib structs** were affected | `48c480b1` |
| an `__init__` body that reads a TYPE name was refused as reading a local of the body (`a read of 'List', 'Self' in the right-hand side`), so no container-backed field could be given its value by a constructor at all | `_init_type_position_names`, scoped to the callee of a construction whose base is a type constructor | `b3b13256` |
| `struct_field_kind` had two doors — a literal class-level default and a nested framed struct — and a container has neither, because a container default is refused by name (`struct_frame_representable`: "the default is not a literal") | `ctor_establishes_slot`: a one-field struct's constructors put a materialized blob in the field. One-field only, because premise (B1) is about a blob whose lifetime is the assigning function's while the slot's is the object's, and a multi-field struct's frame is exactly such an object | `b3b13256` |
| …and one store kept that door shut for THIS file: `__init__(out self, *, capacity: Int)` is `self._data = List[Self.T](capacity=capacity)`, and `blob_constructor_with_operands_refusal` refused it | `blob_constructor_lowering`: a `capacity=` operand is a reservation rather than content, so the container it builds is empty | `4e3af109` |

**MEASURED, on both architectures: `binary_heap.mojo` no longer refuses on
`len(self._data)` anywhere in it.** Before, four of its functions did
(`__len__`, `__init__`, `pop`, `peek`). After, none does.

## 2. The row does not move, and the export gate is the wall behind it

**Re-measured 2026-10-03, after §0: this section's conclusion is UNCHANGED and
its evidence is stale in one word.** The sweep family label it quotes —
`one-field mutator has no return convention` — is gone; what the same ten files
report now is whatever `binary_heap.mojo` reaches next, which is row #0a. The
numbers below were measured with row 0 standing and are kept because the
CONCLUSION they support ("the codegen half is not the wall; the export gate is")
is the part a reader needs, and it does not depend on which construct is
refused. **The reason the row does not move is wall two, and wall two is
untouched by any amount of codegen work on this file.**

Ten of the 165 files, re-measured on **both** architectures with
`python3 tools/formal_sweep.py -j 2 -t 120 <10 files>` (and `--arch x86_64`),
which agree exactly:

```
[arm64]  10 files: PASS=0 not-pass=10
  codegen/dependency by family: binary_heap.mojo: one-field mutator has no return convention x10
codegen coverage: 0/10 = 0.0%
[x86_64] 10 files: PASS=0 not-pass=10
  codegen/dependency by family: binary_heap.mojo: one-field mutator has no return convention x10
codegen coverage: 0/10 = 0.0%
```

(the arm64 sweep lock is machine-wide and shared with every other worker, so
one arch can refuse to start while another is sweeping — that is the runner's
`--allow-concurrent` flag, not a finding.)

**0 of 10 move**, which is the same answer `bugs/FORMAL_known_limits.md` §1.2
recorded on 2026-09-30 for a smaller sample ("Giving `binary_heap.mojo` a
concrete public symbol … moves **0 of 35**"), now re-measured with the codegen
half of the chain closed. The terminal cause advanced from the export gate to
the next construct in `binary_heap.mojo`'s own body, which is exactly what
§1.2 predicted and the reason it called the number "the refusal advances one
level".

**And past every codegen refusal in the file, the export gate is what fires.**
Built `binary_heap.mojo` as a module dylib with each refusal bypassed in turn —
`receiver_writeback_name` resolved the way the language suggests rather than
skipped, `check_value_position_method_reads` disabled, one `CodegenError` per
emitted function logged instead of raised:

```
REFUSED: FormalBuildError formal dylib has no public functions:
binary_heap.mojo exports nothing under doc/ABI.md's rules: it declares only
the generic struct template(s) BinaryHeap, and a parametric type has no single
boundary layout either.
```

which is **the message the sweep itself recorded**, one hour of codegen work
earlier. So the row has two independent walls and codegen was only the first:

1. `binary_heap.mojo` does not lower (§3);
2. `binary_heap.mojo` exports nothing, and 162 of the 163 files that name it
   name nothing it declares — they are refused because
   `std/collections/__init__.mojo` re-exports it.

`formal/build.py`'s `_export_entries` on this file is `[]`, with
`reflect.export_exclusions` reporting `{'BinaryHeap': 'generic-template'}`.
`_method_exports` WOULD publish `BinaryHeap_push` and its five siblings
(`_formal_exports`'s own comment says a struct method "is part of the module's
API even when the module has no free functions at all"), and the gate at
`compile_formal_dylib` consults only `_export_entries`, so the two disagree
about one module's API.

**The gate is right and the disagreement is not the bug.** `doc/ABI.md` §Generics
is explicit that a generic is not a single boundary symbol and that each
*instantiation* is, and `no_public_api_reason`'s docstring says publishing a
template under its base name "would be wrong, not conservative: one trie entry
cannot be two instantiations". `bugs/FORMAL_known_limits.md` §1.2 costs that
project at (a) a monomorphizer, (b) a mangling function, (c) CAS keying by
`(template-id, type args, comptime params)`, (d) a naming decision for
`ReflectedFn.display_name` — weeks. **Do not start it for this row**: it moves
0 files until §3 is closed, and §3 is where the next unit of work is.

The one thing a reader should take from this: **a plan that reads §3 of the
sweep map as "one file has to lower first, then 164 files move" is wrong about
the second half.** `binary_heap.mojo` lowering is necessary and not sufficient.

## 2b. What is BEHIND the export gate, measured 2026-10-03: it is `tile.mojo`, and the row is claimed

`bugs/FORMAL_sweep_work_map_2026-10-03_b9.md` §3 records the state of the row
after `formal/monomorph.py` landed: **163 files, "module exports no public
functions", 162 of them naming nothing `binary_heap.mojo` declares.** §2 above
says the gate is wall two and that fixing wall one is necessary and not
sufficient. This section is the other half of that sentence, measured rather
than argued: **what the row's files hit if wall two stops being a wall.**

The probe lifts wall two the only way it can be lifted without answering the
ABI question — it treats a module nobody binds a concrete name from as "no
library needed", which is the decision `formal/imports.py::build_module_dylib`
would have to make per edge. It does that by returning `None` for a module whose
library the export gate refuses, printing each skip with the module and the
consumer that asked for it, so the number below is a count of refusals lifted and
not an assertion that one was:

```python
# .tmp/probe_export_gate.py, scratch — see the map's §6
orig = I.build_module_dylib
def patched(module_name, source_path, *a, **kw):
    try:
        return orig(module_name, source_path, *a, **kw)
    except B.FormalBuildError as e:
        if "has no public functions" not in str(e):
            raise
        print(f"[probe] SKIPPED {module_name} for consumer {kw.get('_parent')}")
        return None
```

Ten of the 163, sampled across the stdlib (`bugs/sweeps/sweep-arm-9.txt`, arm64;
the x86-64 arm's log is identical for these paths). **Every one of the ten
skips exactly one module, and every one moves off this row:**

```
[probe] SKIPPED .binary_heap (binary_heap.mojo) for consumer std.collections
build: <file> imports '<X>', which cannot be built either: tile.mojo:
workgroup_function[…](…) calls a name this unit does not compile, so the
brackets cannot be bound …
```

**8 of 10 on `tile.mojo`'s bracketed specialization, 2 on
`builtin_slice.mojo`'s Optional unwrap.** So:

* **fixing this row moves 0 of the 163.** That is the same answer §1.2 recorded
  on 2026-09-30 for a smaller sample and the same answer §2 records for wall
  one, now with wall two lifted as well — the row has two walls and the second
  one hides a third row that is 8-in-10 where the 163 are.
* **`tile.mojo`'s row reads 4 files today only because `binary_heap.mojo`
  masks it.** Its doc is `bugs/FORMAL_stdlib_tile_row_is_a_specialization_
  through_a_function_value.md` and it is **claimed** (`formal16-7`), so the
  number belongs to that claim and not to this one.
* **The decision this row still needs is therefore a decision and not a
  project**, and it is small enough to state: *does the importing module bind
  any CONCRETE name of the dependency?* If not, no library is needed and the
  edge can be dropped. `monomorph.py` already answers exactly that question one
  level in, for instantiations. **It is not a light worker's row** for two
  reasons that are about the tree and not about the size: it is
  `formal/imports.py`'s closure walk, and it reverses a pinned decision —
  `test_formal_imports.py::test_a_module_with_no_boundary_symbol_is_refused`
  exists to FAIL if a template-only module ever builds, and its docstring says
  why ("the only way to make it build is to publish the template under its base
  name, and that is a run-time wrong answer rather than a build error").
  Whoever takes it has to answer that test rather than route around it.

## 3. What is left in `binary_heap.mojo`, in the order the build reaches it

Both architectures, same five, same order, same reasons. Reproduce with the
chain probe (below) or by reading the refusals in order from
`fire.py build --formal --no-prove --backend=arm64 -o /dev/null
…/binary_heap.mojo`.

(Six rows, and #0 is where the file's verdict comes from today: it is a
PREP-time refusal, so it preempts every emitter refusal below it.)

| # | construct | refusal | why it is a project, not a patch |
|---|---|---|---|
| 0 | `def pop(mut self) -> Self.T` | ~~`BinaryHeap.pop() both changes its receiver and returns a value`~~ | **FIXED 2026-10-03**, §0. The receiver is handed over by reference, so the return register carries the popped element and `pop` lowers. This was a PREP-time refusal, so while it stood it preempted every emitter refusal below it — which is why removing it changed this file's reported verdict rather than adding a row |
| 0a | `def clear(mut self)` → `self._data.clear()`, once `self._data` is rewritten to `self` | `BinaryHeap_clear: self.clear is not a field of BinaryHeap` (`check_value_position_method_reads`) | **The file's reported verdict as of 2026-10-03**, measured on both architectures with row 0 gone. The one-word rewrite turns `self._data.clear()` into `self.clear()`, and the value-position check cannot tell a call's callee from a value read — its own docstring calls that "a limitation, not a choice". Either give the walk a parent (a second traversal of its own) or do not rewrite a field whose own struct has a method of that name. **Touches the one-word rewrite, which `formal12-singles-a`/`formal12-singles-b` hold — not claimed here** |
| 1 | `self._data.clear()` | ~~`is a method call on a value, and this backend lowers only append, close, write … and the string methods`~~ | **FIXED 2026-10-04**, §3b. It WAS `count = 0` — one store — and the receiver was not the obstacle §3a said it was: measured, `len(self._data)` through the one-word collapse has always read the blob's count, so the store lands where the read did. `List.clear` is now in `model.BUILTIN_VALUE_METHODS` and both backends emit it |
| 2 | `self._data.unsafe_ptr()` (in `_heapify_up` and `_heapify_down`) | same method-call refusal, and now the file's reported verdict on both architectures | `unsafe_ptr` hands out the blob's base; with it come `unsafe_offset`, `unsafe_take_pointee` and `unsafe_write` (`(data_ptr.unsafe_offset(pos)).unsafe_write(...)`). That is a POINTER model — ownership, `^`, and what a borrow means — not four method entries |
| 3 | `self._data.append(val^)` (in `push`) | `list.append() is not lowered on the formal arm64 path: a list blob lives in the frame, so the room an append needs has to be known when the list is built. This one is not (the receiver is not a list literal)` | True and structural: the blob is carved out of the building function's frame, and the zero-operand `List[Self.T]()` reserves no room. **This is the one that interacts with §1's `capacity=` answer** — the reservation is dropped there, so appending into a reserved container is refused here rather than silently overrunning. Do not "fix" this by honouring `capacity` without a representation for it |
| 4 | `self._data.pop()` (in `pop`) | method-call refusal again | `List.pop` needs the count decremented and the element read out of the blob |
| 5 | `data_ptr[unsafe_offset=child]` (in `_heapify_down`) | `type-parameter subscript [...] is not supported on the formal arm64 path` | A subscript whose index is a KEYWORD (`unsafe_offset=`) on a pointer. Measured on its own: it is only reached once `unsafe_ptr()` lowers, so it is downstream of #2 rather than independent of it |
| 6 | `ref[self._data[0]] Self.T` (in `peek`), `swap(item, self._data[0])`, `element^`, `debug_assert[assert_mode="safe"](len(self) > 0, …)` | not reached | unmeasured — the build never got past #5. One of them is already known to build on its own: `debug_assert[assert_mode="safe"](1 > 0, "boom")` lowers on BOTH architectures, so the 85-file `debug_assert` row this file also sits in (`bugs/FORMAL_debug_assert_bracket_has_no_lowering.md`) is **not** on this file's critical path |

So: **six constructs, of which #0, #0a and #1 are FIXED, #2 is a pointer model,
and one (#5) has a doc.** #0 — `pop` — was the cheapest real step because it was
the file's reported verdict and a decision about the ABI rather than an emitter
exercise, and it is done (§0). #0a was a WALK (§3a) and #1 was an emitter entry
(§3b). **The next step is #2**, and it is a project rather than a patch for the
reason its own column gives: `unsafe_ptr` hands out the blob's base, and what
comes with it is a pointer model — ownership, `^`, and what a borrow means.

**And still 0 of the 165 files move**, which is the measurement §2 and §2b give
and the one this branch re-confirms rather than re-argues: wall two is the export
gate (`binary_heap.mojo` exports nothing under `doc/ABI.md`'s rules) and behind
it is `tile.mojo`'s bracketed specialization. **A file that lowers and a file that
is reachable are two different facts, and only the second one is worth 165
files.**

## 3a. Row 0a's CAUSE is fixed, and what it makes visible is row 1 (2026-10-03)

Row 0a's table entry offered two repairs: "either give the walk a parent (a
second traversal of its own) or do not rewrite a field whose own struct has a
method of that name".  **The first is done**, and the second is not needed:
`formal/model.py::iter_nodes_with_parent` is the walk with the parent beside
each node, `model.is_call_callee` is the one reader of "is this a call's
`func`", and `check_value_position_method_reads` now skips a `MemberExpr` that
is a callee.  Its own docstring had called the blindness "a limitation, not a
choice" and argued it harmless because "a call cannot store into the name
either" — true of the NAME, but the check does not ask whether the name is a
field, it asks whether `recv.name` is a field READ, and in callee position
there is no read at all.

Minimal reproduction, which does **not** depend on row 0 and so is measurable
on `master` today:

```
struct Wrap:
    var _data: List[Int]
    def __init__(out self):
        self._data = List[Int]()
    def clear(mut self):
        self._data.clear()
def main(n: Int) -> Int:
    var w = Wrap()
    w.clear()
    return 0
```

`master`, both architectures:

```
build: Wrap_clear: self.clear is not a field of Wrap — clear is one of its
METHODS, and nothing in Wrap stores into an attribute of that name … Call it
(`self.clear(...)`), which is a receiver and a call and lowers
```

— a METHOD CALL reported as a field read, with a message telling the reader to
add a call the source already has.  With the fix:

```
build: self.clear() is a method call on a value, and this backend lowers only
append, close, write … and the string methods … 'clear' is not one of those
methods of those receivers
```

**which is row 1**, and that is the whole of what this buys: the file's verdict
moves from a mis-diagnosis to the real gap, one row down.  It does NOT build,
and it is worth saying why, because the table's row 1 ("`List.clear` is
`count = 0` — one store.  Trivial to lower and honest") is wrong about the
receiver it would have to lower: by the time the emitter sees `self.clear()`
the one-word rewrite has collapsed `_data` into the receiver, so the receiver is
a NAME whose type this path does not infer, and the refusal says exactly that
("the receiver is a name on this path").  Adding `clear` to the method table
would emit a store against the wrong word.

So row 1 is **not** the one-store change the table says it is: either
`_rewrite_one_word_field_method_calls` has to lift `self._data.clear()` to a
call on `_data` before the collapse (the same lift `SOLE_FIELD_CALLEE_CASES`'s
transitive row already gets, because the chain `self._data.clear` is not a
prefix of the map's `_data`), or the one-word rewrite has to decline to collapse
a field whose own struct declares a method of the chain's name.  The first is
the same shape as a fix that has already landed and is named in
`bugs/FORMAL_ast_bridge_...`-adjacent work; the second is the option this file
listed and is now the only one left.  **Neither is in this claim's reach**: both
are the one-word rewrite, and the row is not reachable on this tree anyway
because row 0 (`pop`) still stands — `build --formal` on this file still
reports `mutating_receiver_return_refusal`, which is being fixed on
`work/formal15-mutator-return-abi`.

### The paragraph above is WRONG about the receiver, and §3b is the correction

Read it as a hypothesis rather than as a conclusion: "Adding `clear` to the
method table would emit a store against the wrong word."  The next session did
not have to take either repair, because the premise is false — measured, not
argued, in §3b.  It is kept here rather than deleted because a doc that removes
its own wrong reasoning teaches a reader that reasoning is not worth checking.

Test: `test_formal_run.py`'s
`a_method_callee_through_a_collapsed_field_is_not_a_field_read`, in the group
that already pins the three `sole_field_call_refusal` spellings — and it is a
`refuse:` expectation whose words are the METHOD TABLE's, so the old message
fails it, which is the point.

## 3b. Row 1 is FIXED, and §3a's premise about the receiver was false (2026-10-04)

`List.clear` is in `model.BUILTIN_VALUE_METHODS` as `list_clear`, both backends
emit it, and the file's verdict moved to row 2.  **Four instructions of lowering
and one guard, and the guard is the whole of the safety argument.**

**What the lowering is.**  The blob is `[count:i64][elem0]…` and a list value IS
its address, so `clear` is a store of 0 at offset 0 of the receiver — the word
`len` of the same receiver reads.  Nothing else: no capacity (an append has to
know there is room, an empty needs none), no element type, no traversal, and 0 as
the answer, which is this model's `None`.  arm64 emits `mov x1, x0` / `movz x2,
#0` / `str x2, [x1]` / `movz x0, #0`; x86-64 the same four moves in its own
registers.

**Why §3a's "the receiver is a NAME whose type this path does not infer" is
false, measured.**  Three probes, all on both architectures, all of which answer
the question §3a left open:

| probe | result | what it settles |
|---|---|---|
| `len(self._data)` through the one-word collapse, in a `class Box` with `_data = [4,5,6]` | `3` (CPython: `3`) | the collapse already hands the emitter a word that IS the blob base — `len` reads its offset 0, and that is the same word `clear` would store to |
| `self._data[1]` through the same collapse | `5` (CPython: `5`) | and a SUBSCRIPT through it, so it is not one call the walk happens to help |
| `self._text.lstrip()` with a `String` field | refused as "classified as `int` rather than a string" | the collapse does not make EVERY method name lowerable, and the classifier catches the ones whose receiver is not a blob |

So the one-word rewrite needed neither of §3a's repairs: the receiver it hands
the emitter is the right word, and `_method_recv_kind` — the same reader
`len_operand_lowering` uses — classifies it `list`.  **The refusal's own last
words were the evidence and nobody read them as evidence**: "adding it to either
table would be a guess about what it means on `list`" states the receiver's kind
in the message, and the kind is exactly the question the guard needs.

**The guard, and why it is POSITIVE evidence rather than a capacity lookup.**
`append` needs no guard of this kind because its own (`_list_caps_by_name`) refuses
whenever the receiver is not a list literal it can size — the absence of a
reservation.  `clear` has no such accident to fall on, and a name in
`BUILTIN_VALUE_METHODS` with no kind guard would zero the first eight bytes of
ANY word and leave the program running: a silent wrong answer, which is the one
thing this backend does not emit.  So `_emit_list_clear` asks
`is_list_kind(self._method_recv_kind(e))` and refuses with
`model.list_clear_refusal` — a message shared by both architectures, because two
machines naming one limit differently is the defect this tree keeps paying for.

**The residual, stated rather than left to be found.**  The guard trusts the
classifier, and a receiver the classifier calls `list` is a receiver whose
declared field type or binding said so.  A `clear` that is really a STRUCT
method of a one-word struct whose single field happens to be classified as a
list would be lowered as the list's; the rows that would have to catch that are
the lift's (`_rewrite_method_calls` and `_lift_one_word_field_method` resolve a
struct method by name first, and the bare-receiver arm of the lift reads
`one_word`/`bound`), so the emitter only ever sees a name the name-only paths
declined.  What is NOT covered is a receiver whose struct is declared in another
module AND annotated `List[...]` at the call site — which is a program whose
source says "a list" and calls `clear` on it, so the lowering is right anyway.

**A DICT passes the same guard, and that is measured rather than accidental.**
`is_list_kind` admits a dict kind, because a dict on this path is a counted blob
too — `len_operand_lowering` reads its count from the same offset 0 — so zeroing
that word empties it exactly as CPython's `dict.clear` does.  Measured on both
architectures: `{"a": 1, "b": 2}` reports 2, clears to 0, and a **second dict
built after the clear still reports 1**, which is the number that makes the store
a store rather than a coincidence.  So the guard's evidence is "a counted blob"
and not the word "list", and `test_formal_run.py::list_clear_empties_a_dict_blob`
is the row that says so; a guard keyed on the NAME would have refused a program
CPython answers correctly.

**Four rows of test, in `test_formal_run.py`, and one of them is a row that
CHANGED KIND.**

* `list_clear_empties_a_list_literal` (new, in `CASES`) — a local list,
  `before=3@@after=0`.  The BEFORE number is what makes the AFTER one mean
  anything: a `clear` that emitted nothing would still print `after=0`.
* `a_method_callee_through_a_collapsed_field_empties_the_field` — **this one
  existed before and was a `refuse:` row**: §3a's last paragraph predicted it
  would fail, for the reason it gave ("it is a `refuse:` expectation whose words
  are the METHOD TABLE's, so the old message fails it, which is the point"), and
  it did.  It moved from `SOLE_FIELD_CALLEE_REFUSALS` to `SOLE_FIELD_CALLEE_CASES`
  rather than being deleted, because it is the shape that group is about and a
  group whose central case vanishes stops testing it.  Its assertion is now
  CPython's own answer on both architectures: `before=3@@after=0`, which says
  the collapse hands the emitter the right word rather than merely surviving.
* `one_word_field_method_clear_on_a_scalar_field_is_still_refused` (new, beside
  the two other one-word-field method refusals) — the boundary: `self.n.clear()`
  where `n: Int` is REFUSED, by the guard's own sentence, because the name IS in
  the table and the receiver is what is wrong.  The refusal says so, which the
  generic "not one of those methods" would not: a reader told to add a name to a
  table that already has it goes looking in the wrong place.

**One message moved, and three tests moved with it.**  The refusal enumerates the
lowered names ("lowers only append, clear, close, write"), so the string three
tests and one tool keyed on changed:

* `tools/formal_sweep_causes.py`'s "method call on a value receiver" row was keyed
  on that enumeration, so `clear` joining the table would have taken every file in
  the row back to `other refusal` **silently**.  It is re-pointed at the clause
  that states the fact — "is not one of those methods of those receivers" — for
  the reason `bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §5.1 gives: a marker
  keyed on a list a change to the list invalidates is a row that reads as a cause
  blocking nothing.
* `test_refusal_taxonomy.py`'s sample for that row now carries the message's TAIL,
  because the marker now lives in the tail and a sample cut before it would fall
  through to the frame-address cause one entry above.
* `test_formal_sweep.py`'s `CHAIN_MSG_2` is a real needle and carries the new
  list; `test_formal_external_call.py` and `test_formal_run.py` quote the old one
  in prose, and prose that names a list nobody maintains is how the next reader
  goes looking for a string lowering that was never the point.

## 4. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH

# the reported refusal, before the three fixes: `git show 48c480b1^` into a
# scratch worktree and build from there.  (`-o` needs a real path; this
# compiler will not write /dev/null.)
python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/bh.out \
  ../new-modular/Mojo/stdlib/std/collections/binary_heap.mojo

# and now: five constructs further on, identically on both architectures
for a in arm64 x86_64; do
  python3 fire.py build --formal --no-prove --backend=$a -o .tmp/bh.$a \
    ../new-modular/Mojo/stdlib/std/collections/binary_heap.mojo
done

# the row: ten of the 165, both arches (they agree exactly)
python3 tools/formal_sweep.py -j 2 -t 120            <10 files>
python3 tools/formal_sweep.py -j 2 -t 120 --arch x86_64 <10 files>
python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-7.txt

# row 1's three rows, and the two architectures they run on
python3 test_formal_run.py list_clear_empties_a_list_literal \
    list_clear_through_a_one_word_struct_field \
    one_word_field_method_clear_on_a_scalar_field_is_still_refused

# the message the guard prints, and the refusal-taxonomy marker that moved
python3 test_formal_sweep.py           # the pre-existing dyld-probe red
python3 test_refusal_taxonomy.py       # 226/226

# the tests that cover §1
python3 test_formal_run.py            # 752/752
python3 test_formal_value_model.py    #  46/46
python3 test_new_syntax_parsing.py    #  91/91
```

**Note for the next reader: editing anything under `formal/`, the parser, or
`mojo/middle/` invalidates the sweep CAS**, so a re-measurement of these numbers
is a real rebuild of the slice (`tools/formal_sweep.py`'s own bytes are in every
key).