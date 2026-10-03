# `std/collections/binary_heap.mojo` builds nothing yet, and the 165 files behind it have TWO walls

**Status: the refusal this file was filed under is FIXED. The row it blocks is
NOT, and the reason is not the one the sweep map records.** Both facts are
measured on both architectures; §2 is the measurement that matters most, because
it says the export gate — which every plan for this row has treated as the
*second* problem — is reached again as soon as the first one is out of the way,
so no amount of codegen work on this file moves any of the 165.

Written on `work/formal12-binary-heap`, claim `sweep12:binary-heap`.

---

## 1. What landed, and what it was

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

## 3. What is left in `binary_heap.mojo`, in the order the build reaches it

Both architectures, same five, same order, same reasons. Reproduce with the
chain probe (below) or by reading the refusals in order from
`fire.py build --formal --no-prove --backend=arm64 -o /dev/null
…/binary_heap.mojo`.

(Six rows, and #0 is where the file's verdict comes from today: it is a
PREP-time refusal, so it preempts every emitter refusal below it.)

| # | construct | refusal | why it is a project, not a patch |
|---|---|---|---|
| 0 | `def pop(mut self) -> Self.T` | `BinaryHeap.pop() both changes its receiver and returns a value` (`mutating_receiver_return_refusal`) | A one-field struct's mutating method hands its receiver back in the result register; there is no second word for the popped element. `receiver_writeback_name`'s own message names the two repairs (split the method, or make it a reader). This one is a PREP-time refusal, so it preempts every emitter refusal below — it is the file's reported verdict today |
| 0a | `def clear(mut self)` → `self._data.clear()`, once `self._data` is rewritten to `self` | `BinaryHeap_clear: self.clear is not a field of BinaryHeap` (`check_value_position_method_reads`) | The one-word rewrite turns `self._data.clear()` into `self.clear()`, and the value-position check cannot tell a call's callee from a value read — its own docstring calls that "a limitation, not a choice". Either give the walk a parent (a second traversal of its own) or do not rewrite a field whose own struct has a method of that name. **Touches the one-word rewrite, which `formal12-singles-a`/`formal12-singles-b` hold — not claimed here** |
| 1 | `self._data.clear()` | `is a method call on a value, and this backend lowers only append, close, write … and the string methods count, endswith, find, lstrip, startswith` | `List.clear` is `count = 0` — one store. Trivial to lower and honest; it is here because the emitter's method table has no entry for it |
| 2 | `self._data.unsafe_ptr()` (in `_heapify_up` and `_heapify_down`) | same method-call refusal | `unsafe_ptr` hands out the blob's base; with it come `unsafe_offset`, `unsafe_take_pointee` and `unsafe_write` (`(data_ptr.unsafe_offset(pos)).unsafe_write(...)`). That is a POINTER model — ownership, `^`, and what a borrow means — not four method entries |
| 3 | `self._data.append(val^)` (in `push`) | `list.append() is not lowered on the formal arm64 path: a list blob lives in the frame, so the room an append needs has to be known when the list is built. This one is not (the receiver is not a list literal)` | True and structural: the blob is carved out of the building function's frame, and the zero-operand `List[Self.T]()` reserves no room. **This is the one that interacts with §1's `capacity=` answer** — the reservation is dropped there, so appending into a reserved container is refused here rather than silently overrunning. Do not "fix" this by honouring `capacity` without a representation for it |
| 4 | `self._data.pop()` (in `pop`) | method-call refusal again | `List.pop` needs the count decremented and the element read out of the blob |
| 5 | `data_ptr[unsafe_offset=child]` (in `_heapify_down`) | `type-parameter subscript [...] is not supported on the formal arm64 path` | A subscript whose index is a KEYWORD (`unsafe_offset=`) on a pointer. Measured on its own: it is only reached once `unsafe_ptr()` lowers, so it is downstream of #2 rather than independent of it |
| 6 | `ref[self._data[0]] Self.T` (in `peek`), `swap(item, self._data[0])`, `element^`, `debug_assert[assert_mode="safe"](len(self) > 0, …)` | not reached | unmeasured — the build never got past #5. One of them is already known to build on its own: `debug_assert[assert_mode="safe"](1 > 0, "boom")` lowers on BOTH architectures, so the 85-file `debug_assert` row this file also sits in (`bugs/FORMAL_debug_assert_bracket_has_no_lowering.md`) is **not** on this file's critical path |

So: **six constructs, of which two (#0a, #2) are in other workers' write sets
and one (#5) has a doc.** The cheapest real step is #0 — `pop` — because it is
the file's reported verdict and it is a decision about the ABI (does a one-field
mutator get a second return word, or does the method split?), not an emitter
exercise.

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