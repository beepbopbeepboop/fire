# `std/{builtin,math,bit,random,format,utils}`: two root causes fixed, and the six refusals that are not mine to lift

**Slice:** the 68 `.mojo` files under
`../new-modular/Mojo/stdlib/std/{builtin,math,bit,random,format,utils}`
(builtin 38, math 6, bit 3, random 4, format 4, utils 13).
**Claim:** `sweep14:std-builtin-math` on `work/formal14-std-builtin-math`.
**Status:** swept complete on BOTH architectures (`tool` class 0), two root
causes fixed with tests, and the six remaining in-file refusals each measured
against what is behind it. **The headline is that this slice has no unowned
large row and the coverage number did not move** — §3 says why, and §2 says
what the two fixes were worth, which is not coverage.

Overlaps two finished maps, and reads with them rather than instead of them:
`FORMAL_sweep_work_map_2026-10-02_std-a.md` (`std/{builtin,collections,memory,
algorithm,bit}`) and `…_std-b.md` (`std/{os,pathlib,io,format,hashlib,base64,
random,math}`). §5 **corrects** std-a §4 on two of its seven rows; the
correction is the point of filing this.

---

## 1. The run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120            <the six directories> \
  > bugs/sweeps/sweep14-std-builtin-math-arm64.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120 --arch x86_64 <the six directories> \
  > bugs/sweeps/sweep14-std-builtin-math-x86_64.txt 2>&1
```

Logs committed; `peak 0.3 GB` against the 8 GB reservation on both arms, and
**the two architectures agree exactly, file for file**, which is what
`…_b7.md` §2.5 measured over 542 files and is re-measured here over 68.

`bugs/sweeps/sweep14-std-builtin-math-x86_64-BEFORE-the-fix.txt` is the same
x86-64 slice before the two commits below. It is x86-64 only because the arm64
sweep lock was held by another worker's slice for the whole pre-fix window and
`formal_sweep.py` refuses to start rather than share
`cas/formal-imports/<arch>/` — the runner's own `--allow-concurrent` exists for
that and is not needed here because the post-fix arms agree.

| class | arm64 | x86-64 |
|---|---|---|
| **pass** | **9** | **9** |
| built-with-admitted-contracts | 0 | 0 |
| **codegen** (a refusal IN this file) | **7** | **7** |
| **codegen/dependency** (refused one level down) | **52** | **52** |
| not-answerable / backend-crash / tool | 0 | 0 |
| **codegen coverage** | **9/68 = 13.2 %** | **9/68 = 13.2 %** |

**Identical before and after both fixes**, on both architectures. §2 says what
the fixes were worth instead, because "coverage did not move" read alone would
be a reason to believe the two commits were worth nothing, and they were — just
not in files.

The 9 passes: `builtin/{__init__,_closure,floatable,identifiable,inline_level,
swap}.mojo`, `math/constants.mojo`, `utils/{_select,_visualizers}.mojo`.

`python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep14-std-builtin-math-arm64.txt`:

| files | in-file | cause |
|---|---|---|
| 40 | 0 | one-field mutator has no convention to write its answer back — `binary_heap.mojo`, and `uses:` reads **0 of 40** name anything it declares |
| 11 | 1 | other refusal — `builtin_slice.mojo` (`FORMAL_builtin_slice_optional_field_is_a_frame_holder`, `formal13-3`) |
| 2 | 2 | method call on a value receiver (`format/repr.mojo`, and one more after §2.2) |
| 1 each | 1 | `...` body (`builtin/len.mojo`) · a method on a multi-field struct where a descriptor is meant (`builtin/none.mojo`) · module exports no public functions (`utils/_select.mojo`) · MLIR construct (`builtin/type_aliases.mojo`) · comptime does not fold (`math/polynomial.mojo`) · cannot be lowered (`builtin/float_literal.mojo`) |

## 2. What landed, and what it was worth

### 2.1 `formal: a converting @implicit __init__ is not the mutating overload's twin` (5f7d7c54)

