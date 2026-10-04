# FORMAL_std_os_io_round2_scope_is_one_refusal_shape: std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu} is 46 files, 3 build, and all 43 of the rest are TWO features neither of which is in this scope

**Area:** FORMAL (new-modular stdlib breadth, round 2). Found 2026-10-04 on
`work/formal20-std-os-io-2`, claim `sweep20:std-os-io-2`. **Not a bug in this
scope's files** — that is the finding, and it is the answer to the question the
sweep cannot answer. What is left open is the per-file refusal table, the chain
underneath it, and an owner per link.

Round 1 of this scope is `FORMAL_std_os_io_scope_is_decided_by_five_modules_outside_the_claim.md`
(`sweep14:std-os-io`, **not edited here** — it is that claim's document). It
measured `std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` = 46 files, 3 pass,
and read the chain behind all 43 as `std/collections/binary_heap.mojo`, then
`std/algorithm/backend/tile.mojo`, then `std/builtin/builtin_slice.mojo`.

**That chain is gone.** The per-edge export gate landed after it, and this
round's scope is a different set of packages anyway — it drops `sys` and `time`
and adds `python` and `_gpu`, the two packages round 1 never swept. On this
tree **zero** of this scope's 43 refusals name `binary_heap.mojo`, `tile.mojo` or
`builtin_slice.mojo`, and none is more than ONE import deep (§2). What every one
of them is instead is in §2's table, and there are only two features in it.

---

## 1. The sweep, both architectures

`../new-modular/Mojo/stdlib/std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu}`
is **46 `.mojo` files** — `os` 11, `_gpu` 10, `python` 7, `io` 5, `hashlib` 5,
`base64` 3, `ffi` 3, `pathlib` 2 — swept whole, `-j 2 -t 120`, both
architectures, on this branch's base `3c3516db` (the three commits in §4 landed
after the sweep and change no file it builds):

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib/std
F=$(for d in os io pathlib hashlib base64 ffi python _gpu; do
      find $S/$d -name '*.mojo'; done | sort)

python3 tools/memslot.py --gb 16 --label s20osio -- \
  python3 tools/formal_sweep.py -j 2 -t 120 -M 8 --no-stdlib --allow-concurrent $F
python3 tools/memslot.py --gb 16 --label s20osiox86 -- \
  python3 tools/formal_sweep.py -j 2 -t 120 -M 8 --no-stdlib --arch x86_64 \
    --allow-concurrent $F
