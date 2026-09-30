# FORMAL_known_limits: the sweep residue, audited — which refusals are true

**Last audited: 2026-09-27 (the five-agent round 1, agent [5] — §6 added).**
Sections 1–5 are wave 5's audit and are **not** re-measured here; §6 is a
separate, later measurement of the same sweep on a tree four other agents were
editing, and it does not restate or revise §1–§5. §6 answers one question the
earlier sections could not: ranked by file count and by what closing it costs,
what is the biggest remaining lever.

**Last audited: 2026-09-26 (wave 5, agent E1).** This is the single home for
the *verified* limits behind the residue of the formal sweep's codegen classes,
and for the audit that established which of them are true. It replaces the
"what is still open" list that used to live at the bottom of
`FORMAL_module_exports_nothing.md` for the one item that belonged here (the
Stage 5 generic-template limit); that document keeps its own bug and points
here.

**The rule this document exists to enforce.** A refusal in the sweep is a
*claim about a file*, and a claim that is false is worse than no claim: it
sends the next reader looking for a construct that is not there, and it
inflates the sweep's finding count with a non-bug. `no_public_api_reason` was
written for exactly this reason ("a message that is false about the file is
worse than no message") and then, in three of its six branches, said something
false about the file. Those three are CLOSED and their sections are gone
(below, under "What wave 5 closed"); what is left here is what is still open,
with the counts as they measure on this tree.

Two more classes of defect were closed in the same wave and are recorded the
same way: two constructs that **fabricated a value** — a dotted MLIR template
and a module-level `comptime` initializer, which between them made
`std/builtin/type_aliases.mojo` a **false PASS**, the worst outcome this
project has — and a crash in `reflect.collect_exports_src` that stopped the
export probe dead on any module with a dataclass field carrying a default.

## Two open items in the arm64 per-export-contract work (agent [3])

Not part of the sweep families above, and not re-measured by this audit. Both
are **true** claims, both unfinished; the single home for their full state —
every measurement, every trap hit on the way, and the exact next step — is:

> **`FORMAL_contract_work_handoff.md`** — read §1 and §3 of it to start.

| item | measured | is the claim true? | what closes it |
|---|---|---|---|
| a per-export contract for a real dylib export (the emitter exists, `hreg` does not evaluate) | `formal-dylib` is RED, deliberately, 10 PASS / 1 FAIL | **true, unfinished** | shrink the composed effect so `bv_decide` sees one multiplication; **not** a budget problem (40× `maxHeartbeats` measured, did not help) |
| `Total` for a looping export | was **FALSE** at a constant fuel (`countdown` returns `none` at n = 8000); now TRUE, still unproved | **true since `e0af987`** | a loop-aware ranking argument; the acyclic-only CFG walk cannot supply it. Mirrored x86-64 gap: `OPEN_WORK.md` A4 |

The tree is intentionally red on the first row. Do not make it green by
reverting the emitter: a red that needs fixing gets fixed, and a green that does
not do what we want is technical debt.

---

## The three families, and what each one actually is

Measured on the four sweeps of this tree (`tools/formal_sweep.py`, both
architectures, both scopes).

| family | files (arm64, stdlib scope) | distinct causes | it is really |
|---|---|---|---|
| 1. `formal dylib has no public functions` | **30** | **8** terminal modules | 7 true limits + 1 reached by a separate bug |
| 2. `__mlir_attr[...]` assembles an MLIR attribute | **46** | **1** terminal module | 1 true limit |
| 3. the small shapes nobody else claimed | 8 | 6 | 6 true limits |

Two facts about the *shape* of these families matter more than their sizes,
and neither is visible from the finding count:

- **Family 1 is 30 files and 8 files.** Every one of the 30 is blocked by one
  of eight modules, and the largest of those (`_assembly.mojo`) accounts for
  17. Nothing here is 30 separate problems. **All 30 are now at DEPTH** — not
  one of them is a direct finding, because `std/sys/info.mojo` now refuses
  before any of them reaches the point of building a dylib, so the family is
  entirely measured through import chains.
- **Family 2 is 46 files and 1 file.** Thirty-five of the 46 are
  `CODEGEN/DEPENDENCY`, nearly all of them through `std/sys/info.mojo`; the
  other **11 are direct** — files whose OWN module-level `comptime` bindings
  carry the template (`sys/info.mojo`, `builtin/{coroutine,dtype,float_literal,
  rebind,simd,type_aliases,variadics}.mojo`, `reflection/reflect.mojo`,
  `gpu/_utils.mojo`, `_plugin/selector.mojo`). On x86-64 the
  family is the same 46 files with byte-identical messages (measured, §5.1),
  because the refusal is arch-free text and now fires before the
  architecture-specific gaps that used to shadow it. Any future work on family
  2 should start from `std/sys/info.mojo` and expect the rest to follow.

---

# 1. `formal dylib has no public functions` — 30 files, 8 causes

## 1.1 The audit table

Every terminal module, its file count, and the verdict. "True limit" means
*the refusal is correct and the file really has nothing an importer could
bind*. The evidence column is what was measured, not what the message says.

| terminal module | files | what the file actually declares | verdict |
|---|---|---|---|
| `std/sys/_assembly.mojo` | 17 | one public `def inlined_assembly[…]` (generic, variadic over `*types: AnyType`, body is `__mlir_op.\`pop.inline_asm\``) | **true limit** |
| `std/reflection/function.mojo` | 4 | one `struct ReflectedFn[func_type, func]` (generic); a `comptime reflect_fn[…] = ReflectedFn[func]` alias; two `@staticmethod` methods, `display_name()` concrete and `linkage_name[…]` generic | **true limit** |
| `std/sys/_io.mojo` | 3 | three `comptime` constants (`stdin`/`stdout`/`stderr`), no declaration at all | **true limit** |
| `std/algorithm/backend/tile.mojo` | 2 | four overloads of `def tile[…]`, all generic | **true limit** |
| `std/collections/string/_unicode_lookups.mojo` | 1 | eight `comptime` lookup tables, no declaration at all | **true limit** |
| `std/utils/_select.mojo` | 1 | one `def _select_register_value[…]` — private *and* generic | **true limit**; the message names the privacy, which is the operative rule and is now the only rule it needs |
| `std/gpu/host/nvidia/__init__.mojo` | 1 | a docstring, no declaration at all | **true limit, but it should not be reached** — see 1.3 |
| `std/stat/stat.mojo` | 1 | seven `def S_ISxxx[intable: Intable]` | **true limit** |

Measured evidence for all eight, run on this tree:

```
$ python3 -c "…_export_entries([p]).keys()…"
std/sys/_assembly.mojo                exports: []   shape: {'generic_funcs': ['inlined_assembly']}
std/reflection/function.mojo          exports: []   shape: {'generic_structs': ['ReflectedFn']}
std/sys/_io.mojo                      exports: []   shape: {}
std/algorithm/backend/tile.mojo       exports: []   shape: {'generic_funcs': ['tile','tile','tile','tile']}
std/utils/_select.mojo                exports: []   shape: {'private_generic_funcs': ['_select_register_value']}
std/collections/string/_unicode_lookups.mojo  exports: []  shape: {}
std/gpu/host/nvidia/__init__.mojo     exports: []   shape: {}
std/stat/stat.mojo                    exports: []   shape: {'generic_funcs': ['S_ISLNK', …, 'S_ISSOCK']}
```

`_export_entries` is `formal/build.py`'s, and it calls
`reflect.collect_exports_src` — **the same function the gimple dylib's
reflection table uses**. That is the right constraint and it is deliberate: one
rule, so a symbol cannot be findable in one backend's dylib and absent from
the other's. The rule excludes, on purpose and by `doc/ABI.md`: a `_`-prefixed
name; a generic template (`fn name[…]`, `struct S[T]`); an overloaded name;
and a `_CLIB_SYMS` name. Every one of the eight above falls under one of those
four, so **the refusal is true in all eight cases**, and no fix to the export
rule would make any of them build.

**§1.1, corrected (2026-09-27, agent [2]): the `_CLIB_SYMS` question is
settled, and the argument that this section used to make for changing the rule
was false.** It used to read:

> The `_CLIB_SYMS` exclusion is right for a CALL — the symbol is already
> reachable with `dlsym` out of the system dylibs — and WRONG for a
> DEFINITION. `std/sys/terminate.mojo` **defines** `exit`; if that module also
> exported one other symbol, an importer's `exit()` would bind libSystem's,
> silently, with no diagnostic. […] Cost: small in code, and it needs a
> decision about whether a dylib may shadow a libc symbol an importer would
> also resolve by `dlsym`.

**The claim is false on this tree, and so is the hazard it describes.** Three
measurements, all reproducible:

1. **`terminate.mojo` defines no `exit` — it defines nothing at all.**
   Compiling it through the real path (`build_stdlib_dylib.compile_module_to_c`
   with `module_name='std_sys_terminate'`) and reading the generated C: the
   only line mentioning `exit` is the module's own docstring, stringified as
   data. `nm` on the object reports exactly two external definitions,
   `__std_sys_terminate_toplevel` and `_std_sys_terminate_init`. Neither
   `def exit()` (whose body is a self-recursive `exit(0)`) nor
   `def exit[intable](code)` (a template) emits a line. There is no `exit` for
   an importer to bind the wrong one to.

2. **A module that *does* define a `_CLIB_SYMS` name cannot shadow libc,
   because the codegen has already renamed it.** The rename is
   `mojo/middle/types.py:799` — `_c_names` maps a C keyword **or** a
   `_C_RESERVED_FUNCS` name to `mojo_<name>` — which is `doc/ABI.md`'s
   "C-keyword names get the documented `mojo_` prefix" extended to the
   reserved libc names. Measured on the modules that actually declare one:

   | module | Mojo name | C symbol emitted |
   |---|---|---|
   | `std/sys/_libc.mojo` | `exit` | `_std_sys__libc_mojo_exit_9f63a2` |
   | `std/sys/_libc.mojo` | `write` | `_std_sys__libc_mojo_write_37bd8e` |
   | `std/io/file.mojo` | `open` | `_std_io_file__open_file_1b532c` |
   | `std/memory/memory.mojo` | `memcpy`, `memmove`, `memset` | none bare |

   `nm` on all four objects finds **no** bare libc name among their external
   definitions. A dylib built from them exports
   `_std_sys__libc_mojo_exit_9f63a2`, and libSystem's `exit` is untouched.

3. **The case is real but small.** 18 raw exports across 8 stdlib modules
   (`string.mojo`, `io/file.mojo`, `memory/memory.mojo`, `os/os.mojo`,
   `random/random.mojo`, `sys/_libc.mojo`, `sys/terminate.mojo` ×2) carry a
   `_CLIB_SYMS` name — measured with `reflect.collect_exports` and the
   exclusion filter bypassed, so this is the population the rule governs, not
   the population that reaches a dylib.

**Decision: the exclusion stays exactly as it is, and no code change is
warranted.** The `dlsym` rationale recorded above is the whole of what it is
doing, and it is the right one: the symbol a Mojo *call* to `open` resolves is
libc's, so advertising `open` in a reflection table would tell an importer
"this dylib provides `open`" when what it provides is
`_std_io_file__open_file_1b532c` under a different name — a table whose `name`
and `addr` columns disagree, which is worse than no entry. There is no
shadowing to prevent, so the trade-off that was left open ("may a dylib shadow
a libc symbol an importer would also resolve by `dlsym`?") does not arise.

**What did change is the export table's completeness, and it was a different
defect entirely** — one this document did not know about because it lives in
`reflect.export_csym`, not in the rule. A C *prototype* was being run through
the Mojo overload-mangler, so `build_stdlib_dylib.build()`'s `nm` cross-check
rejected 429 of the header's entry points as "stale" and the dylib advertised
**30 of 459** runtime symbols it defines. **CLOSED 2026-09-27** (agent [2]
measured, agent [3] applied; `INTERFACE-REQUESTS.md` request `[2] → [3]` A).
Before/after, on the same `build()` path with the same inputs:

```
pre-fix : 458 entry points considered, 429 unadvertised
post-fix: 458 entry points considered,   0 unadvertised
now     : export table: 458 of 459 runtime entry points advertised
                       (0 misresolved, 1 undefined — py_tokenize)
```

**This is now the real export table**, and `FORMAL.md` §11.2 agent [5] is built
on it: symbols read off the headers and confirmed against `nm`, per
architecture, from `build_stdlib_dylib.runtime_export_entries(arch)`. Measured
2026-09-28 on the merged tree: **1964 of 1968 advertised, 0 misresolved** — the
`csym` fix that made it so is in `reflect.export_csym`. The one entry it does not
advertise is correct — `py_tokenize` is defined by the self-hosted compiler's
own transpiled `fire_compiler.py`, not by the runtime.

The build now also reports the shortfall **by class** — *defined but misresolved*
versus *declared and undefined* — because those two are not equally interesting
and a single "drop stale export" line for both is what let a 429-entry defect
sit there looking like routine noise. Both classes are pinned by
`test_runtime_dylib.py`, in both directions: every advertised symbol is real
(`test_export_table_entries_are_all_real_definitions`) **and** every defined
symbol is advertised (`test_every_defined_entry_point_is_advertised`). The
first held while the table named 30 of 459, because the other 429 were dropped
rather than advertised wrongly; only the second makes a regression red.


## 1.2 What would close it, and what it costs

`doc/ABI.md` §Generics is the load-bearing citation and it is explicit:

> A generic is not a single symbol; each instantiation is. The boundary symbol
> for `Generic[Args]` is the **monomorphized** function, mangled as
> `Generic__method__<mangled-type-args>`, keyed in the CAS by `hash(template-id,
> concrete type args, comptime params)`. … **Until Stage 5, generics are
> monomorphized inline by the codegen.**

So the fix is not "stop excluding generics". Exporting `S_ISREG` under its base
name is one trie entry; called at `Int` and at some other `Intable` it is two
functions, and only one address can be in the trie. A consumer with different
type arguments would silently bind the first instantiation's body — a build
error traded for a run-time wrong answer, which is the one trade this whole
mechanism exists to refuse.

**Cost: Stage 5 monomorphization on the formal path.** `monomorphize.py`
exists and works for the gimple path; the formal path has no equivalent.
Concretely that is (a) a monomorphizer that walks a generic body with a
concrete type-argument binding and instantiates the calls inside it, (b) a
mangling function that agrees with `doc/ABI.md` and with what the importer
computes, (c) CAS keying by `(template-id, type args, comptime params)` so two
instantiations of one template get two entries, and (d) a decision about
`ReflectedFn.display_name` — a *concrete* method on a *parametric* type, whose
symbol name is only determined once the type arguments are. Items (a)–(c) are
the project; (d) falls out of it. This is weeks, not an afternoon, and it is
the single largest lever in the whole residue: it alone would unblock **24 of
family 1's 30 files**.

The files that would *not* be unblocked by it, and why:

- `std/sys/_io.mojo`, `std/collections/string/_unicode_lookups.mojo`,
  `std/gpu/host/nvidia/__init__.mojo` declare no function at all. Monomorphizing
  nothing is still nothing. These are correct refusals **permanently**;
  `doc/ABI.md` §Aggregates is the reason (a `comptime` constant is inlined at
  its use site and crosses no boundary). **Cost to close: nothing — and that is
  the point.** They should be read as a *fact about those modules*, not as work.
- `std/utils/_select.mojo`'s only declaration is `_`-prefixed (and also
  generic — the message names the privacy, which is the operative rule).
  doc/ABI.md's public-symbol rule excludes it on purpose. Permanent, by design.

So the **decisions** in family 1 decompose as **21 blocked on Stage 5, 6
permanent, 0 wrong.** What was wrong was the *reporting*, and that is closed —
see "What wave 5 closed".

## 1.3 One of the 30 should not be in the family at all

`std/gpu/host/nvidia/tma.mojo` is refused because it "imports `.`", and the
module `from ..` resolves to is `std/gpu/host/nvidia/__init__.mojo` — the
importing file's **own** package. The source says:

```mojo
from .. import DeviceBuffer      # means std.gpu.host, NOT std.gpu.host.nvidia
```

`formal/imports.py`'s `_candidates` does `rel = module_name.replace(".",
os.sep)`, so `".."` becomes `"/"` and the real parent directory is never
tried; the leaf fallback then finds the importer's own `__init__.mojo`:

```
>>> _candidates("..", "…/std/gpu/host/nvidia", ".mojo")
['//.mojo', '//__init__.mojo', '…/nvidia/.mojo', '…/nvidia/__init__.mojo']
>>> resolve_module_path("..", relative_to="…/nvidia/tma.mojo")
'…/std/gpu/host/nvidia/__init__.mojo'          # wrong
>>> resolve_module_path("std.gpu.host", relative_to="…/nvidia/tma.mojo")
'…/std/gpu/host/__init__.mojo'                 # what `..` means
```

The `nvidia/__init__.mojo` refusal is *true* (the file declares nothing) and it
is a limit that will never close. But **`tma.mojo` should not be blocked by it**,
and the same defect inflates the `NOT-ANSWERABLE/UNRESOLVED-IMPORT` class too
(`…/gpu/memory/__init__.mojo` "imports `.memory`", `…/os/path/__init__.mojo`
"imports `.path`"). This is also recorded as open in
`FORMAL_module_exports_nothing.md`; it is repeated here because it is a
*count* correction, not a limit: **fixing `_candidates` removes at least one
file from family 1 and is a prerequisite for trusting the family's size.**
Cost: the leaf fallback in the same function is load-bearing for
`import formal.types` inside `formal/`, so this needs a real fix (compute
`..`/`.` against the *importing file's directory*, and try the parent before
the leaf) rather than a special case. Half a day, and it is not in this
document's lane — it belongs to whoever owns `formal/imports.py`.

---

# 2. MLIR attribute templates — 46 files, 1 cause

## 2.1 The refusal is true, and it is the right refusal

`formal/model.py`'s `is_mlir_template` reads a bracket or a dotted member
access on one of four names (`__mlir_attr`, `__mlir_deferred_attr`,
`__mlir_deferred_type`, `__mlir_type`) as an MLIR attribute template, and
`mlir_template_refusal` says why: the elements are backtick-quoted literal
fragments interleaved with compile-time sub-expressions, the whole thing denotes
a *dialect attribute*, and **there is no MLIR in a freestanding image for the
template to become**. Materializing it as a container "would turn an attribute
into a pointer to a frame blob and disagree with the compiler that does have
MLIR."

Verified: the construct in the wild is both spellings, e.g.
`std/sys/info.mojo:86`

```mojo
var res = __mlir_attr[
    `#kgen.param.expr<current_target> : !kgen.target`
]
```

and `std/sys/info.mojo:32`

```mojo
return __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`
```

