# FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib: `std/collections/string/_unicode_lookups.mojo` blocks `_unicode.mojo`, and there are TWO walls behind it
**Status: PARTIALLY FIXED 2026-10-05 (`work/formal41-exports-and-strings`,
`9722edb7` + `57412b76`) — the `std/math/constants.mojo` terminal cause on this
row is GONE (33 of 59 files, measured on both architectures) and the gate is now
a rule with a tested boundary. The row's TOTAL did not move and no file builds:
the 33 went one level deeper to `_io.mojo`, which is the same row. The
`_unicode_lookups` half this document is named for is NOT fixed, and every wall
§3 describes still stands.** §0 records the measurement in full, including the
part of it that is unflattering; nothing below has been re-derived and the
analysis is the 2026-10-03 one.

## 0. 2026-10-05: the `constants.mojo` terminal cause is gone, the row is not

**The terminal cause of the largest group on the row was a module this
document does not mention**, and the map could not even name it:
`bugs/FORMAL_sweep_work_map_2026-10-05_b13.md` §4 records the row's 59 files
as "33 blocked by `constants.mojo`" and then says the `uses:` line is
**NOT MEASURED** — "the chain names this module by basename only and that
basename is absent or ambiguous in this tree". It is ambiguous: this tree has
three `constants.mojo`, and the one the chain means is **`std/math/constants.
mojo`** — 33 lines, eight `comptime` constants (`pi`, `e`, `tau`, `log2e`,
…), and not one declaration.

`std/math/__init__.mojo` writes `from .constants import e, pi, tau`, and that
one edge was refused for **33 of the row's 59 files**. So the biggest single
group on the third-largest row of the whole corpus was not the feature this
document asks for and not the constants-only family the previous round
measured as permanent. It was a rule about when a module with no SYMBOL is
still allowed to be a LIBRARY.

**The refusal was right about the module and wrong about the consequence.**
`constants.mojo` really has no symbol, and `no_public_api_reason`'s sentence
("There is nothing an importer could bind") is true of it. But the importer was
not asking for a symbol. It was asking for a **value**, and a value crosses a
boundary through the manifest's `constants` table — one value of a folded
module-level name in a whole program, so the consumer materializes the same one
in its own image. That route is not new: `sys.byteorder` and every package that
re-exports a constant already take it, and `formal/hostmods/sys.mojo`'s own
docstring says so. What was missing was a module whose whole API is such values
being allowed to BE a library, which is precisely what `_namespace_library`
emits — a real MH_DYLIB with an empty export trie and a populated constants
table. So the gate that reaches it (`formal/build.py::
_publishable_constant_values_module`) is now reached by a second shape, and
the refusal stands for the half with no way across at all.

**Measured, both architectures, all 59 files of the row, 118 builds:**

| | before | after |
|---|---|---|
| files stopped by `constants.mojo` | **33** | **0** |
| files stopped by `_io.mojo` | **23** | **56** |
| files stopped by `_select.mojo` / `_unicode_lookups.mojo` / `stat.mojo` | 1 / 1 / 1 | 1 / 1 / 1 |
| **the row's total** | **59** | **59** |
| files that BUILD | 0 | **0** |
| architectures disagreeing about any of the 59 | 0 | 0 |

**Read that table honestly, because the shape of it is the whole result and it
is not the flattering one.** The row's total did not move and not one of the 59
files builds. What moved is 33 files from one blocker on this row to ANOTHER
blocker on this row: `_io.mojo` went 23 → 56 because the 33 that used to stop at
`constants.mojo` now get one level further and stop there instead. That is the
shape this project's own instruments warn about — "a file's terminal cause is
the first refusal its build walk reaches, so fixing one moves the file to the
next with the count unchanged" (`FORMAL_sweep_work_map_2026-10-05_b13.md` §4) —
and it is why a row count is an upper bound and not a coverage number.

**What the change is worth is therefore not a row count, and claiming one would
be the error the map's §4.3 is about.** It is worth three things a count cannot
show:

* **the `constants.mojo` terminal cause is gone** — not moved behind another
  refusal of the same kind, but gone: 0 of 118 builds stops there, against 33 of
  59 before;
* **the gate is now a rule with a stated boundary** rather than a refusal whose
  only content was that the module declares nothing. `_unicode_lookups.mojo`'s
  container and `_io.mojo`'s `FileDescriptor(0)` are refused for a REASON —
  nothing to publish — and both are pinned by tests that fail if the reason
  changes;
* **the `std/math/constants.mojo` case is a module real importers use**, and it
  now builds on both architectures with its four values readable across the
  boundary, checked against CPython. `std/math/__init__.mojo` is still refused,
  on `_io.mojo`, and it will stay refused until §0.1's storage feature lands —
  so this fix moved that file, not saved it.

### 0.1 What is left, and it is the part this document is actually about

`std/sys/_io.mojo` is the largest group on the row, and it is a DIFFERENT fact
from `constants.mojo`: its three names are `comptime stdin = FileDescriptor(0)`,
`stdout`, `stderr` — **struct constructions**, and `fold_module_value` has no arm
for a call, so there is no value to publish and no symbol either. A module in that
shape genuinely has nothing an importer could reach, and the refusal is the right
answer; it is recorded and pinned by `test_formal_imports.py`'s `a constants-only
module with an unfoldable value is still refused`. Closing it is
`FORMAL_module_state_no_storage.md` §(2) — a real `__DATA` home for a module
constant whose value is not a word — and that doc has **no live claim**, so it is
the cheapest open thing left on this row.

**So: of the row's 59 files, 56 are now stopped by one storage feature, and the
other three are correct refusals** (a private name, a container blob, generic
templates nobody instantiates). **This document's own subject —
`_unicode_lookups.mojo` — did not move**, and §4's verdict about it still stands:
it needs the container feature, and even with it the MLIR row is behind it.

### 0.2 2026-10-03: unchanged, and the honest stopping point had moved further away

Re-measured on this tree:

```console
$ python3 fire.py build --formal --no-prove -o .tmp/uni.out \
      ../new-modular/Mojo/stdlib/std/collections/string/_unicode.mojo
build: _unicode.mojo imports 'std.collections.string._unicode_lookups', which
cannot be built either: _unicode_lookups.mojo: formal dylib has no public
functions: ... (identical to §1)

# §3 wall 2, the MLIR row -- and what is in FRONT of it now:
$ python3 fire.py build --formal --no-prove -o .tmp/gc.out .tmp/gc.mojo
build: gc.mojo imports 'std.builtin.globals', which cannot be built either:
builtin_slice.mojo: StridedSlice___init__ returns a frame address, so it cannot
be compiled into a dylib ...
$ python3 fire.py build --formal --no-prove -o .tmp/gc2.out .tmp/gc2.mojo
build: pick: `pop.global_constant` is a dialect OPERATION whose value could be a
word on this path, but it cannot be GUARDED here: ...
```

**The MLIR refusal itself is unchanged** — same operation, same "a deliberate
deferral, not an impossibility" wording — so §3 wall 2 stands as written. What is
new is that reaching it through the real spelling costs one more blocker:
`std.builtin.globals` (which is where `global_constant` lives) imports
`builtin_slice.mojo`, whose `__init__` returns a frame address, and a
returned-frame function cannot go into a dylib at all. So the feature §4 step 1
asks for would have to clear THREE walls to move this row by one file, not two.

**Why nothing was done here** (as of 2026-10-03; §0 above is what changed),
and it is not only the "not worth it" the original Status gave:

* the fix is one feature — inline a container-valued module constant at the use
  site, and skip the dylib for a module nothing binds — and that feature is the
  one `FORMAL_module_state_no_storage.md` §(2) needs, which is
  `work/formal16-5`'s claim. Two workers implementing one feature is how the two
  halves end up disagreeing about what a module constant IS.
  **The second half landed 2026-10-05 for the folded-value case** (§0) and the
  first did not, which is the split this bullet predicted: "a module with nothing
  to export needs no dylib" and "a module constant's value crosses a boundary"
  are two features wearing one sentence, and only the one that needs no new
  storage was cheap;
* even done, the row moves one file (`_unicode_lookups.mojo`, which nothing
  imports for its own sake) and `_unicode.mojo` still refuses — on the MLIR row,
  now behind the slice row;
* and the working repair for the table is still an accessor, which is a source
  change to an external stdlib that no repository worktree can make.

Found by sweeping `std/collections` for `sweep14:std-collections`; see
`FORMAL_sweep14_std_collections.md` §5.1.

---

## 1. The row

```
CODEGEN/DEPENDENCY: ../new-modular/Mojo/stdlib/std/collections/string/_unicode.mojo
  (build: _unicode.mojo imports 'std.collections.string._unicode_lookups', which
  cannot be built either: _unicode_lookups.mojo: formal dylib has no public
  functions: _unicode_lookups.mojo exports nothing under doc/ABI.md's rules
  because it declares no function and no type at all — only module-level
  constants, which are inlined at their use site and cross no boundary. There is
  nothing an importer could bind, and nothing this backend could add.)
