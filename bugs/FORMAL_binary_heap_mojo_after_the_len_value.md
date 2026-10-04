# `std/collections/binary_heap.mojo` builds nothing yet, and the 165 files behind it have TWO walls

**Status: §3 row 1 is FIXED (`List.clear`, both backends), and §3a row 0a's
CAUSE was already fixed — so the file's own verdict has moved two rows down the
table and the two corrections below are what a reader planning §3 needs. §2's
conclusion is UNCHANGED and re-measured: the row does not move, because wall
two is the export gate and it is untouched by any of this.** Re-measured on both
architectures:

```
build: self.clear() is a method call on a value, and this backend lowers only
append, close, write (on a file descriptor) and the string methods count,
endswith, find, lstrip, startswith — …            <- BEFORE row 1
build: …                                           <- now the NEXT row
```

Written on `work/formal12-binary-heap`, claim `sweep12:binary-heap`.

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
| 0a | `def clear(mut self)` → `self._data.clear()`, once `self._data` is rewritten to `self` | ~~`BinaryHeap_clear: self.clear is not a field of BinaryHeap`~~ | **The file's reported verdict as of 2026-10-03; its CAUSE fixed in §3a (`model.iter_nodes_with_parent` + `check_value_position_method_reads` skipping a callee), and with row 1 now closed the file's verdict has moved past this row entirely** |
| 1 | `self._data.clear()` | ~~`is a method call on a value, and this backend lowers only append, close, write … and the string methods count, endswith, find, lstrip, startswith`~~ | **FIXED 2026-10-03, §3b.** `List.clear` is `count = 0` — one store at offset 0 of the blob — and it is now in `model.BUILTIN_VALUE_METHODS` with a LIST-only kind guard. §3b corrects this row's own analysis: the receiver is typed after the collapse, and the collapse is correct |
| 2 | `self._data.unsafe_ptr()` (in `_heapify_up` and `_heapify_down`) | same method-call refusal | `unsafe_ptr` hands out the blob's base; with it come `unsafe_offset`, `unsafe_take_pointee` and `unsafe_write` (`(data_ptr.unsafe_offset(pos)).unsafe_write(...)`). That is a POINTER model — ownership, `^`, and what a borrow means — not four method entries |
| 3 | `self._data.append(val^)` (in `push`) | `list.append() is not lowered on the formal arm64 path: a list blob lives in the frame, so the room an append needs has to be known when the list is built. This one is not (the receiver is not a list literal)` | True and structural: the blob is carved out of the building function's frame, and the zero-operand `List[Self.T]()` reserves no room. **This is the one that interacts with §1's `capacity=` answer** — the reservation is dropped there, so appending into a reserved container is refused here rather than silently overrunning. Do not "fix" this by honouring `capacity` without a representation for it |
| 4 | `self._data.pop()` (in `pop`) | method-call refusal again | `List.pop` needs the count decremented and the element read out of the blob |
| 5 | `data_ptr[unsafe_offset=child]` (in `_heapify_down`) | `type-parameter subscript [...] is not supported on the formal arm64 path` | A subscript whose index is a KEYWORD (`unsafe_offset=`) on a pointer. Measured on its own: it is only reached once `unsafe_ptr()` lowers, so it is downstream of #2 rather than independent of it |
| 6 | `ref[self._data[0]] Self.T` (in `peek`), `swap(item, self._data[0])`, `element^`, `debug_assert[assert_mode="safe"](len(self) > 0, …)` | not reached | unmeasured — the build never got past #5. One of them is already known to build on its own: `debug_assert[assert_mode="safe"](1 > 0, "boom")` lowers on BOTH architectures, so the 85-file `debug_assert` row this file also sits in (`FORMAL_debug_assert_bracket_has_no_lowering`) is **not** on this file's critical path |