and the refusal fires on both architectures for both. **Verdict: true limit,
and permanent on this path.** A formal image links libSystem and nothing else,
embeds no C runtime and no MLIR; there is no target for the template to
become, and a "best effort" string would be a number the source never wrote.

Wave 3's C4 established the complement, and it is the reason this is a limit
rather than a bug: across all 294 stdlib files plus this repository, `a[i, j]`
occurs ~2000 times as a generic's **explicit template parameter list**, ~90
times as an `__mlir_attr[…]`, and **zero** times as an index. There is no 2-D
index to lower hiding behind these.

**What would close it, and what it costs.** Nothing on this path. The only
honest closure is a *different target*: a build that embeds an MLIR dialect
registry and evaluates `#kgen.*` attributes to concrete values at compile time
— which is what the real compiler does and is the entire content of the formal
backend's premise. Until then this refusal is the correct answer, and its cost
is 46 files of coverage that are unreachable by construction.

## 2.2 `__mlir_op` still builds and segfaults

`__mlir_op` is deliberately *absent* from `MLIR_TEMPLATE_NAMES`, on the stated
ground that "it is a real side-effecting op, lowered as a call". The call it
lowers to is a symbol nothing defines:

```mojo
def main():
    var n = 3
    var a = __mlir_op.`pop.inline_asm`[n]
    print("a = %llu\n", a)
```
```
$ fire.py build --formal --no-prove --backend=arm64 -o m2 m2.mojo && ./m2
Built: m2.aout
Segmentation fault: 11                                    # exit 139
$ fire.py build --formal --no-prove --backend=x86_64 -o m2x m2.mojo && ./m2x
Built: m2x.aout
Segmentation fault: 11                                    # exit 139
```