```

Byte for byte the same on arm64 and on x86-64. One file, and the b7 map §3
already counted it (`_unicode_lookups.mojo x1` out of 668 files).

`_unicode_lookups.mojo` is 8 `comptime` lookup tables and nothing else:

```mojo
comptime has_uppercase_mapping: Array[UInt32, 1450] = [0x0061, 0x0062, …]
comptime has_lowercase_mapping: Array[UInt32, 1433] = […]
comptime uppercase_mapping:      Array[UInt32, 1450] = […]
comptime lowercase_mapping:      Array[UInt32, 1433] = […]
comptime has_uppercase_mapping2: Array[UInt32, 26]   = […]
comptime uppercase_mapping2:     Array[SIMD[.uint32, 2], 26] = […]
comptime has_uppercase_mapping3: Array[UInt32, 13]   = […]
comptime uppercase_mapping3:     Array[SIMD[.uint32, 4], 13] = […]
```

and `_unicode.mojo` imports all eight and reads each of them.

## 2. The measurement that makes the doc worth having: the SAME module builds

```sh
python3 fire.py build --formal --no-prove -o .tmp/gbl.out \
  ../new-modular/Mojo/stdlib/std/collections/string/_grapheme_break_lookups.mojo
# Built: .tmp/gbl.out  [arm64/macho]
```

`collections/string/_grapheme_break_lookups.mojo` is the same shape — four
`comptime` tables, 580 lines, **zero imports** — and it is one of only **3 files
in this 53-file slice that build**. So the export gate is not a fact about a
module that declares nothing; it is a fact about a module that is **imported**.

Which is the whole of the diagnosis: *as a program* a constants-only module needs
no exports, and *as a library* the build insists on one and then refuses.

## 3. The two walls, and the second one is why this is 1 file

**Wall 1 — the export gate.** `doc/ABI.md`'s export rule publishes functions and
non-generic types. A module with neither has an empty trie, and
`compile_formal_dylib` refuses rather than writing a library nothing can bind.

The candidate repairs, and why neither is worth starting:

* **Do not build a dylib for a module nothing binds.** Sound — a library with no
  exports is never loaded, because there is no symbol to resolve — but the
  importer still needs the eight VALUES, and with no dylib there is no `__DATA`
  to read them out of. It only works if the importer inlines the module body, and
  that is `model.module_body` plus a substitution for a container-valued
  constant, which is wall 1½ below.
* **Give the module an export.** Wrong as a fix and it says so: the whole table
  is lookup data, and exporting `has_uppercase_mapping` as a boundary symbol would
  mean publishing a 1450-word blob's address — a parameterless global whose
  address is chosen at link time, which is the same missing capability as every
  other exported slot (`FORMAL_module_state_no_storage.md` §(2), still open).

**Wall 1½ — a container constant's ADDRESS does not cross.** Measured, both
architectures, and now a refusal of its own thanks to `77cfe92e`:

```
# lookups.mojo:  TABLE = [10, 20, 30]        (nobody writes it)
# user.mojo:     from lookups import TABLE ; … TABLE[0]

