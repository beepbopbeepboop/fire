# FORMAL_std_os_io_round2_scope_is_one_refusal_shape: std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu} is 46 files, 3 build, and all 43 of the rest are TWO features neither of which is in this scope

**Area:** FORMAL (new-modular stdlib breadth, round 2). Found 2026-10-04 on
`work/formal20-std-os-io-2`, claim `sweep20:std-os-io-2`. **Not a bug in this
scope's files** — that is the finding, and it is the answer to the question the
sweep cannot answer. What is left open is the per-file refusal table, the chain
underneath it, and an owner per link.

**Status (2026-10-04, `work/formal25-5`): §6 item 3 is CLOSED — the stub step no
longer stops the walk, and it was the stub step, not the chain.** The document's
own reading of why was wrong by half and right by half: the shape it named (an
import that is the *only statement* of an indented block) is **not** a parse
error in this dialect, and the shape it did not name (a parenthesised import
spanning lines) is. One repair covers both, and with it the walk measured **five
links nobody had measured** instead of three (§0.2). §6 items 1 and 2 are
unchanged and item 4 was filed by its own branch
(`FORMAL_a_dotted_import_resolves_to_a_nearer_leaf`, `formal21-1`), so the two
features §2 names are still `formal19-1`'s and `formal16-2`'s and the per-file
table is still §2's. §0.2 is what changed, and §0.1 (item 1) before it.

**Status (2026-10-04, `work/formal21-6`): §6 item 1 is CLOSED — the instrument
can now rank this scope's causes, and the table it prints is measured rather
than 21 rows of `NOT MEASURED`.** §6 items 2 and 3 are unchanged and item 4 was
filed by its own branch (`FORMAL_a_dotted_import_resolves_to_a_nearer_leaf`,
`formal21-1`), so **this document has nothing left of its own**: the two
features §2 names are `formal19-1`'s and `formal16-2`'s, the per-file table is
§2's, and the only thing this document asked for was an instrument that can
answer the question. §0.1 is what changed.

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
architectures, on this branch's base `3c3516db` (this branch's four commits all
land after the sweep, and §4's change no file a build reads):

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

With it fixed the walk names every module and gets three links deep before its own
limit stops it. Verbatim from `.tmp/probe3_arm64.txt`:

```
=== round 0: 3 built, 8 refusing module(s)
    19  std/format/_utils.mojo        4  _io.mojo
    11  std/memory/alloc.mojo         3  std/_gpu/_utils.mojo      <- §6.4, MISATTRIBUTED
     2  constants.mojo                2  std/math/__init__.mojo
     1  std/bit/mask.mojo             1  std/os/fstat.mojo
  stubbed _io.mojo (1 file(s)) and dropped import lines from 5 file(s)

=== round 1: 3 built, 8 refusing module(s)      _io.mojo -> arg.mojo (4)
=== round 2: 3 built, 7 refusing module(s)      arg.mojo -> the next 2 links
=== round 3: 3 built, 0 refusing module(s), 43 unmeasurable (the stub step left the copy unparseable)
```

**Round 3's last line was the walk measuring its own edit, and §0.2 is what fixed
it and what measured the five links behind it.** It read here as "this tool's
limit"; it was one deleted line of a parenthesised import.

