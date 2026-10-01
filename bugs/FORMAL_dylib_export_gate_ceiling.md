# FORMAL_dylib_export_gate_ceiling: the 38-file row is not 38 problems, and the ceiling of every candidate is **0 files**

**Claim under `construct:dylib-export-gate`, measured 2026-09-30 on `738fb3ab`
(this tree), arm64, the tool's default scope. Verdict: no change to the export
rule is warranted, and the row should not be read as work.**

`bugs/FORMAL_sweep_work_map_2026-09-30_r2.md` row 2 is
`a module with no boundary symbol: only generic templates` — **38 files
blocked**, 35 of them `std/collections/binary_heap.mojo`. The task behind that
row asked for the marginal effect before any change, and named three
candidates: a per-instantiation export keyed by type arguments, a type
descriptor an importer can bind a template through, and narrowing the question
to the one module carrying 35 of the 38.

All three are measured here. **All three ceilings are 0 files**, and the reason
is the same in every case: *34 of the 35 do not contain the string
`BinaryHeap`.*

---

## 1. The baseline, reproduced

A fresh 637-file sweep of this tree, which lands on the r2 map's numbers
exactly (`PASS=112`, `codegen coverage: 112/481 = 23.3%`, `codegen/dependency
by family: … binary_heap.mojo: module exports nothing x35`):

    $ python3 tools/memslot.py --gb 8 --label ab-baseline -- \
          env GMOJO_HOME=$PWD/.tmp/gmojo_base python3 tools/formal_sweep.py \
          -j 6 -t 90
    [arm64] 637 files: PASS=112 not-pass=525

Cold CAS (`GMOJO_HOME` at an empty directory) throughout, per
`FORMAL_sweep_cache_ignores_imports.md` — every measurement below is of a change
to a `.mojo` file, and the sweep's cache cannot see one.

The 35 files, and the route each takes (chains read off the printed lines):

| how many | route |
|---|---|
| 21 | transitively (`std._plugin` → `std.collections`, `std.builtin.constrained` → …) |
| 7 | `from std.collections import …` directly |
| 4 | `from std.collections.string.string_slice import …` |
| 2 | both of the above |
| 1 | `from std.collections import …` plus `from std.collections.string import …` |

**34 of the 35 contain no occurrence of `BinaryHeap`.** The 35th is
`std/collections/__init__.mojo:27` itself, and what it contains is

```mojo
from .binary_heap import BinaryHeap
```

— a re-export. It does not construct one, call one, or name a method of one.
This is now printed by the cause table on every run (landed in `b6a94d35`):

    $ python3 tools/formal_sweep_causes.py --min 5 .tmp/ab_base.log
       38       0  module exports no public functions
            refused in: binary_heap.mojo x35, _unicode_lookups.mojo x1,
                        constants.mojo x1, stat.mojo x1
            uses: 1 of 35 blocked by binary_heap.mojo name anything it declares
                  (BinaryHeap)  [34 of the 35 name nothing it declares; the rest
                  of the row is closure]

## 2. Why the whole family is one module's re-export