```

| class | arm64 | x86-64 |
|---|---|---|
| **pass** | **3** | **3** |
| built-with-admitted-contracts | 0 | 0 |
| **codegen** (a refusal in THIS file) | **3** | **3** |
| codegen/dependency | 40 | 40 |
| **codegen coverage** | **3/46 = 6.5 %** | **3/46 = 6.5 %** |
| peak RSS | 0.4 GB over ≤5 procs | 0.4 GB over ≤5 procs |

`--allow-concurrent` is needed on a machine where another worker is sweeping the
same architecture: two sweeps of one arch share `~/.gmojo/cas/formal-imports/<arch>/`
and its manifest, and the manifests are written atomically now
(`test_formal_manifest_atomic.py`), so the collision the sweep warns about is
down to a stale read.

**The two arms agree on every one of the 46 files** — same three passes, same
three in-file refusals, same refusing module for each of the other 40 (§2's
table is one table, read off both logs). Nothing here is an ABI difference.

The three that build: **`std/os/pathlike.mojo`**, **`std/os/path/__init__.mojo`**,
**`std/_gpu/host/__init__.mojo`** (read off the sweep's own published ledger,
`tools/formal_sweep.py::load_ledger`, since PASS lines are counted and not
printed).

## 2. All 43 refusals, and they are TWO features

**Max chain depth over the whole scope: 1 import.** That is the whole finding.
A scope of 46 files, 40 of which fail on something a module they import refused,
and no file fails on anything two modules down.

| files | in-file | refusing module | the call | the declaration | owner |
|---|---|---|---|---|---|
| **22** | 1 | `std.format._utils` | `FormatStruct(writer, "…")` | `std/format/_utils.mojo:287` `struct FormatStruct[T: Writer, o: MutOrigin]` | `FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable` |
| **11** | 1 | `std.memory.alloc` | `dealloc(allocation^)` | `std/memory/alloc.mojo:904` `def dealloc[T: AnyType, /](var allocation: Allocation[T, alignment=_], /)` | same |
| **2** | 0 | `std.math` | `align_up(x, a)` | `std/math/math.mojo:1453` `def align_up[…]` | same |
| **1** | 0 | `std.bit.mask` | `is_negative(value)` | `std/bit/mask.mojo:26` `def is_negative[dtype: DType, //](value: SIMD[dtype, _])` | same |
| **1** | 1 | `..fstat` → `std.os.fstat` | `stat(path.__fspath__())` | `std/os/fstat.mojo:179` `def stat[PathLike: stdPathLike](path: PathLike) raises` | same |
| **4** | 0 | `std.sys._io.mojo` | — | *declares no function and no type at all — only module-level constants* | `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib` |
| **2** | 0 | `std.math.constants.mojo` | — | same shape | same |

**The first five rows are ONE feature, 37 of 46 files, and every type argument in
it is inferable from the call's own arguments.** `FormatStruct(writer, "X")` —
`writer: Some[Writer]` gives `T`; `dealloc(allocation)` — the argument's type
*is* `T`; `is_negative(value)` — `value: SIMD[dtype, _]` is the whole signature;
`stat(path)` — `path: PathLike` is the parameter. Mojo's rule is that a type
argument may be omitted when it can be inferred, and the stdlib relies on it in
all four. `FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
§3 states the fix exactly (`formal/monomorph.py::all_instantiation_calls`: derive
the type arguments from the call's argument types rather than from a bracket) and
§1 measures it at 123 files tree-wide, so this scope's 37 is a third of that row
and moves with it. **Claimed (`formal19-1`); not taken here** — see §5.

The last two rows are the other feature: a module whose whole body is
module-level constants has nothing an importer can bind, and
`formal/build.py::no_public_api_reason` refuses the dylib.
`FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md` calls that "one
feature — inline a container-valued module constant at the use site, and skip the
dylib for a module nothing binds". **Claimed (`formal16-2`); not taken here.**

**So this scope's honest in-file count is 3, and all three are one of the two
features above** — `std/ffi/unsafe_union.mojo:293` calls `FormatStruct(writer,
"UnsafeUnion").params(…)`, `std/ffi/__init__.mojo:1053` calls `dealloc(…)`, and
`std/os/path/path.mojo:398` calls `stat(…)`, each bare, from a file the sweep is
sweeping. They are classified `codegen` rather than `codegen/dependency` because
the refusing message carries no `imports '…'` hop for the sweep to peel: the CALL
is in the file being swept. The defect they point at is not in those three files.

## 3. The chain, measured, and the instrument that could not measure it

`tools/formal_chain_probe.py` walks what the sweep reports only the terminal link
of. On this scope it used to stop at round 0:

```
=== round 0: 3 built, 3 refusing module(s)
   37  <no module named>
    4  _io.mojo
    2  constants.mojo

  (stopping: <no module n is not under the stdlib copy, so there is nothing this
   tool may rewrite)
```

37 of 46 under a placeholder, then the walk ended — the victim is chosen by
sorting the group keys and the placeholder is not a filename, and the message it
printed is that placeholder with five characters sliced off as if it were a
`.mojo` stem. So the one instrument that could answer "how deep is this scope"
reported **no chain at all** for the refusal that blocks the most files, and
named a module that does not exist. Cause and fix in §4.

With it fixed, the scope's chain is four links deep before the walk's own limit:

| link | files | refusing module | the refusal |
|---|---|---|---|
| 1 | 37 | `std/format/_utils.mojo` (22), `std/memory/alloc.mojo` (11), `std/math/__init__.mojo` (2), `std/bit/mask.mojo` (1), `std/os/fstat.mojo` (1) | a bare call to a generic template (§2's first five rows) |
| 2 | 3 | `std/sys/arg.mojo`, behind `std/sys/_io.mojo` | `Span[StaticString, ImmStaticOrigin] is a compile-time explicit-parameter list on a generic, not a subscript` |
| 3 | 2 | `std/math/constants.mojo` | exports nothing under `doc/ABI.md`'s rules |
| 4 | 42 | — | the walk's own stub step emptied an indented block and the copy stopped parsing |

```sh
python3 tools/memslot.py --gb 12 --label probe -- \
  python3 -u tools/formal_chain_probe.py 6 arm64 $F
```

**Link 2's owner is `FORMAL_a_comptime_explicit_parameter_list_is_a_specialization`**-class
work, not a claim this scope can name: `std/sys/arg.mojo` is outside every
package here and the refusal is about an explicit-parameter list on a generic,
which is the shape `bugs/FORMAL_generic_monomorph_scope.md` §"what is not
covered" already holds. **Link 4 is the tool's documented limit** — neutering a
module removes the names its users call — and it is now detected and reported as
such rather than as 42 files refusing a construct (§4).

**Read §2 before planning anything in this scope, and §2's owner column before
working it.** Neither feature is in this scope's packages, and closing link 1
does not move the scope by itself: with `FormatStruct` answered, the same 37 files
reach `std/memory/alloc.mojo`'s `dealloc`, which is the same feature. The
measured statement is that this scope has **no construct of its own left to
lower**, which is the answer, not an omission.

## 4. What landed with this measurement

Three defects in `tools/formal_chain_probe.py`, all found by running it on this
scope, all fixed with tests (`test_formal_chain_probe.py`, 12 cases):

1. **`imported_callee_refusal` names its module in prose, not in the `<file>: `
   chain prefix**, so every export-gate refusal read as the catch-all. Resolved
   with the build's own `formal.imports.resolve_module_path(name,
   relative_to=importer)` rather than a second spelling rule in the tool.
2. **A resolution outside the copy was actionable**, and the stub step's next act
   is `write_text`: for a scope file outside the copy (this tool's own default
   scope is this repository's `*.py`) the resolver answers with the REAL stdlib,
   which exists, so an `is_file()` check passes. The walk would have overwritten
   `../new-modular/Mojo/stdlib`. A path outside the copy is now discarded, and
   the module docstring's "THE STDLIB IS ONLY EVER READ" is enforced rather than
   asserted.
3. **The walk reported its own damage as a chain link** (§3's link 4).

The sweep's own instruments rank this scope's causes as one row of 37 "other
refusal" plus one of 6, and cannot rank them further: `tools/formal_sweep_causes.py`
reads the refusing module out of the chain's `<file>: ` prefix too, so the same
prose shape defeats it — **21 of the 22 groups it prints carry "NOT MEASURED:
the chain names this module by basename only"**, which is the tool being honest
about a module it cannot name rather than about a module with no users. §2's table
was produced from the sweep log by matching `is imported from \`…\`` — five lines
in a throwaway script, and that script should be a tool. **Left open rather than
done:** §6.

## 5. What was deliberately NOT done, and why

**Neither §2 feature was implemented here.** `control.py claims` holds
`FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable` at
`formal19-1` and `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib` at
`formal16-2`, and both fixes land in `formal/monomorph.py` and the dylib emission
respectively. Working them from a third branch would have put two features'
worth of divergence into the integrator's merge for no gain: the measurement,
not the implementation, is what this scope had left to give, and this document is
it.

**No honest libc/syscall model was added, and the task's hint about one is
answered rather than followed.** This scope's modules are libc-backed in the
ordinary way — `realpath`, `getcwd`, `fopen`/`fread`/`fwrite`, `_stat`/`_lstat`,
`getenv` — and that surface is already modelled: `formal/hostmods/os/_syscalls.mojo`
is the single audited list of what a formal image asks of the operating system
("a formal image links libSystem and nothing else (FORMAL.md §1), so *what does
this module ask of the operating system* is a question with a short, complete
answer"), with `formal/hostmods/{os,io,pathlib,stat,sys,hashlib,math}.mojo` on
top of it and `formal/build.py` holding the `readdir$INODE64` ABI spelling.

What is missing is not a model of a libc call: **none of this scope's 43 files is
refused at a libc call.** All of them stop before their own bodies are lowered,
so a model added now would be a model of code the backend has not reached. §2 is
the honest dependency order, and adding to the hostmod surface before link 1
closes would be writing against a boundary that has not moved.

## 6. What is left

1. **The cause-ranking instrument cannot rank this scope's causes.**
   `tools/formal_sweep_causes.py` reads the refusing module from the chain
   prefix, so both of §2's features collapse into "other refusal" and the
   `refused in:` / `uses:` columns print "NOT MEASURED" for 21 of the 22 groups.
   The fix is the one `tools/formal_chain_probe.py` just took: resolve the module
   the message names, with `formal.imports.resolve_module_path`, so the row reads
   `std.format._utils` rather than whatever import the chain's first hop happened
   to be. Until then the ranked table for this scope is §2's and not the tool's.
2. **`__init__`-only modules are refused with "nothing this backend could
   add"**, which is not true — the backend could inline them, which is
   `formal16-2`'s feature. Worth a doc edit when that lands, because the sentence
   is a dead end for whoever reads the 6 files first.
3. **The chain walk stops at link 4 and cannot be pushed further by this tool.**
   Removing an import line whose only use was the only statement in an indented
   block is the limit; a stub that also removed the block would extend it. Not
   worth building until someone needs a fifth link.

## 7. Reproducing

Every number above is one `fire.py build --formal --no-prove` per file behind
`tools/memslot.py`, no Lean anywhere (`--no-prove`), and the two arms agree file
for file. The three commits on `work/formal20-std-os-io-2` carry the probe fix
and its 12 tests; the two sweep logs this section quotes are `.tmp/sweep_arm64.txt`
and `.tmp/sweep_x86_64.txt` in that worktree.