| link | files | refusing module | the refusal |
|---|---|---|---|
| 1 | 34 | `std/format/_utils.mojo` (19), `std/memory/alloc.mojo` (11), `std/math/__init__.mojo` (2), `std/bit/mask.mojo` (1), `std/os/fstat.mojo` (1) | a bare call to a generic template (§2's first five rows) |
| 2 | 4 | `std/sys/arg.mojo`, behind `std/sys/_io.mojo` | `Span[StaticString, ImmStaticOrigin] is a compile-time explicit-parameter list on a generic, not a subscript` |
| 3 | 2 | `std/math/constants.mojo` | exports nothing under `doc/ABI.md`'s rules |
| — | 43 | — | the walk's own stub step dropped the head of a parenthesised import and the copy stopped parsing — **§0.2 closed this, and the five links behind it are measured there** |

```sh
python3 tools/memslot.py --gb 12 --label probe -- \
  python3 -u tools/formal_chain_probe.py 5 arm64 $F
```

**Round 0's eight groups account for all 43 non-passing files, and one of the
eight is keyed on the IMPORTER rather than the module that refused.** Adding the
group sizes: 19 + 11 + 4 + 3 + 2 + 2 + 1 + 1 = 43. The five groups whose key is a
real refusing module for link 1 are 19 + 11 + 2 + 1 + 1 = **34**, and the three
left over are the `std/_gpu/_utils.mojo` group — so **link 1's feature accounts
for 37 files, exactly §2's 37, with 3 of them filed under the wrong name.**
`std.format._utils` resolves to `std/_gpu/_utils.mojo` ITSELF, so the importer is
named as the refuser; see §6.4 and
`FORMAL_a_dotted_import_resolves_to_a_nearer_leaf.md`. It is the only group in the
walk whose key is wrong, and it is wrong because of a defect in the resolver the
walk and the build share — which is also why §2's table, read off the sweep log
rather than off this walk, is the one to use.

**Link 2 HAS a doc and no claim, and it is not monomorphisation**
(`work/formal25-5`): `std/sys/arg.mojo` is outside every package here, and the
refusal — `Span[StaticString, ImmStaticOrigin] is a compile-time
explicit-parameter list on a generic, not a subscript` — is filed in
`bugs/FORMAL_a_comptime_origin_alias_is_an_mlir_attribute_template.md`, which
measures the chain it is actually behind. The short version: the second bracket
argument is a `comptime` ALIAS whose initializer is an MLIR attribute template
(`std/origin/__init__.mojo:123`), and that module does not build, so there is no
word to bind for it. A near-identical program with a comptime argument that
*folds* builds, which is what rules out the easy reading. 4 files of this scope
sit behind it, so it was worth a doc rather than a mention — and the doc it
needed to be is not the one `FORMAL_generic_monomorph_scope.md` §"what is not
covered" was going to become. **The stop is the tool's documented limit** —
neutering a module removes the names its users call — and it is now detected and
reported as such rather than as 43 files refusing a construct (§4).

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

## 0.1 §6 item 1 is CLOSED: the cause-ranking instrument can rank this scope

The defect §6 item 1 described is fixed at the cause, and the fix is the one
`tools/formal_chain_probe.py` had already taken for itself: **read the module the
MESSAGE names, and resolve it with the build's own resolver.**

`formal/model.py::imported_callee_refusal` states the defining module in a
sentence — `` `FormatStruct` is called, and it is imported from
`std.format._utils` `` — and carries **no `<file>: ` prefix** for it, which is
what §6 item 1 measured ("the same prose shape defeats it") and what
`…_b10.md` §3.3 described from the other side ("the chain names this module by
basename only"). `formal_sweep.py::refusing_module` is now ONE reader for that
sentence, cut from the f-string that writes it (the same discipline as
`…_b9.md` §5.1's samples: a log line drifts, a generated sentence does not), and
`tools/formal_sweep_causes.py::_resolve_refuser` asks two questions in the order
that has answers — a name that is a FILE goes to the basename index as before,
and a DOTTED MODULE name goes to `formal.imports.resolve_module_path`.

**Measured on the b10 log, which contains this scope, arm64 and x86-64
identically:**

| `refused in:` | before | after |
|---|---|---|
| this scope's largest row | keyed on the IMPORTER (`std._gpu._utils` — §6.4's misattribution) | `std.format._utils` x111, `std.memory.alloc` x29, `std.bit.mask` x13, `.philox` x6, `std.math` x3 |
| `uses:` on `std.format._utils` | **NOT MEASURED** | **42 of 111** blocked files name something it declares; 69 are closure |
| `uses:` on `std.memory.alloc` | **NOT MEASURED** | **6 of 29** |
| `uses:` on `std.bit.mask` | **NOT MEASURED** | **2 of 13** |

Two cells still read NOT MEASURED (`pathlib` x2, `time` x1) and both are the
documented ambiguity case rather than a gap: each basename matches a stdlib
package AND `formal/hostmods/`, and the tool says so instead of picking one.

**A relative spelling still resolves through the basename index or not at all**,
on purpose: `..fstat` and `.philox` are relative to the file that did the
importing, which is inside the chain and not the file the sweep swept, so
answering it would be a guess — and this column's whole discipline is that an
unmeasured number says so.

`python3 test_refusal_taxonomy.py` is 235/235 (was 219/219) with rows pinning
the reader against `formal/model.py`'s own sentence, that the row is keyed on
the DEFINING module rather than the importer, that a dotted name resolves to a
file at all, that `uses` counts the one file that names the callee, and that a
relative spelling stays unmeasured.

**What this does NOT do:** it ranks the scope's causes, it does not FIX them.
§2's two features are still `formal19-1`'s and `formal16-2`'s, and
`…_b10.md` §3.1's measurement of them (170 files, 14 symbols, 79 call sites,
largest site 13) is unchanged by this — which is what a reader should take from
it: the queue can now PRIORITISE the corpus's largest construct.

## 0.2 §6 item 3 is CLOSED: the walk stopped because of its own EDIT, and five
## links nobody had measured were behind it (`work/formal25-5`)

**The premise was half wrong and the half that was wrong is the half that
mattered.** §6 item 3 said the limit was "removing an import line whose only use
was the only statement in an indented block … a stub that also removed the block
would extend it". **An emptied block is not a parse error in this dialect:**
`fire_compiler.py::_parse_block` substitutes a `PassStmt` for an empty suite
rather than refusing it (*"Empty block: comment-only body produces DEDENT with no
INDENT"*), measured over a module-level `if`, a `try` arm, a function body, a
`struct` body, a `while`, a `for` and a `with`. So deleting such an import costs
nothing, and no fix was owed there.

**What actually stopped the walk is a shape §6 item 3 did not name: a
parenthesised import spanning lines.** `from .constants import (` is ONE line the
walk's pattern matches and the names under it are on the lines after it, so
deleting the matched line leaves them at an indentation no header introduces. On
this scope, round 2 stubbed `constants.mojo`, and the file that broke is
`std/collections/string/_parsing_numbers/parsing_floats.mojo`:

```
30  from std.builtin.globals import global_constant
31
32      CONTAINER_SIZE,          <- the head, `from .constants import (`, is gone
33      MANTISSA_EXPLICIT_BITS,
...
37  )
```

which is `build: 32:0: Unexpected INDENT('')` — reported by **43 of the scope's 46
files**, because every one of them imports that module. Re-measured on today's
master, unchanged:

```
=== round 3: 3 built, 0 refusing module(s), 43 unmeasurable (the stub step left
             the copy unparseable)
```

**The fix is in the EDIT, not in the parser**, and it is one mechanism for both
shapes: `tools/formal_chain_probe.py::stubbed_import_edit` REPLACES each matched
logical import — the whole logical line, continuation lines included, tracked by
bracket depth — with `pass` (`NEUTRALISED`). `pass` is this dialect's own answer
for a statement that is not there any more (it is literally what `_parse_block`
inserts), so it parses at every scope, lowers to nothing on both backends, and
cannot introduce a construct the tree does not already answer for.
`mangled_copy` stays, because a real parse error must stay LOUD.

**Measured, both architectures, same scope, `-j 4`, 8 rounds** — the before is
this tree before the change and the after is the same tree after it:

| | before | after |
|---|---|---|
| rounds walked | **3** (round 3 is the stop) | **8 and still going** |
| links measured | 3 (`_io.mojo`, `arg.mojo`, `constants.mojo`) | **8** — §0.2's table below |
| files reported by the walk's own damage | **43 of 46** | **0** |
| files BUILDING at the last round | 3 | **4** |

The two arms are identical round for round, group for group, count for count; the
only difference in the whole log is where the 300-character truncation lands in
one message that carries a mangled dylib's own name (`.arm64.dylib` vs
`.x86_64.dylib`), which is the same caveat `…_b11.md` §2.2 records.

### The five links that were behind the stop, and who owns each

Nothing below is claimed by this document; these are the rows a reader of §2 was
never given, measured on both architectures:

| link | files | the refusing module | the refusal | owner |
|---|---|---|---|---|
| 4 | 1 | `std/bit/mask.mojo` | `is_negative` on a `SIMD[dtype, _]` — the bare-call row again, one link down | `FORMAL_a_bare_call_to_a_template_…` (`formal19-1`) |
| 5 | 29 | `builtin_slice.mojo` | `Optional[Int]`, and this target has no word to spell `None` as | `FORMAL_stdlib_optional_needs_a_representation` (`formal16-7`) |
| 6 | 10 | `std/base64/_fnv1a.mojo` | `data[…](…)` calls a name this unit does not compile, so the brackets cannot be bound | the bracketed-specialisation row; `formal19-1`'s neighbourhood |
| 7 | 9 | `std/hashlib/hasher.mojo` | the dylib re-exports `Span` from `std.collections`, and no module it imports exports that name | **§0.3 — a TYPE demanded as a SYMBOL, and it is fixed** |
| — | 32 | `std/memory/alloc.mojo` | `dealloc` — §2's second row, which **grows 12 → 13 → 32** as the two features in front of it clear | `formal19-1` |

**What this does NOT do**, so the reading is the honest one: it does not move a
single file to `pass`, and it was not expected to — §2 is unchanged and its two
features are still `formal19-1`'s and `formal16-2`'s. It fixes an INSTRUMENT
that was reporting its own damage as the end of the chain, and it hands over five
links that had never been measured. The `hasher.mojo` row was the only one of the
five with no claim behind it, and §0.3 is what happened to it.

Verified: `python3 test_formal_chain_probe.py` **20/20**, seven of them new and
all of them asked of `fire_compiler`'s parser rather than of a build — including
the one that pins the DELETION still failing to parse (so the substitution cannot
be judged unnecessary) and the one that pins the emptied-block correction above.

## 0.3 The row §0.2 found with no owner was a TYPE demanded as a SYMBOL, and
## that is fixed (`work/formal25-5`)

`std/hashlib/hasher.mojo` line 21 is `from std.collections import Span`, and
`Span` is declared in `std/collections/span.mojo` and re-exported by
`std/collections/__init__.mojo`. The refusal the walk measured was:

```
build: __init__.mojo imports '.base64', which cannot be built either:
hasher.mojo: std_hashlib_hasher.…arm64.dylib re-exports Span from
std.collections, but no module it imports exports that name, so a caller of it
would have nothing to bind. This is a real gap in that module's public API — a
private, generic or overloaded definition, all of which doc/ABI.md keeps out of
the boundary — and not something this backend can paper over …
```

**Every clause of that is false.** `Span` is public, it is not generic, it is not
overloaded, and it is a TYPE — and a type has no symbol, so there is nothing to
be missing. The check that fired is `formal/build.py::_namespace_library`'s, and
its input is the KIND `formal/imports.py::declared_kinds` recorded for the
imported name.

**And that kind was `"unknown"`, because `declared_kinds` read ONE file.** The
module the import statement names is the package `std.collections`, whose
top-level statements are five `from .sub import …` lines and no declaration at
all. `"unknown"` is not `"type"`, so the name landed in the set that must be
provided as a symbol. This is the SAME defect `bugs/FORMAL_known_limits.md` §1
records and fixed one hop in — there, `std/traits/__init__.mojo`'s names were
absent because a `TraitDef` was filed as neither a function nor a type; here a
name is absent because the file read is not the file that declares it.

**Reproduced on six lines, with no stdlib involved** — a package that
re-exports `struct Shape` from its submodule, and a module with no free function
(a trait, so it is built as a NAMESPACE library) that imports the type through
the PACKAGE:

```console
$ python3 fire.py build --formal --no-prove -o .tmp/pk3.aout \
      .tmp/pkgtest/main3.mojo
build: main3.mojo imports 'pkg2.mid', which cannot be built either: mid.mojo:
pkg2_mid.…dylib re-exports Shape from pkg, but no module it imports exports
that name, so a caller of it would have nothing to bind. This is a real gap in
that module's public API — a private, generic or overloaded definition …
```

**The fix is in the KIND reader, not in a name list**: `declared_kinds` now
follows the forwarding edge — a name the file does not declare but forwards is
looked up in the module its own `from … import …` names, resolved with the
build's own `resolve_module_path`, under a hop bound. The direction is
load-bearing and it is the argument for safety: this can only turn `"unknown"`
into a real kind, the only kind that leaves the symbol check is `"type"`, so it
can remove a refusal and cannot add one. A name nothing declares stays absent,
which is the pre-existing behaviour and the one that still catches a re-export of
something that does not exist — pinned, because a fix that resolved kinds more
liberally would let a package publish a name nothing defines.

**Measured over the stdlib's 252 files** — every `from … import …` site in
`../new-modular/Mojo/stdlib/std`, asked of the real resolver:

| kind before → after | sites | what it means |
|---|---|---|
| `function` → `function` | 538 | unchanged |
| `type` → `type` | 402 | unchanged |
| `unknown` → **`type`** | **221** | **stop being demanded as a symbol** — a struct or trait reached through a package that re-exports it |
| `unknown` → `function` | 354 | already demanded (only `"type"` leaves the set), and now RECORDED accurately in the manifest |
| `unknown` → `unknown` | 362 | unresolvable, a host module, a `comptime` alias, or hidden by a cycle — unchanged |

**And on this scope, measured, the row is gone**: the same 9 links deep walk
puts those 9 files on `std/function.mojo`'s MLIR-attribute template at round 7 and
`std/reflect.mojo`'s at round 8, where before this commit they stopped at
`hasher.mojo`. Both of those are the modules the walk had just stubbed, so the
honest reading is "with the walls in front of them stubbed, these 9 land on the
MLIR attribute template in `std/reflect.mojo`" — a new link, not a fix, and it
belongs to `FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops`
(`formal19-4`).

Verified: `test_formal_imports.py` **PASS=72 FAIL=3** (the three are pre-existing
and measured identical with the fix disabled — `_KIND_HOPS = 0`, which is the
one-file reader this replaces; see the bug doc filed beside this commit),
`test_formal_link_accounting.py` 263/263, `test_refusal_taxonomy.py` 264/264,
`test_formal_run.py` **PASS=1024 FAIL=0** (both architectures, every formal
image in the suite), `test_formal_dylib.py` PASS=24 FAIL=0. The three new rows
are `test_declared_kinds_files_a_forwarded_name_by_its_definition` (the table,
no build), `test_a_forwarded_type_is_not_demanded_as_a_symbol` (the build, both
arches) and `test_a_forwarded_name_nothing_defines_is_still_refused` (the guard
on the guard).

## 6. What is left

1. ~~**The cause-ranking instrument cannot rank this scope's causes.**~~ **CLOSED
   — §0.1.** `tools/formal_sweep.py::refusing_module` reads the module the
   message names and `tools/formal_sweep_causes.py::_resolve_refuser` resolves a
   dotted name with `formal.imports.resolve_module_path`, so `refused in:` names
   the DEFINING module and the `uses:` column is measured for every group whose
   name resolves.
2. **`__init__`-only modules are refused with "nothing this backend could
   add"**, which is not true — the backend could inline them, which is
   `formal16-2`'s feature. Worth a doc edit when that lands, because the sentence
   is a dead end for whoever reads the 6 files first.
3. ~~**The chain walk stops at link 4 and cannot be pushed further by this
   tool.**~~ **CLOSED — §0.2, and the premise was wrong as well as the tool.**
   The stop was never the tool's limit: it was one deleted line of a
   parenthesised import, and §0.2 names the file, the line and the error. The
   walk now measures 8 links on this scope where it measured 3, on both
   architectures, with 0 files reporting its own damage.
4. **`formal.imports.resolve_module_path` is wrong for one importer in this
   scope**, and it is filed: `FORMAL_a_dotted_import_resolves_to_a_nearer_leaf.md`
   — `std/_gpu/_utils.mojo` importing `std.format._utils` resolves to ITSELF,
   because `_candidates` puts a root's leaf fallback in the same list as its
   dotted path and the root loop is nearest-first. Measured inside a real build,
   not only by direct call. It surfaced here because the probe now resolves the
   module a refusal names with that same function, and it put three files of one
   round under a group keyed on the IMPORTER.
5. ~~**One link of §0.2's new table has no claim and no doc**:
   `hasher.mojo` re-exports `Span` from `std.collections` and no module it
   imports exports the name, so 9 files of this scope sit behind it. ~~
   **CLOSED — §0.3.** It was not a gap in that module's public API at all: it is
   a TYPE demanded as a SYMBOL because `declared_kinds` read the package rather
   than the module that declares the name. 221 such sites over the stdlib, and
   those 9 files now walk two links further.

## 7. Reproducing

Every number above is one `fire.py build --formal --no-prove` per file behind
`tools/memslot.py`, no Lean anywhere (`--no-prove`), and the two arms agree file
for file. The four commits on `work/formal20-std-os-io-2` are the three probe
fixes of §4 and this document; the two sweep logs §1 quotes are
`.tmp/sweep_arm64.txt` and `.tmp/sweep_x86_64.txt` in that worktree, and the
chain walk's is `.tmp/probe3_arm64.txt`.

§0.2's before and after, on this scope, with the commit that made the difference
(the walk is `-j 4` internally and `--no-prove` per build, so no Lean and no
`formal_sweep`):

```sh
export PATH=/opt/homebrew/bin:$PATH
S=../new-modular/Mojo/stdlib/std
F=$(for d in os io pathlib hashlib base64 ffi python _gpu; do
      find $S/$d -name '*.mojo'; done | sort)

python3 tools/memslot.py --gb 8 --label chain -- \
  python3 -u tools/formal_chain_probe.py 8 arm64 $F
python3 tools/memslot.py --gb 8 --label chainx -- \
  python3 -u tools/formal_chain_probe.py 8 x86_64 $F

python3 test_formal_chain_probe.py          # the substitution, asked of the parser
```