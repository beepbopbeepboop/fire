# FORMAL_sweep20_std_collections_2: `std/collections`, `std/memory`, `std/algorithm`, `std/iter`, `std/itertools` — round 2, both architectures, and a resolution defect the round found

**Claim** `sweep20:std-collections-2` on `work/formal20-std-collections-2`.
56 files per architecture, `-j 2 -t 120`, on `master` at `3c3516db` plus this
branch's commits. **Both arms agree path-for-path and class-for-class, before
and after the fix below**, and the only difference anywhere in the four logs is
the architecture inside one dylib's file name — the fourth round running in
which that is the whole x86-64 story for this slice.

Two things a reader should take away, in this order.

* **Every one of the six in-file refusals is another worker's live claim.** Four
  distinct causes, six files, and not one of them unowned: the bare-template-call
  row (3 files) and `type_dict.mojo`'s parameter binding are
  `FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable` and
  `FORMAL_a_generic_structs_parameters_are_never_bound` (`formal19-1`),
  `binary_heap.mojo` is `FORMAL_binary_heap_mojo_after_the_len_value`
  (`formal18-2`), and `tile.mojo` is
  `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value`
  (`formal16-7`), whose own last section names the variadic parameter as the
  next wall and says it is "a change to the calling convention both backends AND
  the Lean proof share". **A plan that starts at the fourth-largest cause here
  to make progress in this slice will not make progress in this slice** — which
  is round 1's conclusion (`…_sweep14_std_collections.md` §6) re-measured on a
  tree that has absorbed ~150 formal branches since, and it still holds.
* **What the round DID find is not a coverage gap at all: a dotted import could
  bind a module it does not name.** `resolve_module_path` offered a name's LEAF
  to each search root before offering the name AS SPELLED to the roots further
  out, so which of the two won was decided by how deep the importing file
  happened to sit. **31 imports in 252 stdlib files bound a module other than
  the one they name**, and two of them are two modules that each import the
  other and each compiled ITSELF. Fixed, with the ordering as the whole repair
  (§5). It moved no class in this slice — 4 pass, 6 `codegen`, 46
  `codegen/dependency`, before and after — and that is the honest headline: it
  removed a class of *silently wrong* answers, not a class of refusals.

---

## 1. The run

```sh
export PATH=/opt/homebrew/bin:$PATH
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label sw20-$a -- \
    python3 tools/formal_sweep.py -j 2 -t 120 "--arch=$a" \
      ../new-modular/Mojo/stdlib/std/collections \
      ../new-modular/Mojo/stdlib/std/memory \
      ../new-modular/Mojo/stdlib/std/algorithm \
      ../new-modular/Mojo/stdlib/std/iter \
      ../new-modular/Mojo/stdlib/std/itertools
done
```

Four runs, all 56 files, all complete (each run's own summary line is the
authority and it sums to its file count):

| run | files | classes | CAS | log |
|---|---|---|---|---|
| arm64, before | 56 | 4 pass, 6 codegen, 46 codegen/dependency | 0 hit / 56 miss | `bugs/sweeps/sweep20-std-collections-2-arm64-BEFORE-the-resolution-fix.txt` |
| x86-64, before | 56 | the same, per path | 8 hit / 48 miss | `…-x86_64-BEFORE-the-resolution-fix.txt` |
| arm64, after | 56 | the same, per path | 10 hit / 46 miss | `…-arm64-AFTER-the-resolution-fix.txt` |
| x86-64, after | 56 | the same, per path | 0 hit / 56 miss | `…-x86_64-AFTER-the-resolution-fix.txt` |

All four logs are committed. `--stdlib-subtrees collections,memory` does **not**
find these: the subtrees are looked up directly under the stdlib root, so the
spellings that work are `std/collections,std/memory,…` or explicit paths, and
the paths above are what ran.

Peak **0.3 GB** across up to 5 processes against the 8 GB reservation, on all
four runs; no memory breach; no `tool` row and no `not-answerable` row on either
architecture.

