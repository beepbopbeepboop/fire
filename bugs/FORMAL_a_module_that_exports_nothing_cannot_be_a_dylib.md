# FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib: `std/collections/string/_unicode_lookups.mojo` blocks `_unicode.mojo`, and there are TWO walls behind it
**Status: unchanged and re-measured 2026-10-03 (`work/formal16-2`); the row is
still "not worth it", and the honest stopping point has MOVED FURTHER AWAY rather
than closer.** The refusal below is byte for byte what this doc recorded, the
container-constant refusal §3 quotes is still the current one, and the MLIR row of
§3 wall 2 is now *behind a second wall the doc does not mention*. Nothing here is
fixed, and the one thing that would fix it is a feature another worker holds.

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

**Why nothing was done here**, and it is not only the "not worth it" the original
Status gave:

* the fix is one feature — inline a container-valued module constant at the use
  site, and skip the dylib for a module nothing binds — and that feature is the
  one `FORMAL_module_state_no_storage.md` §(2) needs, which is
  `work/formal16-5`'s claim. Two workers implementing one feature is how the two
  halves end up disagreeing about what a module constant IS;
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

**None. This row is closed as "not worth it", and this doc exists so that
decision is on the record rather than re-derived.** If someone does want it:

1. teach `module_body` to inline a container-valued module constant at the use
   site, and skip the dylib for a module nothing binds — one feature, and it is
   the same feature `FORMAL_module_state_no_storage.md` §(2) needs;
2. then re-sweep `_unicode.mojo` and expect the MLIR row, which is the honest
   stopping point.

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
