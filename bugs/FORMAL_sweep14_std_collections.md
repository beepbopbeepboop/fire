# FORMAL_sweep14_std_collections: `std/collections`, `std/memory` and `std/algorithm` on both architectures

**RE-MEASURED 2026-10-05 (`work/formal29-5`), and THREE OF THE SIX WALLS HAVE
MOVED — which is the whole content of this document, refreshed.** Each wall was
built directly (`tools/formal_sweep.py -j 1 -t 120 <file>` on the stdlib
checkout at `../new-modular`, one build each), and the terminal cause of three of
the four largest rows is no longer what §3 names:

| §3's wall | files in this slice | what it says NOW | measured |
|---|---:|---|---|
| `binary_heap.mojo`'s `pop()` | **25** | **`self.unsafe_ptr()` is a method call on a value** — the mutator-return refusal is GONE, and the file's terminal cause is a `Pointer` method | `CODEGEN`, arm64 |
| `builtin_slice.mojo`'s `self = other` | **13** | **`FormatStruct` is imported from `std.format._utils`, which does not export it** — the doc's export rule, on a different name | `CODEGEN`, arm64 |
| `tile.mojo`'s `workgroup_function[…](…)` | **4** (+2 in `format_int.mojo`) | **`the body reads 'tile_size_list', its *-parameter, and this path has no variadic ABI`** | `CODEGEN`, arm64 |
| `type_dict.mojo`'s parameter binding | 1 | unchanged — still `Self._index` reads a `comptime` class attribute whose value is `Self.keys.try_index(key)` | `CODEGEN`, arm64 |

**AND ONE WALL NOW STANDS IN FRONT OF BOTH OF THE BIGGEST ONES.** Every file
measured above that is not yet refused in its own body stops at the same
sentence — `` `FormatStruct` is called, and it is imported from
`std.format._utils`, so the call has to bind a symbol `std.format._utils`
exports. That module does not export it `` — and `std/sys/info.mojo`, which
this project has measured six times over for a different reason
(`bugs/FORMAL_target_query_evaluator.md`), now reports it too, where it used to
report `binary_heap`'s `pop()`. **So the export rule is the largest single wall
in this area, ahead of both rows §6 called items 1 and 2, and it is one missing
export in one module rather than 38 files of anything.** Whether
`std/format/_utils.mojo` can export it is a one-line question this session did
not ask, and it is the first thing a planner should measure: it is the wall
`FORMAL_stdlib_module_names_are_not_classified` and the `-77` files behind it
both sit behind.

**Everything below is the 2026-10-04 measurement and is kept as it was**,
because it is the record of what the row was and the three rows above are what
it is now; §6's ordering is stale in the same way §3's table is, and §6 says so.

**53 files, and the two architectures are the same sweep again: every file has
the same class on arm64 and on x86-64, and 3 of 53 build.** The 46 files refused
in a module they import are behind **six** module walls, and **25 of the 46 are
one line of `std/collections/__init__.mojo`** — the `binary_heap` re-export —
which is a fact about this slice worth having in one number.

Claim `sweep14:std-collections` on `work/formal14-std-collections`, measured on
`master` at `17ddeaec` plus this branch's two commits.

---

## 1. The run

```sh
export PATH=/opt/homebrew/bin:$PATH
for d in collections memory algorithm; do
  python3 tools/memslot.py --gb 8 --label sw-arm-$d -- \
    python3 tools/formal_sweep.py -j 3 -t 120 ../new-modular/Mojo/stdlib/std/$d
done
python3 tools/memslot.py --gb 8 --label sw-x86 -- \
  python3 tools/formal_sweep.py -j 3 -t 120 --arch x86_64 \
    ../new-modular/Mojo/stdlib/std/{collections,memory,algorithm}
```

`--stdlib-subtrees collections,memory,algorithm` does **not** find these: the
subtrees are looked up directly under the stdlib root, so the spellings that work
are `std/collections,std/memory,std/algorithm` or explicit paths. The paths above
are what ran. Both arches at `-t 120`, `-j 3`, peak **0.3 GB** across up to 6
processes against an 8 GB reservation, no memory breach, no `tool` row.

**Both sweeps were SIGTERMed partway through** (`memcap: interrupted by signal
15`), which the runner handles: results are printed as each file is classified,
so the classified lines survive and the remainder was finished by re-running the
unclassified files. Every number below is over **all 53** on **both** arches —
`.tmp/` in the worktree holds the four logs this table was computed from, and
the arithmetic is `formal_sweep.py`'s own class prefixes plus each run's summary
line, which the runner checks sums to its file count. A partial log's counts
would be readable as a scope, so the per-arch completeness is stated rather than
implied.

## 2. The classes, both arches, identical

| class | arm64 | x86-64 |
|---|---|---|
| **pass** | **3** | **3** |
| **codegen** (a refusal IN the file) | **4** | **4** |
| codegen/dependency (refused in a module it imports) | 46 | 46 |
| not-answerable / backend-crash / tool | 0 | 0 |
| files | 53 | 53 |