**The 10 arm64 "hits" in the after-run are sound and worth explaining**, because
they are the one number here that looks like a stale cache. `cas.formal_build_key`
folds in `cas.formal_fingerprint()`, which is a glob over `formal/**`, so editing
`formal/imports.py` changes every key in the store and a run after the fix
should miss on all 56. It hit on 10 because a **full 710-file sweep of this tree
accidentally ran on the fixed tree** (§7) and published verdicts under the new
key before the after-run started. Those verdicts are the fixed tree's own — the
timeout is the only per-run input that is not in the key and a timeout is never
published — so the comparison stands. The x86-64 arm missed on all 56 because
that sweep was arm64-only, which is the same fact from the other side.

## 2. Classes, both architectures, identical — and identical before and after

| class | arm64 before | arm64 after | x86-64 before | x86-64 after |
|---|---|---|---|---|
| **pass** | **4** | **4** | **4** | **4** |
| **codegen** (a refusal IN the file) | **6** | **6** | **6** | **6** |
| codegen/dependency | 46 | 46 | 46 | 46 |
| not-answerable / backend-crash / tool / unknown | 0 | 0 | 0 | 0 |
| files | 56 | 56 | 56 | 56 |

Codegen coverage **4/56 = 7.1 %** in all four runs, over a denominator that is
every swept file (nothing is in a not-answerable or tool class).

**The 4 passes are the same four on both architectures and in both runs**, and
they are worth naming because one of them is new since round 1:

```
algorithm/backend/cpu/map.mojo                                  (a call through a function VALUE)
collections/string/_grapheme_break_lookups.mojo                 (580 lines, 0 imports)
collections/string/_unicode_lookups.mojo                        (8 constants, 0 imports)
collections/string/_parsing_numbers/__init__.mojo               (12 lines, 0 imports)
```

The three constants-only modules are round 1's three, and `map.mojo` is the
fourth: round 1 filed it as an in-file refusal — "already refused correctly, and
already was … Take what the operation DOES rather than the operation" — and it
builds now. That is the only PASS this slice gained since round 1, and it came
from a branch that is not this claim's.

**`0` in the `not-answerable` classes is the structural fact about this slice**:
a file that declares no function and no type builds as a program, and read as
an IMPORT it is a refusal (§4's "no boundary symbol" rows). A stdlib module is
imported, so the second reading is the one that costs anything.

## 3. What moved since round 1, and since the b9 map

Round 1 (`bugs/FORMAL_sweep14_std_collections.md`, 53 files on `17ddeaec` plus
its two commits) measured 3 pass / 4 codegen / 46 codegen/dependency behind
**six** module walls. Both maps are in `bugs/`; this is the delta, file by file
where it is a single file and by wall where it is not.

| round 1's wall | files then | what it is now |
|---|---|---|
| `binary_heap.mojo`'s export gate | **25** | **GONE.** `formal/imports.py::library_free_edges` decides per edge (merged 2026-10-03, `work/formal18-export-gate`), so a module nobody binds a concrete name from is no longer refused for having no boundary symbol |
| `binary_heap.mojo`'s `pop()` (a mutator that also returns a value) | the file's own verdict | **GONE**, and two rows further on: the file's verdict is now `self.clear()`, a method call on a value |
| `binary_slice.mojo`'s `self.step.or_else()` | 13 | **GONE**, replaced by `slice returns a frame address, so it cannot be compiled into a dylib` (2 files here) |
| `tile.mojo`'s `workgroup_function[…](…)` bracketed specialization | 4 | **GONE**, replaced by `tile.mojo`'s own `*tile_size_list` variadic parameter (5 files here) |
| `map.mojo`'s call through a function VALUE | 1 in-file | **BUILDS** |
| `type_dict.mojo`'s `comptime` off a parameter | 1 in-file | unchanged, and the refusal now names the real premise |
| a module with no boundary symbol (`_unicode_lookups.mojo`) | 1 | 3 here (`_io.mojo`, `constants.mojo`, `_unicode_lookups.mojo`), 10 files |
| **not on round 1's list at all** | — | **the bare-template-call row: 31 files, the largest in this slice** |

So: **the 25-file wall fell and the row behind it is 31 files.** Both facts are
in the same measurement, and the second is why this slice's coverage number did
not move: the gate lifted and the next wall is wider than the one it hid.

`iter` and `itertools` are new to the scope (3 files) and all three are
`codegen/dependency`: `iter/__init__.mojo` and `itertools/__init__.mojo` behind
`std.memory`, `itertools/itertools.mojo` behind the `FormatStruct` row.

## 4. The six in-file refusals, and who owns each

The task's line is "every file that is a refusal IN the file (not closure, not
host-import)". There are six, in four causes, and **the owner column is the
finding**.