`std/sys/_assembly.mojo` — the module that heads 17 of family 1's 30 files — is
built out of exactly this construct. **Verdict: a gap, not a false refusal, and
it is the largest remaining hole in this document**: a construct that builds,
links, and dies at the first instruction. **What it should be:** refused with
the same MLIR-template wording, and the honest reason is the one its own comment
contradicts: the bracketed list is MLIR op attributes, which is a different
node, and the `pop.inline_asm` body is `__mlir_attr` again, so there is no call
to lower either. **Cost: minutes**, now that `is_mlir_template` exists and
`mlir_template_refusal` is one call — it needs `__mlir_op` added to the name
set and its "deliberately absent" comment deleted. Not done in wave 5: it was
not in that wave's brief, and adding a fifth name to a set whose other four
entries are each pinned by a `refuse:` case deserves its own case rather than a
drive-by.

---

# 3. The small shapes — 8 files, 6 causes

| shape | files (arm64, stdlib scope) | verdict | evidence / what it should be |
|---|---|---|---|
| `constructing X has no representation: this image has no declaration of X` | 4 — `stdlib_core.mojo` (`StringRef`, direct) and `std/testing/prop/{__init__,random,runner}.mojo` (`Error`, at depth) | **refusal TRUE** | `Error` really is 2 fields and `StringRef` is a fat pointer, so neither fits one word, and neither is a struct in these images. The message now says the one thing it has checked — that there is no declaration here to ask — instead of asserting a shape it cannot see |
| `__mlir_attr[...]` assembles an MLIR attribute | 46 | **true limit** | §2 |
| `comptime X = … does not fold to a compile-time constant` | 2 (`std/math/polynomial.mojo`, `std/algorithm/backend/tile.mojo`) | **true limit** — and the arch drift is **CLOSED** (2026-09-27) | `comptime n = len(coefficients)` over a *runtime* parameter, which is genuinely not knowable at compile time. The **drift** was that x86-64 refused **earlier and differently** (`unsupported call target on the formal x86-64 path (got SubscriptExpr)` for `polynomial.mojo`, `unsupported statement ComptimeForStmt` for `tile.mojo`), so one construct got two different limits from two architectures that are one language implementation. Closed by giving x86-64 the same `mojo/middle/comptime.py` resolver arm64 uses — that module documents x86-64 as an intended consumer of exactly this seam and it never was one — so both now refuse with `model.comptime_fold_refusal`, byte for byte. Side effect: x86-64 now *builds* a comptime binding that folds, which it used to refuse outright |
| `a \`...\` stands where this path needs instructions to emit` | 1 (`std/builtin/len.mojo`) | **true limit**, message **CLOSED** (2026-09-27) | `def len(value: StringSlice) -> Int: ...` has no instructions, and the old message (`unsupported expression EllipsisLiteral on the formal <arch> path`) named an AST node the author never wrote and said nothing about what to do. On x86-64 it was worse than weak: `_unsupported_expr_message` appended "container and string values are not", false of a `...`. Now one arch-free `model.ellipsis_refusal`, naming the language's own no-implementation marker and both repairs. **Measured, both arches, because the old note's scope claim was wrong in a way worth recording:** a `...` in a `trait` method builds, but a `...` in a plain function is refused whether or not anything ever CALLS it — so the distinction is the declaration KIND, not reach |
| `a Optional receiver is stored in a container` | 1 (`std/iter/__init__.mojo`) | **true limit** | by-reference receiver work; **already pinned** by `byref_refuse_stored_in_a_list` (`test_formal_run.py`). Not duplicated here |