So: **six constructs, of which two (#0a, #2) are in other workers' write sets
and one (#5) has a doc.** #0 — `pop` — was the cheapest real step because it was
the file's reported verdict and a decision about the ABI rather than an emitter
exercise, and it is done (§0). **The next step is #0a**, which is a different
kind of thing: the one-word rewrite collapses a field access and a method call
onto one spelling, and two passes downstream cannot tell them apart.

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

Test: `test_formal_run.py`'s
`a_method_callee_through_a_collapsed_field_is_not_a_field_read`, in the group
that already pins the three `sole_field_call_refusal` spellings — and it is a
`refuse:` expectation whose words are the METHOD TABLE's, so the old message
fails it, which is the point.

## 3b. Row 1 is CLOSED, and BOTH of this section's reasons for it were wrong
(2026-10-03)

**`List.clear` lowers, on both backends, and the row's analysis above was wrong
twice — both times in the direction of "this needs a rewrite".** Recorded
because the next reader of §3a would otherwise act on it.

    struct Wrap:
        var _data: List[Int]
        def __init__(out self):
            self._data = [5, 6, 7]
        def clear(mut self):
            self._data.clear()
        def size(self) -> Int:
            return len(self._data)
    def main(k: Int) -> Int:
        var w = Wrap()
        printf("before %d", w.size())
        w.clear()
        printf(" after %d", w.size())
        return 0

    arm64    before 3 after 0, exit 0
    x86-64   before 3 after 0, exit 0
    CPython  before 3 after 0

1. **The receiver IS typed after the collapse, so the "lift it to a call on
   `_data`" repair is not needed.** Measured, not read: at the point
   `model.value_method_refusal` is asked, `_method_recv_kind(self)` answers
   **`list`**. The identity took the field away and
   `ValueKinds._declared_kind_for`'s one-word-receiver row hands the question to
   `model.one_word_receiver_kind`, which reads the field's DECLARED type, and
   `struct_field_kind` opens its constructor door because `__init__` stores a
   container display. So §3a's "`_data` is a NAME whose type this path does not
   infer" is false on this tree, and the refusal's own text agrees — it says
   "the receiver is a name **on this path**", not "a name this path cannot
   type": the receiver being a NAME was the complaint, and a name is what a list
   blob lives in.
2. **The collapse is CORRECT, so the "decline to collapse a field whose struct
   declares a method of the chain's name" repair would have been a regression.**
   `self._data` IS `self` — that is the identity this path is built on — and
   `Wrap` declares no FIELD named `clear`, so the rule as §3a states it would
   fire on every method call through a one-word struct's sole field. Measured
   while checking this: making the rewrite skip a chain interior of a callee (so
   `self._data.clear()` survives intact) does NOT reach the value-method table
   at all; it reaches `_callee_symbol`, which emits `BL self._data.clear` and
   the build fails on an unbound symbol. The spelling is nicer and the answer is
   worse, which is the trade this path keeps making.

**So the whole of row 1 is one store.** `model.BUILTIN_VALUE_METHODS` gains
`"clear": "list_clear"` — the blob's COUNT is its first word, so emptying a list
is `count = 0` — and each backend's `_emit_list_clear` emits the receiver, parks
the base, and stores zero at offset 0. No capacity check, which is the whole
difference from `append`: an append needs room a compile-time scan cannot find
for a blob it did not see built, and a clear needs no room.

**The guard is a KIND and it fires.** `model.BUILTIN_VALUE_METHOD_LIST_KINDS` is
the one that needs a kind rather than a fact an emitter has, and
`_shape_guarded_refusal` asks it: the same `clear()` on a field whose value the
constructor takes from a PARAMETER is refused, because the receiver's kind is
then the model's default for an unannotated word (`int`) and a zero written at
offset 0 of an arbitrary word is a store into whatever address that word holds.
Measured on both architectures, identical words:

    build: self.clear() lowers to one store of zero at offset 0 of its receiver,
    and that offset is a container's COUNT — so the store empties a list and
    writes into whatever address anything else holds. self.clear's receiver is
    'int', and this path will not read an arbitrary word as a blob's header.

Tests: `test_formal_x86_64_parity.py`'s
`list_clear_through_a_one_word_structs_sole_field` (both backends against the
CPython oracle, with the numbers) and its
`clear_of_a_receiver_this_image_cannot_call_a_list_refused_identically` (both
backends, the guard); plus `test_formal_run.py`'s
`a_method_callee_through_a_collapsed_field_is_not_a_field_read`, whose
`refuse:` expectation named the METHOD TABLE's words and is now a build with
`size=0 after=0` — it keeps the zero-operand `List[Int]()` constructor, which is
the OTHER of `ctor_establishes_slot`'s two doors.

**What is left in this file, in order: rows 2–6 of the table below**, and row 2
(`self._data.unsafe_ptr()`) is still the one that needs a POINTER model rather
than four method entries — `unsafe_ptr`, `unsafe_offset`, `unsafe_take_pointee`
and `unsafe_write` together. Rows 3 and 4 (`append` / `pop` on a field whose
blob the constructor did not build from a literal) are the capacity and count
questions §3a already answers "do not fix by honouring `capacity=`", and row 5
is downstream of row 2. **None of them is in this claim's reach and none of them
moves the row** — §2's wall two is the export gate, measured again on this tree
and unchanged.

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

# the tests that cover §1
python3 test_formal_run.py            # 752/752
python3 test_formal_value_model.py    #  46/46
python3 test_new_syntax_parsing.py    #  91/91
```

**Note for the next reader: editing anything under `formal/`, the parser, or
`mojo/middle/` invalidates the sweep CAS**, so a re-measurement of these numbers
is a real rebuild of the slice (`tools/formal_sweep.py`'s own bytes are in every
key).