| file | the construct | the refusal | owner |
|---|---|---|---|
| `collections/bitset.mojo` | `FormatStruct(writer, "BitSet")` at `:692` | a bare call to a template whose type arguments are inferrable from the arguments | `FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable` (`formal19-1`) |
| `memory/alloc.mojo` | `FormatStruct(writer, "Allocation")` at `:450` | the same | the same |
| `memory/pointer.mojo` | `strided_load(self, Int(stride), SIMD[.bool, width](…))` at `:1892` | the same, on `std.sys.intrinsics`'s `def strided_load[dtype: DType, //, simd_width: SIMDLength, …]` | the same |
| `collections/type_dict.mojo` | `comptime _index[key: Self.T] = Self.keys.try_index(key)` | a `comptime` class attribute whose value reads a **PARAMETER**, which belongs to an instantiation and not to the class body | `FORMAL_a_generic_structs_parameters_are_never_bound` (`formal19-1`) |
| `collections/binary_heap.mojo` | `self.clear()` | a method call on a value whose receiver is a name, and `clear` is in neither method table | `FORMAL_binary_heap_mojo_after_the_len_value.md` §3a (`formal18-2`), whose own analysis says the one-word rewrite is the repair and that the table entry it names would "emit a store against the wrong word" |
| `algorithm/backend/tile.mojo` | `*tile_size_list` at `:99` | the body reads a `*-parameter` and this path has no variadic ABI | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`'s last section (`formal16-7`), which names this exact wall and calls it "a change to the calling convention both backends AND the Lean proof share" |

**I verified the two `strided_load`/`FormatStruct` rows are the inferrable-kind
shape and not something else**, because that is what decides the owner: `T` is
read off `writer: Some[Writer]`, `o` is the origin parameter's own default, and
`strided_load`'s `dtype` and `simd_width` are spelled in the types of `self:
Pointer[Scalar[dtype], …]` and of the third argument. All three are correct Mojo
with the brackets omitted, which is what the owner's doc says and what its §2
warns is worth repeating here: **the refusal's own next step — "spell it as
`FormatStruct[<a type>](…)`" — is wrong about correct code**, and a reader who
follows it edits working stdlib.

### The 46 dependency rows, by terminal cause (after the fix)

| files | terminal cause | owner |
|---|---|---|
| **29** | a bare call to the template `FormatStruct` (24) / `is_negative` (4) / `dealloc` (1) | `formal19-1`, as above |
| **10** | a module with no boundary symbol: `constants.mojo` (5), `_io.mojo` (4), `_unicode_lookups.mojo` (1) | `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib` (`formal16-2`) |
| **5** | `tile.mojo`'s variadic parameter | `formal16-7`, as above |
| **2** | `builtin_slice.mojo`: `slice` returns a frame address, so it cannot be a dylib export | `FORMAL_wide_receiver_by_reference` (`formal16-8`) — `FORMAL_builtin_slice_optional_field_is_a_frame_holder`'s §"Status 2026-10-03" says so and points one layer down |

**52 of the 52 non-passing files are behind four walls, and all four are
claimed.** That is the round's coverage finding, and it is the same finding round
1 recorded with a different set of numbers.

## 5. The defect this round found: a dotted import could bind a module it does not name

### 5.1 What it was

`resolve_module_path`'s pass 1 walked `_search_roots` nearest-first and, **at
each root**, offered `<name>.mojo`, `<name>/__init__.mojo` and then the same two
spelled with the name's **LEAF**. The leaf fallback is the documented way a
package-relative dotted import of a sibling resolves (`import formal.types`
written from inside `formal/`, where `formal/` is not a search root). The defect
is that the two were interleaved **per root** rather than ordered **across
roots**, so a leaf match one root near beat the spelling of the same name at a
root further out — and which of the two won was a fact about the IMPORTER's
directory depth, not about the import.

The first thing it did, in this slice:

```
$ python3 fire.py build --formal --no-prove -o .tmp/a.out \
      ../new-modular/Mojo/stdlib/std/collections/_asan_annotations.mojo