Two rows this table used to carry are **gone** and not replaced, because both
were over-refusals rather than limits: `constructing DType has no representation`
(`DType` is a ONE-field struct, and the name list that refused it also masked
the arity rule that actually stops the neighbouring case) and
`String(...) takes exactly one value to convert (got 0)` (`String()` is the
language's zero-argument empty-string constructor, and a string on this path is
a NUL-terminated `char *`, so the interned `""` is the answer and `len` of it is
0). Both are closed; see below.

## 3.1 The `mojo_*` refusal is now decided by the ABI, not by the prefix

`FORMAL.md` phase 2, landed 2026-09-27. `is_gimple_runtime_builtin` was
`startswith("mojo_")` (`GIMPLE_RUNTIME_PREFIX`); it is now a table read out of
`runtime/*.h` by `reflect.collect_runtime_exports_h`, and
`model.gimple_runtime_callable(name, provided)` is the whole rule: every type
crossing the call boundary is one 64-bit word, AND the symbol is on the link
line. `GIMPLE_LIST_PREFIX` is **gone** — it was a hand-kept list of prefixes
standing in for a shape, and the shape answers the same question for all 546
entry points instead of the 40-odd names one prefix covered.

The two halves are independent and both are needed, which is what the prefix
rule could not express. A `MojoList *` **argument** is a box no link line can
answer, so it is refused *even when a dylib provides the symbol* — the old code
let that through. And `mojo_print`, whose every type is a word, is refused only
because nothing provides it.

| | measured over all 10 headers in `runtime/` |
|---|---|
| entry points declared | 546 |
| every type crossing the boundary is one word | **223** |
| a box in an argument or the return | 323 |
| of the 223, refused only for want of a linked library | 223 |

**223 of 546 is what a link line converts into working code with no backend
change at all.** For `mojo_sqlite3_*` it is **18 of 22**.

### Two numbers from the round-1 brief that the headers do not support

The brief said "of 455 entry points, 352 return one 64-bit word and 101 return a
heap box" and "for sqlite, **20 of 22** … the only two that are not are
`mojo_sqlite3_query` and `_query_dict`". Measured, both are off, and the reason
is worth recording because it is a rule, not a typo:

1. **455 / 352 / 101.** I measure 546 / 406 / 140 by return type alone, and 223
   once the ARGUMENTS are counted too. Neither matches 455/352/101. The
   scanner those numbers were taken with recorded `char *f` as returning `char`
   (see below), so every pointer-returning function was scored as a scalar —
   and the brief's own headline rule ("callable iff every parameter type AND
   the return type are word-shaped") is the 223 column, not the 406 one. The
   brief's own warning is the reason the larger number is the wrong one.
2. **20 of 22, with `_query` and `_query_dict` the only two refused.** Not
   derivable from the header. `_query` returns `void *`; so do `_open` and
   `_prepare`, and nothing in the *declaration* distinguishes a `void *` a
   program only passes on from a `void *` it iterates — the distinction is in a
   comment. Any rule producing 20/22 is hand-kept, which is the rot phase 2
   exists to remove. The machine-derivable rule refuses all four
   (`_open`, `_prepare`, `_query`, `_query_dict`) and calls the other 18
   word-shaped, and `test_formal_run.py`'s pre-existing
   `gimple_runtime_sqlite_refused` case — which calls `_open` and `_close` — is
   pinned on that, so 18 is also the number the suite already believed.

### The scanner this rests on was itself wrong, twice

`reflect.collect_runtime_exports_h` is where the table comes from, and the
"never hand-kept" property is worth nothing if it misreports. Both fixed here,
both in `reflect.py`:

- **Every pointer return was recorded as a scalar.** The 2026 fix made them
  MATCH; the separator's `\*?` then consumed the `*` that belongs to the type,
  so the table said `char mojo_str_new (char *s)` for a function returning
  `MojoStr *`. 92 `char *` and 39 `MojoList *` returns in `fire_runtime.h`, all
  misstated. A consumer deciding what a value IS was told the opposite of the
  truth — and phase 2 is exactly such a consumer.
- **Five non-existent symbols were in the shipped dylib's table.**
  `mojo_fnptr_call_0` … `_4` are `static inline` helpers, and the scanner read
  the `return` statement in one's body as a prototype (`build_stdlib_dylib.py`
  emits `extern void <sym>();` and takes its address). BUG-2026-036's shape.
  `fire_runtime.h` 459 → 456; four real declarations gained in the same fix.

Neither is closed by a test in the tree, so both are in
`INTERFACE_REQUESTS_agent3.md` §2 as diffs for the integrator.

### What is still open, and it is [1]'s half

A word-shaped call is emitted only when the symbol is on the link line, and the
executable path (`build --formal`, which every suite drives) has no runtime
library on its link line at all. So today the 223 are refused *for want of a
library*, which the new message says plainly instead of claiming there is
nothing to lower. INTERFACE REQUEST to [1] for the optional-runtime-unit
registry; it is the only thing between the 223 and working code.

---


# 4. What wave 5 closed

Recorded here because the *pins* are the durable artefact and a reader
revisiting this document needs to know which of its numbers are now
load-bearing assertions. The analysis, reproducers and reasoning live with the
code and in the test files named here.