`std/builtin/float_literal.mojo` was refused on both architectures with
**"FloatLiteral.__init__() both changes its receiver and returns a value"** —
about a method that changes no receiver at all. One root cause with two
readers, both asking about the LIFTED name `FloatLiteral___init__` that
`method_function_name` gives every overload of one method:

* `build._return_the_receiver` applied the write-back entry `__init__(out self)`
  earned to `@implicit def __init__(_value: IntLiteral[_]) -> FloatLiteral[…]`,
  whose first parameter is an ordinary argument. It refused a function that
  mutates nothing, and named "split it into a method that changes the receiver
  and returns nothing, and one that reads it" as the fix for a method that was
  never a mutator. With the refusal lifted it would have rewritten a bare
  `return` into `return self` and appended a second one — naming a parameter the
  function does not have, which is the build-dependent word this path refuses
  everywhere else.
* `model.struct_init_shapes` asked a CLASS-WIDE `struct_receivers` set, built
  from `method_receiver_name`, which takes the first parameter's name *whatever
  it is called*. The converting constructor's `_value` joined the class's
  receiver set and was then skipped as "the receiver", so the overload counted
  **0 required parameters** and `Cell()` was refused as AMBIGUOUS against
  `__init__(out self)` — with the message reading `(0 required; 0 required)`
  for two constructors of arity 0 and 1.

**Blast radius, measured rather than argued**: walking every method in this
repository and the stdlib (**5405**), the **8** whose first parameter is not a
receiver spelling are all `@implicit` (or positional-argument) converting
constructors of one-field structs — `pointer`, `origin`, `span`, `bitset`,
`list`, `string_span`, `float_literal`, `variadics`. Nothing else in the corpus
changes.

**Worth: 0 files.** `float_literal.mojo` advances to
`self.__int_literal__().__int__(…)` — a method call on a call result, refused
because this path has no inference that answers "which struct does
`self.__int_literal__()` hold" and dispatches by name. That is a real limit and
it stays a `codegen` row. **What the fix was worth** is a refusal whose stated
reason was false, removed from a class the corpus reaches with 8 declarations,
and a rewrite that could have injected `return self` into a function with no
receiver. `…_std-a.md` §4 called this row "a value-model decision about
one-field mutators, not a lowering"; §5 corrects that.

### 2.2 `formal: unsafe_load is value()'s other name, so route it to the same load` (f0b30e33)

`std/utils/_serialize.mojo` was refused on both architectures with
**"p.unsafe_load() is a method call on a value … 'unsafe_load' is not one of
those methods of those receivers, so adding it to either table would be a
guess about what it means on 'int'"** — about `var p = ptr.unsafe_value()`,
whose value is a pointer. `UnsafePointer.unsafe_load(i = 0)` IS `p.value()`
with the index defaulted, so the stdlib spells the read this path already
lowers **116 times**, every one on a pointer, and the name was in neither the
dereference table nor the refusal tables.

The pointer value model answers it for `.value()`: the pointee's declared
width, with the right refusal for every pointee it cannot load (float, blob,
struct, no width). `unsafe_load` now reaches the same
`model.dereference_lowering`, through `IDENTITY_VALUE_METHODS` rather than
`DEREFERENCE_METHODS` — the latter's arm claims "is a load from the address
the receiver holds" even for a receiver not established to be a pointer, which
is true of `unsafe_value` (genuinely ambiguous) and false of `def read_it(n:
Int)`. And `model.dereference_operands_refusal`, shared, replaces a private
f-string per backend: `unsafe_load(i)` is a read at an **OFFSET**, `i = 0` is
its declared default, and "takes no arguments" was a true sentence aimed at a
reader who wrote the ordinary spelling and nothing wrong.

**Worth: 0 files, and the file's next refusal is now the true one** — the
pointee is `Scalar[dtype]` with `dtype` a comptime parameter, so no width is
established, which is §4's generics limit rather than a missing table entry.
The family count for "method call on a value" drops **x3 → x2** on both
architectures. The `width=` bracket is deliberately NOT answered and is not an
argument case: a bracketed callee is a `SubscriptExpr`, never reaches this arm,
and is refused by the pre-existing bracketed-callee rule; it is pinned as such.