build: _asan_annotations.mojo imports 'std.sys.compile', which cannot be built
either: __init__.mojo: std_sys_compile.<digest>.arm64.dylib re-exports
compile_info from std.sys.compile.compile, but no module it imports exports that
name, so a caller of it would have nothing to bind.
```

`std/collections/_asan_annotations.mojo` writes `from std.sys.compile import
SanitizeAddress`. `<stdlib>/std` is one of its search roots (the walk ascends
from the importer), the LEAF candidates there include `compile/__init__.mojo`,
that file exists — so the build compiled **`std/compile/__init__.mojo`**, gave it
the module identity **`std.sys.compile`**, and reported a gap in *that* module's
public API. `.tmp/probe_dylib.py` (scratch) is the whole diagnosis in six lines:
it wraps `build_module_dylib` and prints the `(module_name, source_path, _parent)`
of every call.

### 5.2 How big it was, measured

Every `.mojo` file under `../new-modular/Mojo/stdlib/std` (252) and this
repository (458), every import in each, resolved both ways and compared
(`.tmp/leaf_census.py`, scratch; the roots are
`formal/imports.py::_search_roots(path, None)`, which is what
`formal/build.py::_resolve_imports` uses for a program's own imports):

| scope | imports that bound a module they do not name |
|---|---|
| this repository, 458 files | **0** |
| the stdlib, 252 files | **31** |

So it is a stdlib phenomenon, which is what the mechanism predicts: it needs a
deep absolute dotted spelling (`std.sys.compile`) *and* an ancestor directory
that is itself a search root holding a package with the same leaf
(`<stdlib>/std/compile/`). A flat repository has neither.

The 31, by shape:

* **12 are not arguable.** `std.sys.compile` → `std/compile/__init__.mojo`
  (3 files), `std.sys.intrinsics` → **`std/_gpu/intrinsics.mojo`** (4),
  `std.math.math` → `std/math/__init__.mojo` (4 — the name spells the MODULE
  and got the PACKAGE), `std.io.io` → `std/io/__init__.mojo` (4, same shape),
  `std.os.os`, `std.time.time`, `std.collections.string.format` →
  `std/format/__init__.mojo`. Each compiled the wrong file **under the right
  module name**, which is a wrong answer with nothing on the link line to catch
  it.
* **2 are the clearest statement of the shape there is.** `std/sys/info.mojo`
  writes `from std._gpu.host.info import …` and resolved to **itself**;
  `std/_gpu/host/info.mojo` writes `from std.sys.info import …` and resolved to
  **itself**. Two modules, each importing the other, each compiling itself.
* **17 are the other direction** — a name that spells a PACKAGE and got the
  module beside it: `std.math`, `std.memory` (3 files), `std.benchmark`,
  `std.python`, `std.random`, `std.collections.string`.

### 5.3 The repair

One ordering, in one place. The name **as spelled** is offered to every root
before the leaf is offered to any. `_candidates` becomes `_candidate_shapes`
(the two phases, as a tuple) plus `first_source` (the search), and pass 3 (`.py`)
goes through the same function rather than a second copy of the loop — a second
copy is a second ordering to keep in step.

Nothing else moved: `_search_roots` is untouched, the leaf fallback keeps every
purpose its docstring gave it (a name whose dotted spelling exists nowhere still
resolves through it — which is what `test_package_relative_dotted_import_resolves`
and `formal/x86_64_codegen.py`'s `import formal.types` rely on), the four passes
keep their documented precedence, and relative imports are resolved before any of
it and are untouched.

**Both architectures, by construction**: this is resolution, one code path, above
either emitter — and §2's four-way agreement is the measurement of it.

### 5.4 Tests, and the proof that they pin it

`test_formal_imports.py`, two cases:

* **`test_the_spelling_outranks_a_nearer_roots_leaf`** — the measured shape
  with the numbers replaced, so the two candidate modules return **different
  values** and the program's exit code says which one it bound (10 is the
  spelling, 99 is the nearer root's leaf).
* **`test_a_dotted_stdlib_import_resolves_to_the_module_it_names`** — the 24
  measured rows, plus a walk of **every** stdlib file that fails if *any* import
  drifts off the name it spells, so the shape cannot come back in a file no sweep
  row names yet.

**Both are red under the old ordering.** `.tmp/prove_red.py` monkeypatches
`first_source` back to the interleaved loop and runs exactly those two:

```
RED   the spelling outranks a nearer root's leaf
        `pkg.sub.mod` from a/b/prog.mojo resolved to '…/a/mod/__init__.mojo';
        the name spells pkg/sub/mod.mojo …