| closed | what it was | pinned by |
|---|---|---|
| the dotted and single-element MLIR spellings built and printed a fabricated word (10 on arm64, 0 on x86-64, program-shape dependent) | `is_multi_index` was reached only for a comma list, so `__mlir_attr.\`…\`` and `__mlir_type[x]` fell through to a member read of an undefined name | `limit_mlir_template_dotted_spelling`, `limit_mlir_template_single_element_bracket` |
| a module-level `comptime X = __mlir_type[…]` was never walked — a **false PASS** for `std/builtin/type_aliases.mojo`, which the baseline counted among its 105 | the module-level `comptime` initializer is not part of the function-body expression walk, so the walk's *refusals* were missing, not its lowering | `limit_module_level_comptime_mlir_template`, `limit_module_level_comptime_nested_mlir_template` |
| `no_public_api_reason`'s four named branches were all gated on `not concrete_funcs`, so any module with a concrete public function that exported nothing fell through to a sentence asserting "every declaration in it is private" | the fall-through now computes each public name's reason from `reflect.export_exclusions`, the same function `_export_entries` builds the table from, and a fifth branch names the `_CLIB_SYMS` exclusion | `the fall-through names a rule for each public name`, `a C-library-named definition is reported as a definition`, `a C-library-only module takes the dedicated branch` |
| `_declared_api_shape` filed a concrete and a generic of one name as two generics (`def exit():` reported as a template) | classification is per DEFINITION now, from the parser's own `FunctionDef.comptime_params` | `a concrete and a generic of one name are told apart` |
| a privacy-gated branch asserted properties of the generics — `std/memory/unsafe.mojo` (two public generics, one private helper) told its only function was "both private and parametric" | the branch is **deleted**, not re-gated: its two facts come from disjoint sets, so `set(gen_funcs) & set(private)` is empty for every possible module and the suggested repair would have made it unreachable | `a public generic is not reported as private`, `a private generic module is told it is private` |
| `reflect.collect_exports_src` raised `AttributeError: 'AssignStmt' object has no attribute 'name'`, so `gimple_codegen.py` and `fire_compiler.py` could not be built at all | a struct field's declared name is on `.target.name` for the `AssignStmt` shape the parser deliberately keeps for `x: T = default` | `a dataclass field with a default is in a struct layout`, `every module here survives the export probe` |
| `constructing DType has no representation … DType is not one thing` — false, `DType` has one field and one field is one word | `S()` with no arguments is Mojo's own struct syntax, so a name this image knows as a struct is decided by `_emit_struct_constructor`, which asks the struct | `over_refusal_one_field_struct_spelled_like_an_unrepresentable_type` (+ its guard) |
| `constructing X has no representation … X is not one thing` — a claim about a type the image cannot see | the message now states the one thing it checked, that there is no declaration here | `over_refusal_undeclared_type_says_it_is_undeclared`, `over_refusal_no_longer_claims_a_type_is_not_one_thing` |
| `String(...) takes exactly one value to convert (got 0)` | `String()` is the zero-argument empty-string constructor and materializes the interned `""` | `over_refusal_zero_arg_string_constructor_is_the_empty_string` |
| the private / C-library / overloaded / generic decisions were computed twice, in `reflect` and in the refusal text about them | one table, `reflect.export_exclusions`, read by both; the export SET is unchanged, measured over 578 modules | `the exclusion table does not change the export set` |

**One consolidation deliberately NOT made.** `formal/model.py:struct_field_name`
and `reflect._struct_layout_sig` now both answer "what name does this struct
field introduce", and they cannot import each other: `formal/model.py` is
deliberately leaf-most (`os` and `fire_compiler` only, so the two formal
architectures cannot drift), and `reflect.py` is the SHARED export rule that
`formal/build.py` reads, so an edge from it into `formal/` would make the
gimple dylib's reflection table depend on the formal backends. The home that
would let them share is `fire_compiler.py`, beside the `struct_field_*` shims it
already declares. Recorded rather than done, because `fire_compiler.py` is the
AST source of truth and changing it owes the full quality gate.

**One residual, measured rather than assumed.** `_declared_api_shape` (per
definition) and `reflect.export_exclusions` (the export rule, keyed by name)
disagree on exactly ONE top-level public concrete definition across 380
`.mojo`/`.py` files: `join` in `std/os/path/path.mojo`, where a NESTED
`def join[…]` inside another function puts the name in the regex's set. Every
other name the regex excludes is excluded anyway — private, a C library symbol,
overloaded, or genuinely a template. Reconciling it means changing the export
rule, which changes which symbols reach a dylib; it is not done, and it is why
every message that could be contradicted by it is computed from
`export_exclusions` rather than from the shape buckets.

---

# 5. Verification

## 5.1 The four sweeps, and the set diff

| sweep | wave-4 baseline | this tree | file-level set diff |
|---|---|---|---|
| `--no-stdlib` (repo) arm64 | 284 files, PASS=80, 80/120 | **284 files, PASS=80, 80/120** | 0 new, 0 fixed, 0 class changes, 2 detail-text changes |
| `--no-stdlib --arch x86_64` | 284 files, PASS=79, 79/119 | **284 files, PASS=79, 79/119** | — |
| default (repo + `std/`) arm64 | 578 files, PASS=105, 105/403 | **578 files, PASS=104, 104/403** | **1 new** (`std/builtin/type_aliases.mojo` — the false PASS, now honestly a `CODEGEN` finding), 0 fixed, 7 class changes, 70 detail-text changes |
| default `--arch x86_64` | 578 files, PASS=103, 103/403 | **578 files, PASS=102, 102/403** | the same one file |

Every one of those movements is accounted for:

- **The one new finding is the point.** `std/builtin/type_aliases.mojo` is no
  longer a false PASS. It was in the baseline's 105 for the wrong reason: four
  MLIR templates in module-level `comptime` bindings, none of which anything
  looked at. It is now refused, on both architectures, by a message that names
  the construct (`comptime AnyOrigin = Origin[0, _mlir_origin=__mlir_attr[…]]()`
  — the template is two levels down, and the walk recurses).
- **PASS 105 → 104 is that file and nothing else.** No file left the findings
  set on either scope, so no verdict was lost.
- **The 7 class changes are all `CODEGEN/DEPENDENCY` → `CODEGEN`**, and all
  seven are files whose OWN module-level `comptime` binding now refuses before
  the import chain does: `sys/info.mojo`, `builtin/{coroutine,dtype,rebind}.mojo`,
  `reflection/reflect.mojo`, `gpu/_utils.mojo`, `_plugin/selector.mojo`. A
  finding that moves from a dependency to the file that contains the construct
  is the classifier getting more accurate, not a regression.
- **The 70 detail-text changes split as 44 + 19 + 4 + 3**: 44 files that now
  name the MLIR template instead of something else, 19 more whose
  dependency-chain text now terminates in that same message, 4 whose
  unrepresentable-type message was reworded, and 3 that are another agent's
  by-reference work in flight. Ten more files name the actual construct than
  did before (36 → 46).
- **Arch symmetry is exact for the new refusals**: the same 46 files name the
  MLIR template on x86-64 as on arm64, and **all 46 messages are byte-identical
  between the two architectures**. The two x86-only findings
  (`builtin/swap.mojo`, `builtin/value.mojo`) are pre-existing drift, verified
  identical on `dbf3abb` and untouched by this work.

## 5.2 The pins, and the fail-when-removed demonstration

Every pin in §4 was shown to go **red** when its fix is removed, by running
the new cases against `git archive dbf3abb` plus **only the two test files** and
no production change (`/tmp/e1pre`). 8 of the 9 new `test_formal_run.py` cases
and 9 of the 11 new `test_formal_imports.py` cases are red there, each for the
right reason:

```
FAIL  limit_mlir_template_dotted_spelling: --backend=arm64 BUILT a construct
      that has no representation (expected a refusal naming 'assembles an MLIR
      attribute from a template'); the binary is the real answer here
FAIL  limit_module_level_comptime_mlir_template: --backend=arm64 BUILT …
FAIL  over_refusal_one_field_struct_spelled_like_an_unrepresentable_type:
      build: constructing DType has no representation on this path (a formal
      value is one 64-bit word, and DType is not one thing) …
FAIL  over_refusal_no_longer_claims_a_type_is_not_one_thing: --backend=arm64
      still says ['is not one thing'] — the refusal asserts a fact that is not
      true of the file it is reported against
FAIL  over_refusal_zero_arg_string_constructor_is_the_empty_string:
      build: String(...) takes exactly one value to convert on this path (got 0)
FAIL  a concrete and a generic of one name are told apart: the concrete
      `def exit()` was not counted as concrete: {'funcs': [], …,
      'generic_funcs': ['exit', 'exit'], …}
FAIL  a public generic is not reported as private: two PUBLIC generic templates
      were reported as private: … the only function it declares is the generic
      template bitcast, pack_bits, which is both private and parametric …
FAIL  a C-library-only module takes the dedicated branch: … did not take the
      dedicated branch: … every declaration in it is private (a leading `_`) …
ERROR a dataclass field with a default is in a struct layout
ERROR the exclusion table does not change the export set
      AttributeError: 'AssignStmt' object has no attribute 'name'
```

The two `ERROR`s are the `reflect.py` crash reproducing inside the harness,
which is the defect rather than a broken test. The cases that pass on **both**
trees are the four labelled **guards** in §4, which is what a guard is for.

`test_formal_imports.py`'s three `expect=` markers from wave 4 reported
`marked expect=… but it PASSES` the moment the messages were corrected, and were
removed; `EXPECTED_FAILURES` is now empty, and the three tests are ordinary
passing cases.

## 5.3 The suites