The gate is not a property of the file that was swept. `formal/imports.py`'s
`build_module_dylib` compiles **every module in the file's eager transitive
import closure**, in source order, and `formal/build.py` refuses to emit a
dylib for a module with no boundary symbol — so one such module takes every
importer of its importers with it, whether or not any of them binds a name in
it. That is a deliberate design (`test_formal_imports.py` case 2: "it is
compiled IN FULL — a function the program never calls is still in the library"),
and it is what turns a 9-line re-export into 35 refusals.

`doc/ABI.md` §Generics and `FORMAL_known_limits.md` §1.1/§1.1a are right that
`struct BinaryHeap[T]` has no single boundary symbol, and the refusal is TRUE.
The doc's framing is what is missing: it is true *about `binary_heap.mojo`*, and
nothing in the 35 verdicts is about `BinaryHeap` at all.
(`FORMAL_module_exports_nothing.md` is the companion document: it is about the
refusal and its message, which are both right. This one is about what the
family is worth.)

## 3. Probe A — one concrete instantiation (or any change to the export rule)

**Method.** A copy of the stdlib in `.tmp/std_concrete` with ONE concrete public
declaration appended to `binary_heap.mojo`:

```mojo
def binary_heap_export_probe() -> int:
    return 0
```

so `_export_entries` is non-empty and the gate is satisfied. This stands in for
a per-instantiation export: for a file that never CALLS the template — 34 of
the 35 — what an exported `BinaryHeap[Int].push` would do to it is exactly
nothing, and the only observable difference in the build is that the gate stops
firing. The name is public on purpose: the first attempt used
`_binary_heap_export_probe` and was refused exactly as it should have been
(`reflect.EXCL_PRIVATE`), which is the export rule working.

**Result, all 35 files, cold CAS:**

    CODEGEN/DEPENDENCY  35   … binary_heap.mojo: other refusal x35
    [arm64] 35 files: PASS=0 not-pass=35

and the terminal reason is now *inside* `binary_heap.mojo` itself:

    binary_heap.mojo: len(self._data) — this slot's DECLARED type is
    'List[Self.T]', so the lowering is settled … `S()` does not run `__init__` on
    this path … a field with no class-level default is a word of zeros: the
    count word would be read from address 0.

**Ceiling: 0 of 35.** Not one file changes verdict. And `binary_heap.mojo` was
already failing as an in-file `codegen` finding in the baseline for this exact
reason, so the module that carries 35 files cannot be compiled by this backend
today, whatever its export table says.

## 4. Probe B — a demand-pruned import closure

**Method.** A second copy, `.tmp/std_patched`, identical except that line 27 of
`std/collections/__init__.mojo` — the `from .binary_heap import BinaryHeap` — is
deleted. This is **not a proposed stdlib change** (it removes a public
re-export). It is the counterfactual "what do these 35 files hit when
`binary_heap.mojo` is not in their closure at all?", which is the ceiling of any
closure-pruning scheme and an upper bound on every export-side fix: if a file
fails when the module is *absent*, giving the module a symbol cannot help it.

**Result, the same 35 files, cold CAS:**

    CODEGEN/DEPENDENCY  35   … dtype.mojo: MLIR construct x26,
                                _assembly.mojo: other refusal x9
    [arm64] 35 files: PASS=0 not-pass=35

**Ceiling: 0 of 35.** All 35 leave the gate — and every one of them lands on
`dtype.mojo`'s MLIR constructs or `_assembly.mojo`'s `inlined_assembly`, which
are `FORMAL_known_limits.md` §2 and §1.1: **documented true limits of the
target, and the r2 map's rows 1 and 6.** Per-file, the change is total and
uniform:

    std/_plugin/__init__.mojo          binary_heap.mojo -> dtype.mojo
    std/_plugin/_impl.mojo             binary_heap.mojo -> dtype.mojo
    … 35 of 35 changed; 0 unchanged.

## 5. Probe C — what `BinaryHeap`'s real importers actually call

There are exactly three files in the tree that use the type, and none of them
is in the sweep's default scope (`test/` is not one of
`formal_sweep.py`'s `DEFAULT_STDLIB_SUBTREES`), which is why they never
appeared in the 38:

| file | calls | baseline terminal cause |
|---|---|---|
| `test/collections/test_binary_heap.mojo` | `push`/`pop`/`peek`/`clear` on a `BinaryHeap[Int]` | `random.mojo: Rng_rand_scalar: 'DType' has no home` |
| `test/collections/test_binary_heap_assert_empty_peek.mojo` | `BinaryHeap[Int]()`, `.peek()` | **`binary_heap.mojo` — the gate** |
| `test/collections/test_binary_heap_assert_empty_pop.mojo` | `BinaryHeap[Int]()`, `.pop()` | **`binary_heap.mojo` — the gate** |

So two of the three genuinely are behind the gate, and they are the one place a
concrete instantiation could have paid. Measured, cold CAS, same probe as §3:

    [arm64] 3 files: PASS=0 not-pass=3
    … _assert_empty_peek.mojo: binary_heap.mojo: len(self._data) — this slot's
      DECLARED type is 'List[Self.T]' …
    … _assert_empty_pop.mojo:   binary_heap.mojo: len(self._data) — …

**Ceiling: 0 of 2.** Satisfying the gate moves both files one level deeper, into
`binary_heap.mojo`'s own body, and neither builds. The third was never behind
the gate at all.

## 6. The verdict, and what the sweep should print

**No change to the export rule.** Not a per-instantiation export, not a type
descriptor, not an instantiation-keyed CAS entry. Each is measured above at 0
files, and each would add a name to an export table on the strength of an
assumption (`34/35 never use it`, `binary_heap.mojo` does not lower) that is
true today and would silently stop being true the first time a stdlib importer
actually calls the template — at which point the wrong body binds, which is the
one failure `doc/ABI.md`'s rule exists to refuse.

What landed instead (`b6a94d35`) is the number that decides the row, printed
next to it on every run: **`uses:` — how many of a module's blocked files name
anything it declares.** It is computed from `reflect.export_exclusions`, the one
export rule `no_public_api_reason` also reads, so the names searched for are the
names the refusal is about. It changes no classification and no rate.

### For whoever owns the sweep's semantics (`task:formal-sweep-2`)

There is a larger question here that is **not** mine to decide, and it is worth
being precise about because it is the same shape as the argparse decision in
r2 §3.1. All 38 findings of this cause are `codegen/dependency`, so all 38 sit
in the rate's denominator:

    now        112 pass / 481 denominator = 23.3%
    if the 38 moved out (as `not-answerable/host-import` is kept out)
              112 pass / 443 denominator = 25.3%

**+2 points of rate for 0 files of coverage**, because the 38 are behind two
documented limits (§4). A refusal that is a property of the import GRAPH rather
than of the swept file is the same kind of fact as "this target has no
subprocess": it belongs in a class of its own, out of the denominator, with its
own row — and with the `uses:` number beside it, because for this cause the
count of files that actually reference the refused module is 1, and that file
is the re-export.

I have not made that change. `tools/formal_sweep.py` is not in my claim and the
denominator is the sweep owner's decision.

## 7. Reproducing this

Every number above came from a throwaway harness in `.tmp/` (a copy of the
stdlib per probe, a cold `GMOJO_HOME` per run, and
`tools/formal_sweep_causes.py` over the baseline log). Two traps in it are worth
recording, because each one produced a run whose summary line looked exactly
like a result:

- **The sweep's children do not inherit a patched `module_loader`.** It spawns
  `python3 fire.py build` per file, so setting `module_loader.STDLIB_PATH` in
  the parent changes only the roots the parent computes — a file compiled
  *directly* saw the patched stdlib while the same file reached as a *nested
  dependency* saw the real one, and 15 of the 35 stayed on `binary_heap.mojo`
  for that reason alone. `MOJO_STDLIB` in the environment is the seam that works
  for both (`module_loader._find_stdlib_path` honours it, and it is what
  `formal/imports.py` pass 4 asks).

- **A `_`-prefixed probe declaration does not satisfy the gate**, so a probe
  written as `_binary_heap_export_probe` reports `binary_heap.mojo: module
  exports nothing x35` and looks like the measurement failed. It is
  `reflect.EXCL_PRIVATE` doing its job.

## 8. What is left

Nothing in the export rule. If `binary_heap.mojo` is ever to be usable by an
importer, the blocker is not its export table and not its callers — it is that
`len(self._data)` on a `List[Self.T]` slot has no representable value on this
path (§3, and the in-file `codegen` row the baseline sweep already prints for
it). That is a field-initialisation/value-model question, it is not in this
claim, and `FORMAL_class_assigns_its_fields_in_init.md` /
`bugs/FORMAL_value_model_*` are the neighbourhood.

Verification run by the worker who wrote this: the two probe sweeps (35 files
each, three of them) and the full 637-file baseline, all through
`tools/memslot.py --gb 8`, plus `python3 test_refusal_taxonomy.py` (33 checks)
and `python3 tools/formal_sweep_causes.py` over the baseline log. No gate, no
bootstrap — the change is one reporting column in a `tools/` script and its
test.