RED   a dotted stdlib import resolves to the module it names
        collections/_asan_annotations.mojo writes `from std.sys.compile import …`,
        which spells sys/compile.mojo; it resolved to compile/__init__.mojo instead
```

`test_formal_imports.py` is **72/72**. Because `formal/imports.py` is on
CLAUDE.md's "owes a full `make gate`" list, I also ran the 37 formal test files
whose subject touches import resolution (`grep -l 'formal\.imports\|resolve_module_path\|from formal import imports' test_*.py`),
three at a time under `tools/memslot.py --gb 8`: **32 exit 0**, including
`test_formal_run.py` at 954/954, `test_formal_link_accounting.py` at 246/246,
`test_formal_cross_module.py` at 33/33 and `test_formal_monomorph.py` at 11/11.
The **5 that exit 1 fail identically with `master`'s `formal/imports.py`
restored** — measured, by `cp`-ing the committed file back over mine, running,
and `cp`-ing mine back:

| file | why it is red on `master` too |
|---|---|
| `test_ab_native` | needs a `mojoc` this worker may not build |
| `test_formal_manifest_atomic` | `ValueError: not enough values to unpack (expected 3, got 2)` at `formal/imports.py:3461` — `depends` is appended as a 2-tuple and read as a 3-tuple. **Pre-existing, in the file I edited but not in the code I changed**; someone is mid-flight in `_record` |
| `test_formal_sweep` | one failure whose own message says its fixture "tests nothing" (the bind it resolved is `exit`, which `lstrip('_')` cannot change) |
| `test_formal_sweep_truth` | 6 errors, all `no step lemma wired for: alu_ri32:sub_reg, lea_r64_rip` in the x86-64 end-to-end emitter |
| `test_re_formal` | 2 failures on a `typedef` regex in `formal/re`'s corpus-pattern table |

### 5.5 What the re-measurement shows: 0 classes moved, and that is the point

The slice, both architectures, before and after: **4 pass, 6 codegen, 46
codegen/dependency, in all four runs.** No class moved in either direction. What
moved is five files' **terminal cause**, and every move is towards a true answer:

| file | was | is |
|---|---|---|
| `collections/_asan_annotations.mojo` | **a fabricated refusal**: `std_sys_compile…dylib re-exports compile_info from std.sys.compile.compile` — a gap invented by compiling the wrong module under the right name | the `FormatStruct` bare-call row, like 28 other files here |
| `collections/_conditional.mojo` | `FormatStruct` | `_io.mojo`: no boundary symbol |
| `collections/string/__init__.mojo` | `FormatStruct` | `constants.mojo`: no boundary symbol |
| `collections/string/codepoint.mojo` | `FormatStruct` | `constants.mojo`: no boundary symbol |
| `memory/arc_pointer.mojo` | `is_negative` | `constants.mojo`: no boundary symbol |

Those four are not incidental: `.tmp/closure_moved.py` (scratch) walks the
import closure of two of them and counts **21 moved bindings** inside it,
including the self-import pair `std/sys/info.mojo` ↔ `std/_gpu/host/info.mojo`
and `arc_pointer.mojo`'s own `from std.memory import ArcPointer`, which used to
mean `std/memory/memory.mojo`. Their new wall is reached through a closure that
is now the right one.

**So the honest summary of this fix is: 31 wrong bindings removed, one fabricated
refusal removed, five files re-pointed at truthful walls, and not one class
moved.** A defect whose measured effect on a coverage number is zero and whose
effect on what the compiler *computes* is a module compiled in place of another
is exactly the kind that a coverage sweep will never find on its own, and the
reason it is worth a commit and a test rather than a row in this document.

## 6. What this slice needs, in order

1. **`FormatStruct(writer, "Allocation")` and friends — inferrable type
   arguments on a bare callee** (`formal19-1`). 29 of the 46 dependency rows and
   3 of the 6 in-file rows here; ~123 in the corpus. **One feature.**
2. **`constants.mojo` / `_io.mojo` / `_unicode_lookups.mojo`: a module with no
   boundary symbol** (`formal16-2`). 10 rows here. Permanent as a dylib question;
   the values would have to cross some other way.
3. **`tile.mojo`'s `*tile_size_list`** (`formal16-7`). 5 rows here. A calling
   convention both backends and the Lean proof share — not a light worker's row,
   by its own doc's assessment.
4. **`builtin_slice.mojo`'s `slice` returning a frame at a module boundary**
   (`formal16-8`). 2 rows here.
5. **`binary_heap.mojo`'s `self.clear()`** (`formal18-2`). 1 in-file row, and its
   own analysis puts the repair in the one-word rewrite rather than the method
   table.
6. **`type_dict.mojo`'s parameter binding** (`formal19-1`). 1 in-file row, and a
   monomorphizer.

Items 1-4 are 46 of the 46 dependency rows and **all four are live claims**. As
in round 1: a plan that starts at item 5 to make progress in this slice will not
make progress in this slice.

## 7. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH

# §1, both arms, before and after (four runs; ~13 min each at -j 2 -t 120)
for a in arm64 x86_64; do
  python3 tools/memslot.py --gb 8 --label sw20-$a -- \
    python3 tools/formal_sweep.py -j 2 -t 120 "--arch=$a" \
      ../new-modular/Mojo/stdlib/std/{collections,memory,algorithm,iter,itertools}
done

# §2, the four-way agreement, from the committed logs
python3 - <<'PY'
import re
def rows(p):
    d = {}
    for line in open(p, errors="replace"):
        m = re.match(r'^([A-Z][A-Z0-9/_-]*): (\S+)  \(', line)
        if m: d[m.group(2)] = m.group(1)
    return d
a, x = rows("bugs/sweeps/sweep20-std-collections-2-arm64-AFTER-the-resolution-fix.txt"), \
       rows("bugs/sweeps/sweep20-std-collections-2-x86_64-AFTER-the-resolution-fix.txt")
print([p for p in a if a[p] != x.get(p)], sorted(set(a) ^ set(x)))
PY

# §5.2, the census: every import in a scope, resolved both ways
python3 .tmp/leaf_census.py $(find ../new-modular/Mojo/stdlib/std -name '*.mojo')

# §5.1, the whole diagnosis of the first row, in six lines of scratch
python3 .tmp/probe_dylib.py build --formal --no-prove -o .tmp/asan.out \
  ../new-modular/Mojo/stdlib/std/collections/_asan_annotations.mojo

# §5.4, that the two new tests are red under the old ordering
python3 .tmp/prove_red.py

# §5.4, the 37 resolution test files, three at a time
bash .tmp/run_import_tests.sh
```

`.tmp/probe_dylib.py`, `.tmp/leaf_census.py`, `.tmp/closure_moved.py`,
`.tmp/prove_red.py`, `.tmp/wait_sweep.sh` and `.tmp/run_import_tests.sh` are
**scratch, not committed** (`.tmp/` is git-ignored, and `…_b7.md`/`…_b8.md`/
`…_b9.md` did the same), so each is described rather than shipped. Editing
anything under `formal/` invalidates the sweep CAS, which is why the BEFORE logs
are committed in their own commit and the after-logs in their own.

**One accident worth recording, because it cost a machine and it is the kind of
thing a reader of somebody else's `work.log` deserves to know**: a commit message
containing an unescaped pair of backticks around `python3 tools/formal_sweep.py`
was run by the shell as a command substitution, so a **full 710-file sweep of
this repository and the whole stdlib** started at `-j 18 -t 30` instead of the
intended commit. It was killed with the shell command, published its partial
ledger under its own extension as the tool documents, and released the arm64
lock; §1's 10 CAS hits are its doing and they are sound for the reason given
there. **Write the commit message to a file and use `git commit -F`.**