| directory | pass | codegen | codegen/dependency |
|---|---|---|---|
| `std/collections` (33) | 3 | 2 | 28 |
| `std/memory` (12) | 0 | 0 | 12 |
| `std/algorithm` (8) | 0 | 2 | 6 |

**The 3 passes are the three constants-only modules**, and they are the same
three on both arches:

```
collections/string/_grapheme_break_lookups.mojo    (580 lines, 0 imports)
collections/string/_unicode_lookups.mojo           (8 constants, 0 imports)
collections/string/_parsing_numbers/__init__.mojo  (12 lines, 0 imports)
```

Which is the one structural fact about this slice worth stating early: **a module
that declares no function and no type builds**, as a program. Read on its own
that is a pass; read as an IMPORT it is a refusal (§4.5). A stdlib module is
imported, so the second reading is the one that costs anything.

## 3. The six walls behind the 46, and who owns each

Each row is the module the build walk reaches first, read off the printed line's
own chain (`build: <file> imports '<mod>', which cannot be built either: …`).
Identical on both arches.

| files | the refusing module | its refusal | owner |
|---|---|---|---|
| **25** | `std/collections/binary_heap.mojo` | `BinaryHeap.pop()` both changes its receiver and returns a value — `formal/model.py`'s `receiver_writeback_name` | `FORMAL_binary_heap_mojo_after_the_len_value.md`, and the export rule behind it is `FORMAL_dylib_export_loops_and_frame_bounds` (`formal13-3`) |
| **13** | `std/builtin/builtin_slice.mojo` | `self is assigned other in StridedSlice___init__()` | `FORMAL_builtin_slice_optional_field_is_a_frame_holder` (`formal13-3`) |
| 4 | `std/algorithm/backend/tile.mojo` | `workgroup_function[…](…)` — a bracketed specialization this unit does not compile | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value` (`formal13-6`) |
| 2 | `std/format/format_int.mojo` | the same bracketed-specialization rule, on `b[…](…)` | the same rule; the stdlib row is named in the b7 map §3 |
| 1 | `std/collections/string/_unicode_lookups.mojo` | a module that declares no function and no type cannot be a dylib | **unowned** — §4.5 |
| 1 | `std/algorithm/backend/cpu/map.mojo` | a call through a function VALUE | **unowned** — §4.6 |

**Every row above is claimed or measured-here-to-be-closure**, which is the
finding rather than an omission, and it is the same conclusion
`FORMAL_sweep_work_map_2026-10-02_b7.md` §3.1 reached over 668 files: a file's
terminal cause is the FIRST refusal its walk reaches, so this table is an upper
bound on what each wall costs and a lower bound on what is left underneath.

**The `binary_heap` row has moved since the b7 map and the direction matters.**
b7 §3 read `binary_heap.mojo: … formal dylib has no public functions: … it
declares only the generic struct template(s) BinaryHeap`. That is GONE: the
export gate is no longer this file's verdict, and the terminal cause has advanced
to the file's own `pop()`. So the 25 rows here are one step further along than
the map says, and `FORMAL_binary_heap_mojo_after_the_len_value.md` §3 row 0 —
"a decision about the ABI (does a one-field mutator get a second return word, or
does the method split?)" — is now the whole of what stands between this slice and
25 files. It is not this claim's row and it was not touched.

## 4. The four in-file refusals, and what happened to each

The task's line is "take every file that is a refusal IN the file (not closure,
not host-import)". There are four. Two are excluded by the task (the
`binary_heap` and `tile` rows, other workers own them); the other two are this
branch's two commits.

### 4.1 `algorithm/backend/cpu/map.mojo` — a call through a function VALUE

```mojo
def map(size: Int, func: Some[def(Int) -> None]):
    for i in range(size):
        func(i)
```

`func` is a parameter, and a formal value is one 64-bit word with a home in a
register, a spill slot, a receiver's frame or a folded module constant. A
function value needs a code address; a closure needs an environment, which is a
box this target has no allocator for. **Already refused correctly, and already
was**: the refusal's own text records that this used to be *emitted* as a branch
against a symbol literally named `func`, so the image was written and then the
loader refused it. Nothing here is a defect; the row is a value-model project
(function values), one file, and the remedy the message names — `apply(size,
kind: Int)` with one arm per operation — is a source change to the stdlib, which
no repository worktree can make. Left as it is.

### 4.2 `collections/type_dict.mojo` — a class-level binding that reads a struct PARAMETER. FIXED (the refusal), and the wall is filed

```mojo
struct TypeDict[T: Equatable & Movable, Trait: type_of(AnyType), //,
                keys: List[T], *values: Trait](TrivialRegisterPassable):
    comptime length = len(Self.values)
    comptime _index[key: Self.T] = Self.keys.try_index(key)
    comptime get[key: Self.T] = Self.values[Self._index[key].or_else(...)]