build: 'TABLE' is imported from `lookups`, where it is a module-level CONSTANT
whose only writer is its own module-level statement — its value is laid out in
`lookups`'s `__DATA` as a run of words, and there is exactly one of it in a whole
program. What does not cross is the ADDRESS: a dylib publishes functions and
folded literals, and a block of static data is neither, because its address is
chosen when the library is linked and this image cannot have known it. … give
`lookups` an accessor that hands back what you need out of it (`def TABLE_at(i:
Int) -> Int: return TABLE[i]`) and call that, which is code, and code is what a
dylib exports
```

The accessor **works** — measured, both architectures, `10 30` where CPython
prints `10 30` (`test_the_accessor_is_the_spelling_that_reads_another_modules_container`).
Note what that says: the working repair for a 1450-entry table is an accessor
that returns ONE ELEMENT, so a program that wants the whole table wants 1450
accessor calls or a different design. **That is a source change to the stdlib**,
which is exactly the kind no repository worktree can make.

**Wall 2 — MLIR.** Even with both of the above, `_unicode.mojo` reads
`global_constant[has_uppercase_mapping]()`, and `global_constant` is
`_mlir_value=__mlir_op.\`pop.global_constant\`[value=value]()`
(`std/builtin/globals.mojo:58-73`). The MLIR dialect row is
`FORMAL_known_limits.md` §2 / `formal2-mlir-comptime`. **Unfixed, this row moves
0 files however the first two are closed.**

## 4. The exact next step

**This row is closed as "not worth it", and this doc exists so that decision is
on the record rather than re-derived.** If someone does want it:

1. ~~skip the dylib for a module nothing binds~~ — **DONE for the folded-value
   case**, 2026-10-05 (`9722edb7`): `_publishable_constant_values_module` lets a
   module whose whole API is folded literals be a library, which is where the
   `constants.mojo` terminal cause went (33 → 0 files). **It moved those 33
   files one level deeper rather than off the row**, so this step bought the
   cause and not the count — §0 has the table. What is left is the other half of
   the same sentence, and it is `FORMAL_module_state_no_storage.md` §(2), which
   has no live claim:
   1. a module constant whose value is **not a word** — a struct construction
      (`std/sys/_io.mojo`, which 56 of the row's 59 files now stop at, §0.1) or
      a container blob (`_unicode_lookups.mojo`, §3 wall 1½) — needs a real
      `__DATA` home, and `module_body` is where it would be taught to inline one
      at the use site;
2. then re-sweep `_unicode.mojo` and expect the MLIR row, which is the honest
   stopping point. **Unchanged by §0**: that file did not move, and nothing in
   §0 brings the MLIR row any closer.

**Do not** add a stub function to `_unicode_lookups.mojo` to get past the gate.
It would move the refusal one layer and hide the real one — which is what
`FORMAL_sweep_work_map_2026-10-02_b7.md` §6 records doing for the 16-file row of
top-level statements, where a stub would have made a build pass that computed
nothing, and why the doc that recorded it
(`FORMAL_dylib_module_body_has_no_load_time_entry_point.md`) was **deleted** with
the fix rather than kept as a Status history.

## 5. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH

# §0: the half that is fixed — a package importing a constants-only module,
# both architectures, and the empty export trie beside the two folded values
python3 test_formal_imports.py    # a constants-only module is imported, …

# §0.1: the boundary — the unfoldable shape is still refused, by name
python3 test_formal_imports.py    # … and with an unfoldable value is refused

# the row
python3 tools/memslot.py --gb 8 --label u -- python3 fire.py build --formal \
  --no-prove -o .tmp/u.out \
  ../new-modular/Mojo/stdlib/std/collections/string/_unicode.mojo

# §2: the same shape builds when nothing imports it
python3 fire.py build --formal --no-prove -o .tmp/gbl.out \
  ../new-modular/Mojo/stdlib/std/collections/string/_grapheme_break_lookups.mojo

# §3: the container-constant refusal and its working repair, both arches
python3 test_formal_module_attr.py
```