| command | result |
|---|---|
| `make check` | 7 passed, 0 failed, 0 skipped |
| `test_formal.py` | **PASS=40 KNOWN-GAP=3 FAIL=0** |
| `test_formal.py --backend x86_64` | **PASS=43 KNOWN-GAP=0 FAIL=0** |
| `test_formal_run.py` | **PASS=196 FAIL=0** (162 at wave 4; the growth is four other agents' cases in flight) |
| `test_formal_dylib.py` | **PASS=11 FAIL=0** |
| `test_formal_imports.py` | **PASS=37 EXPECTED=0 FAIL=0** (was 26 with 3 EXPECTED) |
| `test_formal_sweep.py` | Ran 55 tests … OK |
| `python3 test_suite.py` | **43 passed, 0 failed** |
| `formal/x86_64_model_test.py` | **agree 43 WRONG 0** |
| `make check-gimple`, `make check-modcache` | 1 passed each; re-run with `--no-cache` after the `reflect.py` change and **81 passed, 0 failed** |
| `stdlib-dylib` (required: `reflect.py` feeds the gimple dylib's reflection table) | **0 modules skipped before, 0 after**, and the 244-line stderr is byte-identical. `reflect.py` IS in `cas._COMPILER_SOURCES`, so the after-run genuinely rebuilt rather than replaying. `check-modcache`'s `checked_run` key does NOT include `reflect.py` even though `test_module_cache.py` imports it — a real cache gap, reported, not fixed (`tools/suite.py` is not this wave's lane) |

**No stale `EXPECTED_FAILURES` entry.** `test_formal.py`'s three arm64 markers
(`either`, `both`, `fib`) all still fail — `KNOWN-GAP=3` — and
`EXPECTED_FAILURES_X86_64` is empty and stays empty. `test_formal_run.py` has no
expected-failure list.

---

# 6. The residue, ranked (2026-09-27, agent [5])

**What this section is.** §1–§3 group the residue by *shape of refusal* and
establish which of those refusals are true. That is the right axis for deciding
whether a refusal is a lie. It is the wrong axis for deciding what to do next,
because it produces a list of 8 files and 1 file and 46 files and never says
which of them, closed, would move the coverage number the most.

This section re-groups the same findings by **files unblocked per unit of
work**, measured on the four sweeps, and states a cost for each. It is a
backlog, not an audit: nothing here revises §1–§5, and every entry here that
touches a shape §1–§5 already audited points at the section that owns the
verdict rather than repeating it.

**The measurement, and what it is worth.** Four runs of `tools/formal_sweep.py`
on this tree, both architectures, both scopes:

| sweep | files | PASS | codegen | codegen/dependency | host-import | target-limit | coverage |
|---|---|---|---|---|---|---|---|
| `--no-stdlib` arm64 | 294 | 84 | 39 | 0 | 166 | 5 | 84/123 = 68.3% |
| `--no-stdlib` x86_64 | 294 | 82 | 39 | 0 | 166 | 5 | 82/121 = 67.8% |
| default arm64 | 588 | 108 | 127 | 181 | 166 | 5 | 108/416 = 26.0% |
| default x86_64 | 588 | 105 | 128 | 181 | 166 | 5 | 105/414 = 25.4% |

**Read these with the caveat they deserve.** This tree was being edited by four
other agents throughout (`formal/imports.py`, `formal/model.py`,
`gimple_codegen.py`, `fire.py` and others), so the absolute counts move between
runs and the *family decomposition* is the durable part, not the totals. The
file COUNT grew from §5.1's 578 to 588 because other agents added files. Two
`unresolved-extern` files appear on x86-64 and not arm64 and are an artefact of
a per-arch dylib that exists but cannot be `dlopen`ed on this host — that is
agent [2]'s territory, not a codegen finding, and it is flagged in §6.4.

## 6.1 The decomposition, by what actually refuses

Direct `codegen` — 127 files on arm64, 128 on x86-64 — decomposes as:

| shape | files | what it is |
|---|---|---|
| **by-reference frame escape** (`a X receiver is returned from…`, `… frame address is passed to len()`, `… hands the word in the slot…`, `… cannot be placed: this name holds a frame address…`) | **97** | the widest thing in the whole residue, and it is one design question, not 97 |
| MLIR attribute / dialect construct | 10 | §2. **Permanent.** |
| module-level `comptime` binding initialized from an attribute | 1 | §2's twin, the false-PASS shape wave 5 closed |
| 19 distinct singleton causes | 19 | each its own file; §3 is the right home for these |

`codegen/dependency` — 181 files — is **13 terminal modules**, and the top four
were 168 of the 181. **`env.mojo`'s 55 left this family on 2026-09-29**, so the
table's top four are now three:

| terminal module | files | terminal reason | the refusal is | to close it |
|---|---|---|---|---|
| ~~`std/os/env.mojo`~~ | ~~**55**~~ **0** | ~~`external_call['setenv', Int32]` — a subscript whose index is a tuple~~ | **CLOSED 2026-09-29** — the analysis in §6.2 was right about the misdiagnosis and wrong about the cost; see below | **done, and it did not need Stage 5** |
| `std/sys/info.mojo` | 37 | module-level `comptime` binding initialized from an MLIR attribute | true, **permanent** (§2) | nothing on this path |
| `std/collections/binary_heap.mojo` | 35 | `a BinaryHeap frame address is passed to len()` | true | by-reference receiver work |
| `std/builtin/builtin_slice.mojo` | 20 | `constructing Slice with 3 argument(s) is a call to a user-defined __init__` | true, and **the best-worded refusal in the residue** | run `__init__` / field-filling construction |
| `std/sys/_assembly.mojo` | 18 | one generic `inlined_assembly[…]` | true (§1.1) | Stage 5 |
| `function.mojo` 4, `_io.mojo` 3, `random.mojo` 3, `tile.mojo` 2, `_select.mojo` 1, `_unicode_lookups.mojo` 1, `stat.mojo` 1, `itertools.mojo` 1 | 16 | §1.1, table verbatim | 7 true + permanent | Stage 5, or nothing |

## 6.2 A true refusal with a false explanation, in the largest family — CLOSED

**Status: closed 2026-09-29 (`4ad34f3`).** The analysis below was right about
the misdiagnosis and **wrong about the cost**, and the second half of that is
the part that mattered: it said the family is a §1.1 family-1 member and needs
Stage 5 monomorphization, and it does not. Read the rest of this section for
why, and `bugs/FORMAL_env_family_next_terminal.md` for the measurement and for
where the 55 files landed.

The single largest family in the residue — **55 files, one construct** — was
refused like this:

```
env.mojo: external_call['setenv', Int32] is a subscript whose index is a
tuple. A value here is one 64-bit word and a list is a flat blob of words, so
a tuple index has no representation on this path. It is one of two things: a
lookup keyed by the tuple, which is lowered only when the base is a known dict
and compares the key element-wise; or a two-dimensional index, which needs a
row stride the source never states.
```

**The refusal is true and the explanation is wrong**, which is the one
combination this document has an opinion about. `std/os/env.mojo:22` is

```mojo
from std.ffi import c_int, external_call, _CPointer
...
return external_call["setenv", c_int](name.contents, value.contents, c_int(overwrite))
```

`external_call` is a *function-like template*, and `external_call["setenv",
c_int]` applies it at a concrete type argument. It is neither of the two things
the message offers:

  * it is not a **dict lookup** — `external_call` is not a dict, and the
    "lowered only when the base is a known dict" clause is answering a
    question nobody asked;
  * it is not a **two-dimensional index** — the second tuple element is a TYPE,
    not a coordinate, and §2.1 of this document already established (across 294
    stdlib files plus this repository) that `a[i, j]` occurs ~2000 times as a
    generic's explicit template parameter list and **zero** times as an index.
    There is no 2-D index hiding here; the message sends a reader to look for
    one, which is precisely the "a claim that is false is worse than no claim"
    failure this document exists to prevent.

**The honest refusal is the one §1.1 already gives for a generic**: this is a
template application with a concrete type argument, a formal value is one word,
and there is no symbol for the instantiation until the boundary symbol is the
*monomorphized* function (`doc/ABI.md` §Generics). Which makes it a **§1.1
family-1 member**, and its cost the same: Stage 5.

**Cost of the rewording alone: under an hour, and it is [3]'s file**
(`formal/model.py`), not this document's. It is worth doing anyway, because a
55-file family whose explanation is wrong is a family the next person will
re-derive from scratch.

### 6.2.1 …and then it turned out not to be a monomorphization at all

The last two paragraphs above were **half right in a way that cost more than
they saved**, so they are corrected here rather than deleted.

`external_call` looks like a §1.1 family-1 member because the shape is the
shape: a subscript over a name, with a type in the bracket. But the thing the
bracket selects is not a *function to monomorphize* — it is a **C symbol that
already exists**, named by a string literal in the source. There is no
instantiation to mangle and no boundary symbol to invent: the target is
`setenv`, and `setenv` is on the link line whether or not anybody has compiled
a Mojo function. Stage 5 is what you need when the callee is a template this
compiler must EMIT; `external_call`'s callee is a template this compiler must
NOT emit. Conflating the two is what made a 55-file family look like weeks of
work, and it is the same confusion §2.1 of this document warns about one
section earlier — deciding what a construct means from its SPELLING.

So the repair was not a monomorphizer. It was: recognise the construct by its
base name (`M.is_external_call_template`), read the symbol and the declared
return type out of the bracket (`M.external_call_spec`), and let both
architectures take the extern path they already had for every other external
call — plus the one thing an extern call cannot know and this construct states
outright, the **declared return type**, which is what says whether the return
register holds the whole answer or the low half of one. Measured: **55 files
left the family and 0 entered it.** `bugs/FORMAL_env_family_next_terminal.md`
has the before/after table and the next terminal.

Two things this document should have said and did not, and which are the real
transferable lesson:

  * **A shape shared with a construct that needs work is not evidence that it
    needs that work.** The bracket in `external_call["sym", T]` and the bracket
    in `size_of[type, target]` are the same AST node. One of them needs a
    monomorphizer and the other needs a `BL`. Nothing in the refusal, in the
    sweep, or in the family count could tell you which, and the ranking in §6.3
    inherited the answer from the family it was lumped in with.
  * **The measurement that settles a construct's cost is a program, not a
    count.** The family was 55 files and the doc had been re-deriving 55 for
    several waves. Writing the three functions of `env.mojo` out as a
    standalone program, with the `std.ffi`/`std.sys` imports dropped so the
    import closure could not answer for it, took minutes and showed the bodies
    lower and run correctly on both architectures — which is the fact the
    whole ranking hinged on and which no amount of reading had produced.

## 6.3 Ranked, with costs — the answer to "what is next"

| # | lever | files | cost | why this rank |
|---|---|---|---|---|
| **1** | **Stage 5 monomorphization on the formal path** | **34** (family 1: 18 `_assembly` + 16 remainder) — **was 89; the 55 `env.mojo` files left on 2026-09-29** (§6.2.1) | **weeks** — §1.2 (a)–(c) | The largest single lever, and it is the *same* work for both halves: a monomorphizer, a mangling function that agrees with `doc/ABI.md` and with what the importer computes, and CAS keying by `(template-id, type args, comptime params)`. It was ranked first on a 89 that included 55 files that turned out not to need it; the 34 that remain are the real size, and the re-ranking against #2 below is a judgement call now that the numbers are this close |
| **2** | **by-reference frame escape** | **97 direct**, of which 29 are in files that also import a host module and so cannot build anyway → **68 actionable** | days-to-weeks, and it is a *design* question, not a patch | Widest single shape in the residue, and already has its own design document (`bugs/FORMAL_wide_receiver_by_reference.md`) |
| **3** | `Slice.__init__` — run a declared `__init__` / field-filling construction | 20 | **days**, self-contained | The cheapest *capability* in the residue, and the message that describes it is already exact. Nothing about it needs a new value model |
| **4** | ~~`env.mojo`'s message, rewritten to name a template application~~ | ~~0~~ **55** | **done 2026-09-29** | The reword was never needed: the message was replaced by a **lowering** (§6.2.1). Listed here struck through because a ranking that still carries it would send the next reader to edit text that no longer exists |
| **5** | the 19 singleton direct causes (§3) | 19 | one sitting each | Already audited in §3; several are weak messages rather than capabilities, and §3's own guidance applies: **prefer fixing a wrong message to adding a capability** |
| — | MLIR attribute templates | 41 | **nothing — permanent** | §2. Not work. Read as a fact about those modules |
| — | host-import | 166 (160 in reach) | sized, see below | not a limit at all |

**So: the biggest remaining lever is Stage 5 monomorphization, and the numbers
are 34 files and weeks.** It is the same answer §1.2 reached for family 1
alone; `env.mojo`'s 55 were added to that number on the reasoning that the
family "turned out to be family 1 in disguise" (§6.2), and that reasoning was
**wrong** — see §6.2.1, where the 55 are closed and the cost was under a day.
The second answer is the by-reference frame work at 68 actionable files, so
the honest comparison is now 34 files of *plumbing the design already
specifies* against 68 files of *design that does not exist yet* — which
inverts the old order on the numbers, and leaves the ranking a judgement call
rather than a fact. Read the design cost as the thing that has actually been
estimated and the file count as the thing that has been re-measured most
recently.

**Nothing in this list should be started as a side quest.** #1 is a project,
which is why it is written down here rather than attempted.

## 6.4 Three things that are not findings, and were being counted as work

  * **30 of the 127 direct `codegen` findings are in files that also import a
    host module** (measured on both arches; `tools/formal_sweep.py` now prints
    this line). **29 of those 30 are by-reference frame escapes**, which is
    what makes the number actionable rather than a curiosity: the by-reference
    work's real prize is 68 files, not 97. The construct refusal is real and
    the construct is in the file, so `codegen` is the right class — but the
    file fails on its import the moment the construct is fixed, so closing the
    finding changes nothing about the file. This is **not** reclassified: moving those 30 out of the
    denominator would raise the coverage rate from a bookkeeping change, which
    is the one move that makes a coverage report worthless. It is printed, and
    the difference is visible.
  * **`not-answerable/host-import` is 166 files, of which 160 import a module a
    Mojo-side implementation could in principle provide** (`os` 79, `re` 14,
    `sys` 14, `struct` 7, `json`, `time`, `io` and the rest) and 6 need a host
    process or an embedded interpreter. The class blurb used to say all 166 were
    "not fixable", which is false of the 160. That was agent [4]'s list to
    split and this document's to measure; both are done and the sweep now says
    which is which on every run. **`os` is 79 of the 160 and is not close** —
    the split sizes the work, it does not make it small.
  * **2 files are `unresolved-extern` on x86-64 and not on arm64**
    (`example_imports.mojo`, `abfulltest_driver.mojo`), and the reason is
    `dyld cannot load …/formal-imports/x86_64/*.dylib` — the per-arch formal
    dylib exists and is the wrong architecture for this host. That is a
    **per-arch dylib build** item (agent [2]'s, and the thing [2] was asked to
    build), not a codegen gap, and it is a real load failure reported as one.

## 6.5 Arch drift, still open, still two files

Same sweep, both arches, `set`-diffed. **Zero class changes** — every file is
in the same class on both architectures — and exactly **two files whose message
differs**, which is the drift §3 records and which is *not* cosmetic:

  * `std/builtin/swap.mojo` — **arm64 builds it, x86-64 refuses it**
    (`unsupported unary operator '^' on the formal x86-64 path`). A construct
    one architecture lowers and the other does not, which is a codegen gap in
    x86-64, not a wording difference. Pre-existing, unchanged since `dbf3abb`.
  * `std/math/polynomial.mojo` — arm64 says `comptime num_coefficients = …
    does not fold to a compile-time constant`, x86-64 says `unsupported call
    target on the formal x86-64 path (got SubscriptExpr)`. **The two
    architectures name different limits for one construct**, and only one of
    them is the operative one. Already pinned by
    `limit_comptime_over_a_runtime_parameter` with `refuse_either:`.
  * (`std/builtin/len.mojo` also differs, but only by the architecture's name
    inside an otherwise identical sentence. Same verdict, same reason, and that
    is the correct kind of difference.)

Both are x86-64-side work of a sitting each, and both are in
`formal/x86_64_codegen.py`. Not started: it is [3]'s file and [3] is working in
it.

---

# 7. `comptime <expr>` — measured, and the premise it disproved

**Added 2026-09-28.** `FORMAL.md` §11.2 assigned [4] the job of making the two
engines "agree about `comptime`, and agree loudly", on a table that said the
interpreter does not have the construct, the compiled backend has it in
statement form, and the expression form silently yields 0. The table was
measured. It is also wrong in a way that matters, and the correction is the
deliverable.

## What is actually true

| spelling | `python3 fire.py run` | `fire.py build` + run |
|---|---|---|
| `comptime n = 6` | `v: 6` | `v: 6` |
| `comptime if c:` | runs | runs |
| `comptime for ..:` | runs | runs |
| `comptime assert e` | runs | runs |
| `comptime = 5` (a var named `comptime`) | works | works |
| `def f(comptime: Int)` | works | works |
| `@comptime` decorator | works | works |
| `comptime (expr)` | `NameError: name 'comptime' is not defined` | `0`, and prints `comptime: unavailable in compiled mode` |
| `comptime expr` (bare) | `NameError` | `0`, and prints **nothing** |

So: the interpreter is behind on the expression form (true), the compiled
backend supports it as a 0-valued stub (true), and **the one genuine silence is
the bare spelling** — same 0, no diagnostic.

## Why no refusal was added, which is the substantive finding

The obvious fix is to refuse `comptime <expr>` at the parse, where both backends
go through and parity becomes structural rather than a promise. It was written,
and it was reverted, because **`comptime <expr>` is real and the standard
library uses it**:

    std/algorithm/reduction.mojo:251      return comptime (CurrentPlugin.reduce_generator_fn.value())[…]
    std/math/math.mojo:630
    std/memory/stack_allocation.mojo:142
    std/reflection/reflect.mojo

Refusing it took `compile_stdlib.py` from **664 passed / 0 unexpected** to
**660 / 4**. `U` must never increase, and "the three engines agree" is worth
less than four real modules compiling. The reverted diff is kept at
`/tmp/comptime-guard.patch` for the day the evaluator lands.

The same argument kills a narrower version of the guard. A first attempt
refused on "anything that is not a DOT", which also broke `comptime = 5`,
`def f(comptime: Int)` and `comptime for i in [...]` — because in this parser a
keyword *is* an ordinary identifier, and `_CONV_KWS` depends on that. A guard
that breaks working code is worse than the bug it was written for, and the
narrowed allow-list that replaced it still had to be abandoned for the reason
above.

## What is left to do, and where

One cell, in the lowering of a comptime expression — **not** in the parser:

* the parenthesized spelling's `unavailable in compiled mode` diagnostic is
  emitted from the gimple backend (`mojo/backend_gimple/`, the same weak-stub
  convention as `module_gen.py`'s skipped generator functions);
* the bare spelling reaches the same 0 by a path that emits nothing.

Giving the bare spelling the same diagnostic is a small change and would make
every cell in the table say why. **It is not made here** because
`mojo/backend_gimple/` is outside this round's write sets — see
`FORMAL.md` §11.2's "deliberately unowned" list. `test_comptime_parity.py`
pins the silence as a NOTE rather than a pass, so the day it is fixed the test
says so, and pins the parenthesized spelling's diagnostic as a hard check so it
cannot be lost: four stdlib modules depend on that form compiling *and* saying
why.

## The real fix, for whoever wants it

Neither backend can evaluate a `comptime` expression; the compiled one stubs it
to 0. A real fix is a constant folder: `gimple_codegen.py` carries an empty
section header reading "Compile-time constant evaluators (for comptime)" and
`self._comptime_vals` / `_module_const_int` already track folded values, so the
scaffolding is half-present. That is a feature, not a fix, and it is the kind of
item §11.4's easy/hard line sends to a bug doc rather than a session.