```

Was refused by the sentence about a value a `comptime` binding cannot compute,
whose repair is "write the value at the use site (a literal, or an assignment
the compiler can see)". **That repair cannot be carried out**: what `_index` reads
is `keys`, a PARAMETER, and the use site supplies it as an argument
(`TypeDict[Int, AnyType, [1,2,3], Int, String, Float64]`) — a value, not a
literal, and nothing in the class body to move. Same for `length`, which reads a
VARIADIC parameter whose arity is not knowable without the instantiation.

`d62016d6` gives the shape its own refusal naming the real premise (parameters
are not bound; `doc/ABI.md` §Generics + no monomorphizer) instead of the
un-carriable repair. **The wall itself is a project and is filed**:
`the variadic bracket arity and the `len(<display>)` fold.md`, with the family's
size.

This file also has a second wall behind the first — `TypeDict` is a generic
template, so past the comptime value it reaches the same export gate
`binary_heap.mojo` reached and no longer does. **0 files move**, and this is the
honest report: both of this branch's commits turned a false refusal into a true
one, and a true refusal is still a refusal.

### 4.3 `collections/binary_heap.mojo` — excluded (other workers own it)

`BinaryHeap.pop()` both changes its receiver and returns a value. See §3.

### 4.4 `algorithm/backend/tile.mojo` — excluded (other workers own it)

`workgroup_function[…](…)` calls a name this unit does not compile. See §3.

## 5. Two rows no doc owns, measured

### 5.1 `_unicode_lookups.mojo`: a module that exports nothing cannot be a dylib

`collections/string/_unicode.mojo` is refused because the module it imports
declares no function and no type at all — only eight `comptime` lookup tables.
The message says "There is nothing an importer could bind, and nothing this
backend could add", and as a statement about a dylib's export trie that is
correct. **But `_unicode.mojo` does bind those eight names**, as compile-time
constants read at a use site, and this branch's `77cfe92e` establishes what the
answer to THAT read is: a module-level container constant is a constant with a
home in the defining library's `__DATA`, and what does not cross is its ADDRESS.

So the row is two walls, and knowing that is worth more than the row:

1. the export gate refuses a module with nothing to export;
2. past it, `global_constant[has_uppercase_mapping]()` needs
   `__mlir_op.pop.global_constant`, which is the MLIR row
   (`FORMAL_known_limits.md` §2).

Filed as `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`, with both
walls and the measurement. **0 files move**, and the doc says so.

### 5.2 `map.mojo` is the same row as §4.1 seen from the importer

`algorithm/backend/cpu/__init__.mojo` is `codegen/dependency` behind it. One file
either way; the wall and the in-file row are the same refusal.

## 6. What this slice needs, in order

**STALE IN ITS FIRST THREE ITEMS as of 2026-10-05 — see the header table.**
Item 1 is DONE by somebody else and the row moved; item 2's refusal is gone and
its row moved onto the export rule; item 3's refusal is gone and its rows moved
onto the variadic ABI. **The order to measure in now is: (0) the
`std.format._utils` export of `FormatStruct`, which stands in front of items 1,
2 and 3 at once, then (1) `binary_heap.mojo`'s new `self.unsafe_ptr()` row,
then (2) `builtin_slice.mojo` past the export gate.** Items 4-6 below are
unchanged and still not this claim's.

1. ~~**`binary_heap.mojo`'s `pop()`**~~ — **FIXED between 2026-10-04 and
   2026-10-05** (`formal/model.py`'s one-field-mutator receiver handover, which
   this claim's own `5f8ba760`-era neighbour work records). 25 of the 46 rows
   here, ~165 in the corpus,
   and the export gate that used to sit behind it is gone. Not this claim's row.
2. **`builtin_slice.mojo`'s `self = other`** — 13 rows here, 43 in the corpus.
   Not this claim's row.
3. **The bracketed-specialization rule** — 6 rows here. Not this claim's row.
4. **`type_dict.mojo`'s parameter binding** — 1 row, filed, a monomorphizer.
5. **`_unicode_lookups.mojo`'s export gate** — 1 row, filed, and behind it the
   MLIR row, so it is worth 1 row and no more.
6. **Function values** (`map.mojo`) — 2 rows, filed in §4.1's place.

Items 1-3 are 44 of the 46 and all three are other workers' live claims. **A plan
that starts at item 4 to make progress in this slice will not make progress in
this slice**, which is the one conclusion this measurement exists to record.

## 7. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sw -- python3 tools/formal_sweep.py \
  -j 3 -t 120 --arch x86_64 \
  ../new-modular/Mojo/stdlib/std/{collections,memory,algorithm}

# the six walls, from the printed lines' own chains
grep -h 'cannot be built either:' .tmp/post-arm64-all.txt \
  | sed -E 's/.*cannot be built either: ([^:]*):.*/\1/' | sort | uniq -c

# and the in-file rows
grep -h '^CODEGEN: ' .tmp/post-arm64-all.txt .tmp/arm-g3.txt
```

Editing anything under `formal/` invalidates the sweep CAS, so a re-measurement
is a real rebuild of the slice's whole import closure (`tools/formal_sweep.py`'s
own bytes are in every key).