## 3. Why the coverage number did not move, and what would move it

**52 of the 59 non-passes are refused in a module they import, and 51 of those
52 are three modules' refusals — none of them in this slice, and two of the
three claimed elsewhere.**

| blocking module | files here | why it is not this slice's |
|---|---|---|
| `collections/binary_heap.mojo` | **40** | `FORMAL_binary_heap_mojo_after_the_len_value.md` §2 has measured that fixing every codegen refusal in that file moves **0** of its row: the dylib export gate fires behind them (`binary_heap.mojo` declares only a generic struct template, and `doc/ABI.md` §Generics is explicit that a generic is not one boundary symbol). The row's terminal cause as reported here is `BinaryHeap.pop()` — §3 row 0 of that doc, "the cheapest real step" — but **the doc is explicit that it moves no files**, and its recommendation is not to start it. The file also lives in `std/collections`, which `formal14-std-collections` holds |
| `builtin/builtin_slice.mojo` | **11** | `FORMAL_builtin_slice_optional_field_is_a_frame_holder` — **`formal13-3`**. `StridedSlice___init__` rebinds its receiver, so a returned frame cannot cross a dylib boundary |
| `utils/_select.mojo` | **1** | mine, and §4 row 6 |

**So the answer to "what would move this slice" is: not codegen work in these
six directories.** The 40 need a monomorphisation project and the 11 need
`formal13-3`. Both are already written down with their measurements; this doc
adds the per-file count for this slice and nothing else.

## 4. The six in-file refusals, each measured against what is behind it

| file | the construct | what is BEHIND it, measured |
|---|---|---|
| `builtin/len.mojo` | a `...` body where this path needs instructions. The body is `@unavailable`'d, so the language itself is saying "declared, not provided" — a third spelling beside a trait method, which this path accepts | **giving that `...` a body does NOT gain the file.** Measured: with `return 0` in place of `...`, the next refusal on both architectures is `value.__len__()` inside `len[T: Sized]` — "a string representation that carries a length — a value-model change, shared by both backends and the Lean proof" (`FORMAL_string_value_model`, `formal3-8-r2`). §5 corrects `…_std-a.md` §4 on this |
| `builtin/none.mojo` | `writer.write_string("None")` on a `Some[Writer]` — a multi-field struct, so the receiver is a frame address | deliberate and correct (`model.WRITER_METHODS`): lowering it as the lowered `write` would pass a frame address as fd(2) and the program's output would be *missing* rather than wrong-looking. `WRITER_METHODS` carries the measurement. Needs a `Writer` value model |
| `builtin/type_aliases.mojo` | `comptime Never = __mlir_type.\`!kgen.never\`` — an MLIR TYPE bound to a module-level `comptime` | `formal2-mlir-comptime` / `formal-mlir-gpu`; `FORMAL_known_limits.md` §2. The file is 23 lines and two bindings |
| `format/repr.mojo` | `value.write_repr_to(string)` on a type parameter | fully written up in `…_std-b.md` §6: a generic BODY is never specialized, and the file has a second wall behind it (`return string^` returns a 3-field `String`) |
| `math/polynomial.mojo` | `comptime num_coefficients = len(coefficients)` over a comptime parameter | `…_std-b.md` §6, same next step: `FORMAL_known_limits.md` §1.2 (monomorphisation) |
| `utils/_select.mojo` | the dylib exports nothing: every declaration is private | §6 below. 1 of 1 blocked file uses it, so `formal_sweep_causes.py` calls the row work |

`_serialize.mojo` and `float_literal.mojo` were the other two; §2 is what
happened to each.

## 5. Two corrections to `…_std-a.md` §4

That map's §4 lists seven `codegen` rows for its slice. Two of them are stated
in a way this slice's measurements show to be wrong, and both are wrong in the
direction that makes them look like more work than they are.

**`builtin/float_literal.mojo` — "The fix is a value-model decision about
one-field mutators, not a lowering."** It is not a value-model decision at all:
the method the refusal names has **no receiver**, because the write-back entry
that reached it belonged to a different overload of the same lifted name. Fixed
in 5f7d7c54, and the file's next refusal is a call on a call result. The
generalisation worth carrying: **an entry in a table keyed by a lifted name is
not evidence about the function it is looked up on**, and the `param_convs`
guard that saved this one is luck rather than design.

**`builtin/len.mojo` — "Cheap, and the shape is the language's own."** Cheap,
yes; but the file is not gained by it. §4 above measures the wall behind it.
The row is real and the fix is real; the coverage claim attached to it is not,
and a reader who took §4 at its word would do the work and find the file still
refused.

## 6. The private-import row: 147 library files, measured, and partly claimed

`builtin/simd_length.mojo:15` is `from std.utils._select import
_select_register_value as select` — an import of a **private** name across a
module boundary, which is exactly what `doc/ABI.md` excludes from a dylib's
export trie, so `_select.mojo` builds as a library with nothing to export and is
refused. That is the right refusal for the right reason; the finding is that
the **stdlib does this constantly**.

Walking every `from std.X import …` in `../new-modular/Mojo/stdlib`:

| | count |
|---|---|
| library files importing a private name from another stdlib module | **147** |
| the same under `stdlib/test/` | 43 |

By source module, the largest: `collections/string/string_span` 19,
`builtin/dtype` 11, `format/_utils` 11, `ffi` 9, `sys/info` 9, `utils/_select`
5, `io/io` 5, `pathlib` 5, `simd` 4, `builtin/constrained` 4, `math/math` 4,
`builtin/variadics` 4, `time/time` 4 — and in **this slice**:
`builtin/format_int` 3, `builtin/range` 2, `builtin/_startup` 2, `bit/bit` 1,
`builtin/_format_float` 1, `builtin/int` 1, `builtin/debug_assert` 1.

**Almost none of the 147 are reachable today**, because the rows above them
(§3) fire first: 40 of this slice's 68 files never get as far as an import
failure. **1 of 68 does** (`simd_length.mojo`), and `formal_sweep_causes.py`
reports `uses: 1 of 1 … every blocked file uses it, so the row is work`.

**Whose it is, honestly:** the export rule is `formal13-3`'s and `formal13-5`'s
(`FORMAL_dylib_export_loops_and_frame_bounds`,
`FORMAL_dylib_export_audit_adds_a_second_underscore`, `FORMAL_per_export_contracts`),
so this doc does not claim it and does not propose a rule change. What it adds is
the number, which no doc in `bugs/` carries: **147 library files**, so the row
is a project about the ABI and not a per-file fix, and whoever picks it up
should know the size before designing for one file. There are two candidate
answers and both are ABI decisions: honour an explicit import alias (the
importer named the symbol, so it *is* for another module), or let a module with
no public exports build as an empty library and fail at the LINK line instead of
at the build.

## 7. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
D=../new-modular/Mojo/stdlib/std
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120 $D/{builtin,math,bit,random,format,utils}
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 120 --arch x86_64 $D/{builtin,math,bit,random,format,utils}
python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep14-std-builtin-math-arm64.txt

# one file, no sweep, both architectures
for a in arm64 x86_64; do
  python3 fire.py build --formal --no-prove --backend=$a -o .tmp/o \
    $D/builtin/float_literal.mojo
done

# the tests that cover §2
python3 test_formal_run.py \
  an_implicit_converting_init_next_to_a_mutating_one_is_not_a_mutator \
  a_mutating_init_keeps_its_write_back_beside_a_converting_one \
  both_arch_deref_unsafe_load_is_the_same_load_as_value \
  deref_refuse_unsafe_load_with_an_offset \
  deref_refuse_unsafe_load_bracketed_width \
  deref_refuse_unsafe_load_on_a_non_pointer_receiver
python3 test_formal_value_model.py
```

Editing anything under `formal/`, the parser or `mojo/middle/` invalidates the
sweep CAS (`tools/formal_sweep.py`'s own bytes are in every key), so a
re-measurement of these numbers is a real rebuild of the slice.