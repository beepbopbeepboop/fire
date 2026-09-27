# FORMAL_known_limits: the sweep residue, audited — which refusals are true, and which were lies

**Date: 2026-09-26 (wave 4, agent D5).** This is the single home for the
*verified* limits behind the residue of the formal sweep's codegen classes,
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
false about the file. That is the same class of defect D1, D2 and D3 found in
wave 4's other lanes — a plausible-looking answer where the honest one was a
refusal — and it is the reason the audit below is a table and not a summary.

## The three families, and what each one actually is

Measured on the four sweeps of this tree (`tools/formal_sweep.py`, both
architectures, both scopes; the two arm64 baselines reproduce the recorded
284/80 and 578/105 exactly).

| family | files (arm64, stdlib scope) | distinct causes | it is really |
|---|---|---|---|
| 1. `formal dylib has no public functions` | **33** (was 30) | **8** terminal modules | 7 true limits + 1 reached by a separate bug |
| 2. `__mlir_attr[...]` assembles an MLIR attribute | **36** (was 35) | **1** terminal module | 1 true limit + 3 wrong-answer holes around it |
| 3. the small shapes nobody else claimed | 10 | 7 | 5 true limits + 2 false refusals |

Two facts about the *shape* of these families matter more than their sizes,
and neither is visible from the finding count:

- **Family 1 is 33 files and 8 files.** Every one of the 33 is blocked by one
  of eight modules, and the largest of those (`_assembly.mojo`) accounts for
  19. Nothing here is 33 separate problems.
- **Family 2 is 36 files and 1 file.** Thirty-four of the 36 are
  `CODEGEN/DEPENDENCY` through `std/sys/info.mojo`; the 36th is `info.mojo`
  itself. On x86-64 the family is **1 file**, because that backend refuses
  `ComptimeIfStmt` in `info.mojo` *before* it reaches the MLIR template — the
  limit is identical, the cascade order is not. Any future work on family 2
  should start from `std/sys/info.mojo` and expect the other 35 to follow or
  not follow it.

---

# 1. `formal dylib has no public functions` — 33 files, 8 causes

## 1.1 The audit table

Every terminal module, its file count, and the verdict. "True limit" means
*the refusal is correct and the file really has nothing an importer could
bind*. The evidence column is what was measured, not what the message says.

| terminal module | files | what the file actually declares | verdict |
|---|---|---|---|
| `std/sys/_assembly.mojo` | 19 | one public `def inlined_assembly[…]` (generic, variadic over `*types: AnyType`, body is `__mlir_op.\`pop.inline_asm\``) | **true limit** |
| `std/reflection/function.mojo` | 5 | one `struct ReflectedFn[func_type, func]` (generic); a `comptime reflect_fn[…] = ReflectedFn[func]` alias; two `@staticmethod` methods, `display_name()` concrete and `linkage_name[…]` generic | **true limit** |
| `std/sys/_io.mojo` | 3 | three `comptime` constants (`stdin`/`stdout`/`stderr`), no declaration at all | **true limit** |
| `std/algorithm/backend/tile.mojo` | 2 | four overloads of `def tile[…]`, all generic | **true limit** |
| `std/utils/_select.mojo` | 1 | one `def _select_register_value[…]` — private *and* generic | **true limit**; the message names only the privacy, which is the operative rule but not the whole truth |
| `std/collections/string/_unicode_lookups.mojo` | 1 | eight `comptime` lookup tables, no declaration at all | **true limit** |
| `std/gpu/host/nvidia/__init__.mojo` | 1 | a docstring, no declaration at all | **true limit, but it should not be reached** — see 1.4 |
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
the single largest lever in the whole residue: it alone would unblock **27 of
family 1's 33 files**.

The six files that would *not* be unblocked by it, and why:

- `std/sys/_io.mojo`, `std/collections/string/_unicode_lookups.mojo`,
  `std/gpu/host/nvidia/__init__.mojo` declare no function at all. Monomorphizing
  nothing is still nothing. These are correct refusals **permanently**;
  `doc/ABI.md` §Aggregates is the reason (a `comptime` constant is inlined at
  its use site and crosses no boundary). **Cost to close: nothing — and that is
  the point.** They should be read as a *fact about those modules*, not as work.
- `std/utils/_select.mojo`'s only declaration is `_`-prefixed (and also
  generic — the message names only the privacy, which is the operative rule).
  doc/ABI.md's public-symbol rule excludes it on purpose. Permanent, by design.

So the **decisions** in family 1 decompose as **27 blocked on Stage 5, 6
permanent, 0 wrong.** What is wrong is the *reporting*, in three branches of
one function — §1.3 — and that is a separate axis from whether a refusal should
fire. The 6 permanent ones are the cheapest thing in this whole document: they
cost nothing to close, because the correct state is the one they are already
in.

## 1.3 The message is false about the file in three branches

`no_public_api_reason` (`formal/build.py`) exists to name *which* of the ways a
module has no boundary symbol it has hit. Three of its branches assert
something that is not true of the file they are reported against. All three
are on the **current** tree, and all three fire on a real stdlib module. None
of the three changes a verdict — the module is refused either way — so no
sweep number moves; the cost is entirely in what it tells the next reader.

**Bug 1a — a name with BOTH a concrete and a generic definition is filed as
purely generic.** `_declared_api_shape` collects generics into a `set` of
*names* (`re.findall(r'\b(?:fn|def)\s+(\w+)\s*\[', text)`) and then looks each
parsed `FunctionDef` up in it, so a name that is concrete in one place and a
template in another is counted as a template in both places. The real file is
`std/sys/terminate.mojo`:

```mojo
def exit():                        # CONCRETE, public, no template parameters
    exit(0)

def exit[intable: Intable](code: intable):   # GENERIC
    libc.exit(c_int(Int(code)))
```

and the message it gets is:

> `terminate.mojo` … every public function in it is a GENERIC template (exit)

Half of that sentence is false, and it is false in the direction that matters:
`def exit():` is a complete, concrete, public function with a body.

*Minimal reproducer* (two definitions, nothing else — no stdlib, no build):

```python
import sys; sys.path.insert(0, ".")
import formal.build as B
open("/tmp/mod_a.mojo", "w").write(
    "def exit():\n    return 0\n\ndef exit[intable: Intable](code: intable):\n    return 0\n")
print(B._export_entries(["/tmp/mod_a.mojo"]))        # []   — correct
print(B._declared_api_shape(open("/tmp/mod_a.mojo").read()))
# {'generic_funcs': ['exit', 'exit']}                — WRONG: one is concrete
print(B.no_public_api_reason(["/tmp/mod_a.mojo"]))
# … every public function in it is a GENERIC template (exit) …
```

*What it should be instead.* Two things, and the first is the load-bearing one.
(a) `_declared_api_shape` must classify **per definition**, not per name: a
`FunctionDef` is generic only if *its own* source span carries a bracket list.
The parser drops `[...]`, so the honest implementation reads the def's text
span rather than the file's name set — or, cheaper and exactly as sound, keys
the generic set on `(name, ordinal)` so the first and second `exit` are
distinguished. (b) The real reason this module exports nothing is neither of
the four named ones: it is that **`exit` is in `reflect._CLIB_SYMS`**, whose
stated reason is "already available via dlsym from the system dylibs". That
reason is right for a *call* and wrong for a *definition* — `terminate.mojo`
**defines** `exit`, and if it also exported one other name, the importer's
`exit()` would bind **libSystem's** `exit`, silently, with no diagnostic. A
fifth branch is needed, and the guard it implies is the more valuable half:
a `_CLIB_SYMS` name that the module *defines* must be exported, because
libc's is not the same function.

**Bug 1b — the fall-through branch names a privacy rule against a file with no
private declarations.** `no_public_api_reason` ends in an unconditional
`return` that says *"every declaration in it is private (a leading `_`)"*. It
is reached by **every module with at least one concrete public function that
nevertheless exports nothing** — because all four named branches are gated on
`not concrete_funcs`. `std/memory/memory.mojo` is one: it declares fifteen
public functions (`memcmp`, `unsafe_memcpy`, `memcpy`, `memmove`, `memset`,
`memset_zero`, `is_trivially_movable`, …) and four private ones, and it is told:

> `memory.mojo` … every declaration in it is private (a leading `_`)

*Minimal reproducer* — one function, no private declaration anywhere:

```python
open("/tmp/mod_b.mojo", "w").write("def strlen(s: String) -> Int:\n    return 1\n")
print(B._export_entries(["/tmp/mod_b.mojo"]))   # []  — strlen is in _CLIB_SYMS
print(B.no_public_api_reason(["/tmp/mod_b.mojo"]))
# … every declaration in it is private (a leading `_`) …   ← there are none
```

*What it should be instead.* The fall-through must not assert a reason it has
not checked. The minimum honest change is to make it state the *rule* that
actually excluded each name, computed from the same `collect_exports_src`
decision the refusal came from: "its public names are all excluded by
doc/ABI.md's export rule — `strlen` because it is a C library symbol this
path resolves with `dlsym`, and a module that DEFINES one must export its
own". Better still, the fall-through should be unreachable: every combination
of `(concrete_funcs, concrete_structs, gen_funcs, gen_structs)` should map to
a named branch, and anything left over should be an internal error rather than
a sentence about a rule that was not applied.

**Bug 1c — the "both private and parametric" branch fires on a module with no
private generics.** Its condition is `not concrete_funcs and gen_funcs and
private` — i.e. the module has *any* private declaration — and its text then
says *"the only function it declares is the generic template … which is both
private and parametric"*. `std/memory/unsafe.mojo` declares two **public**
generic functions and one private helper, and is told:

> `unsafe.mojo` … the only function it declares is the generic template
> bitcast, pack_bits, which is both private and parametric

Both halves are false: there are two, and neither is private. The same
set-non-empty / element-asserted mistake as 1a, in a different branch.

*Minimal reproducer:*

```python
open("/tmp/mod_c.mojo", "w").write(
    "def bitcast[T: Copyable](x: T) -> T:\n    return x\n\n"
    "def _helper(x: Int) -> Int:\n    return x\n")
print(B.no_public_api_reason(["/tmp/mod_c.mojo"]))
# … the ONLY function it declares is … which is BOTH private and parametric
```

*What it should be instead.* Gate on the intersection, not the union:
`set(gen_funcs) & set(private)`. If the intersection is empty the module's
public API is *all* generic and the "every public function is a GENERIC
template" branch is the correct one.

**Cost of fixing 1a/1b/1c: small** — three condition changes and one new branch
in one function, plus a real classification of `_CLIB_SYMS` names. **Why it
still matters:** `no_public_api_reason` had **no test at all** before this wave
(`grep -rn no_public_api_reason test_formal*.py` was empty), which is how three
of six branches went untested. The pins in §4.1 are what close that.

## 1.4 One of the 33 should not be in the family at all

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
"imports `.path`"). This is already recorded as open in
`FORMAL_module_exports_nothing.md`; it is repeated here because it is a
*count* correction, not a limit: **fixing `_candidates` removes at least one
file from family 1 and is a prerequisite for trusting the family's size.**
Cost: the leaf fallback in the same function is load-bearing for
`import formal.types` inside `formal/`, so this needs a real fix (compute
`..`/`.` against the *importing file's directory*, and try the parent before
the leaf) rather than a special case. Half a day, and it is not in this
document's lane — it belongs to whoever owns `formal/imports.py`.

---

# 2. MLIR attribute templates — 36 files, 1 cause, and 3 holes beside it

## 2.1 The refusal is true, and it is the right refusal

`formal/model.py`'s `multi_index_kind` reads a bracket-with-commas on one of
four names (`__mlir_attr`, `__mlir_deferred_attr`, `__mlir_deferred_type`,
`__mlir_type`) as an MLIR attribute template, and `multi_index_refusal` says
why: the elements are backtick-quoted literal fragments interleaved with
compile-time sub-expressions, the whole thing denotes a *dialect attribute*,
and **there is no MLIR in a freestanding image for the template to become**.
Materializing it as a container "would turn an attribute into a pointer to a
frame blob and disagree with the compiler that does have MLIR."

Verified: the construct in the wild is a multi-line bracket, e.g.
`std/sys/info.mojo:86`

```mojo
var res = __mlir_attr[
    `#kgen.param.expr<current_target> : !kgen.target`
]
```

and the refusal fires on both architectures. **Verdict: true limit, and
permanent on this path.** A formal image links libSystem and nothing else,
embeds no C runtime and no MLIR; there is no target for the template to
become, and a "best effort" string would be a number the source never wrote.

Wave 3's C4 established the complement, and it is the reason this is a limit
rather than a bug: across all 294 stdlib files plus this repository, `a[i, j]`
occurs ~2000 times as a generic's **explicit template parameter list**, ~90
times as `__mlir_attr[…]`, and **zero** times as an index. There is no 2-D
index to lower hiding behind these.

**What would close it, and what it costs.** Nothing on this path. The only
honest closure is a *different target*: a build that embeds an MLIR dialect
registry and evaluates `#kgen.*` attributes to concrete values at compile time
— which is what the real compiler does and is the entire content of the formal
backend's premise. Until then this refusal is the correct answer, and its cost
is 36 files of coverage that are unreachable by construction. **The one thing
worth doing is making the file count honest** (see §2.2): 36 findings, 1 file.

## 2.2 Hole 1 — the same construct in its single-element spelling fabricates a value

`multi_index_kind` is reached only for a **multi-element** subscript, and it
keys on the base name. So the *dotted* spelling of the identical construct —
`__mlir_attr.\`#kgen.param.expr<…>\`` — and the single-element bracket
spelling `__mlir_attr[x]` both fall through to the generic member-read
lowering, which reads a name that has no definition and produces **whatever
word is in the register**. It builds. It runs. It prints a number.

```mojo
# /tmp/pc.mojo — three DIFFERENT templates, one program
def main():
    var a = __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`
    var b = __mlir_attr.`#kgen.param.expr<accelerator_arch> : !kgen.string`
    var c = __mlir_attr.`#lit.zzz<qqq> : !kgen.bogus`
    print("a = %llu\n", a); print("b = %llu\n", b); print("c = %llu\n", c)
```

```
$ fire.py build --formal --no-prove --backend=arm64  -o pc.arm64 pc.mojo && ./pc.arm64
a = 10
b = 10
c = 10
$ fire.py build --formal --no-prove --backend=x86_64 -o pc.x86   pc.mojo && ./pc.x86
a = 0
b = 0
c = 0
```

Three facts, each worse than the last:

1. **The value is fabricated.** Three different templates, including a
   deliberately bogus one, all produce the same number. The template is not
   read at all.
2. **The two backends disagree.** arm64 says 10, x86-64 says 0, for the same
   source. `formal/model.py` goes out of its way to prevent exactly this —
   "the text is deliberately ARCH-FREE: arm64 and x86-64 return the same
   string, so the two architectures cannot drift on what a subscript means" —
   and here they drift on a *value*, which no shared-text discipline can catch
   because there is no refusal to share.
3. **The value is program-shape dependent, not a constant.** Add five locals to
   the program and the same expression yields **1**. So it cannot even be
   mistaken for a stable wrong answer that a test might accidentally agree
   with; it is arbitrary.

All four MLIR names are affected, in the dotted spelling:

```
__mlir_attr            Built
__mlir_deferred_attr   Built
__mlir_deferred_type   Built
__mlir_type            Built
```

**This is reachable from real stdlib source today.** `std/sys/info.mojo:32` is
the dotted form (`return __mlir_attr.\`#kgen.param.expr<current_target> :
!kgen.target\``), and 24 swept `std/` files use a dotted `__mlir_attr.`/
`__mlir_type.`.

**What it should be instead.** `MLIR_TEMPLATE_NAMES` already names the four
constructs. The check must be on the **base**, not on the base-plus-comma-list:
any `SubscriptExpr` or `MemberExpr` whose base is one of those four names is an
MLIR template and gets `MULTI_INDEX_MLIR_TEMPLATE`, whatever the index looks
like. That is a two-line change in `multi_index_kind` plus moving the
`is_multi_index` gate out of the path that reaches it — and it converts three
fabricated answers and one segfault into the refusal that is already written
and already correct. **Cost: hours.** This is in `formal/model.py`, which is
hot with four other agents, so it is reported rather than fixed here.

## 2.3 Hole 2 — a module-level `comptime X = __mlir_type[…]` is never even looked at

The refusal lives in the expression walk, and a module-level `comptime`
initializer is not part of it. So the multi-element bracket form — the exact
shape the refusal exists for — builds when it appears in a `comptime` binding:

```mojo
# /tmp/r4.mojo — the construct the refusal is FOR
comptime OriginSet = __mlir_type[
    `!lit.origin<`, 1, `>`
]
def main():
    var v = OriginSet
    print("v = %llu\n", v)
```

```
$ fire.py build --formal --no-prove --backend=arm64  -o r4.arm64 r4.mojo && ./r4.arm64
Built: r4.arm64
v = 10
$ fire.py build --formal --no-prove --backend=x86_64 -o r4.x86   r4.mojo && ./r4.x86
Built: r4.x86
v = 0
```

Compare the identical expression in a *local* `var`, which **is** refused:

```
$ fire.py build --formal --no-prove --backend=arm64 -o p5 p5.mojo
build: __mlir_attr[`#kgen.param.expr<`, n, `> : !kgen.string`] assembles an MLIR
attribute from a template of backtick-quoted literal fragments and
compile-time sub-expressions: it is not a subscript, and there is no MLIR on
this path for the template to become. …
```

**And this one is a false PASS in the baseline.** `std/builtin/type_aliases.mojo`
is not in the sweep's findings at all — it builds, it is counted in the 105 —
and it contains, at lines 146/149/153/157, three dotted `__mlir_type.\`…\``
aliases and one multi-element `__mlir_type[…]` template. Any program that
imports `OriginSet`, `Never` or `EllipsisType` from it gets a fabricated word.

**What it should be instead.** The `comptime` initializer is a compile-time
expression and must go through the same `_emit_expr` walk as any other; the
walk's *refusals* are what is missing, not its lowering. **Cost: hours**, and
it is the same file as §2.2. Together: one predicate, two call sites.

## 2.4 Hole 3 — `__mlir_op` builds and segfaults

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
Segmentation fault: 11
```

`std/sys/_assembly.mojo` — the module that heads 19 of family 1's files — is
built out of exactly this construct. **Verdict: refusal-logic bug (a gap, not
a false refusal).** `__mlir_op` needs to be *refused* with the same
MLIR-template wording, and the honest reason is the one its own comment
contradicts: the bracketed list is MLIR op attributes, which is a different
node, and the `pop.inline_asm` body is `__mlir_attr` again, so there is no
call to lower either. **Cost: minutes**, once §2.2's predicate exists.

## 2.5 The pins

§4.2. The true limit (the multi-element template) is pinned by a `refuse:`
case, which **fails when the limit is lifted** — the intended anti-rot
direction. The three holes above are **not** pinned as limits, because pinning
them would cement a fabricated answer as intended behaviour; they are written
up here with reproducers and left for the owning agent.

---

# 3. The small shapes — 10 files, 7 causes, 2 false refusals

| shape | files | verdict | evidence / what it should be |
|---|---|---|---|
| `constructing Error has no representation` | 3 (`std/testing/prop/{__init__,random,runner}.mojo`) | **refusal TRUE, route WRONG** | `Error` really is 2 fields, so it does not fit one word. But it is refused by a **hard-coded name list** (`model.UNREPRESENTABLE_TYPE_CTORS`) that fires *before* the shape check — see 3.1 |
| `constructing DType has no representation` | 0 today; reachable | **REFUSAL-LOGIC BUG** | `DType` is a **one-field** struct. See 3.1 |
| `String(...) takes exactly one value to convert (got 0)` | 1 (`std/format/repr.mojo`) | **REFUSAL-LOGIC BUG** (over-refusal) | `String()` is the language's empty-string constructor and a string is a `char *`; `String("")` builds and `len` is 0. See 3.2 |
| `comptime X = ... does not fold to a compile-time constant` | 2 (`std/math/polynomial.mojo`, `std/algorithm/backend/tile.mojo`) | **true limit**, with **arch drift** | `comptime n = len(coefficients)` over a *runtime* parameter. arm64 refuses with this; **x86-64 refuses with `unsupported statement ComptimeVarStmt on the formal x86-64 path`**, so the two architectures name different limits for one construct |
| `S(...) takes no arguments on this path` | 1 (`std/gpu/host/func_attribute.mojo`) + the `DType` case | **true limit** | a struct is default-initialized and its fields assigned; a positional-argument construction is not a shape this backend honours. Same message on both arches. **Already pinned** by `struct_ctor_args_both_backends` (`test_formal_run.py:308`) |
| `unsupported expression EllipsisLiteral` | 1 (`std/builtin/len.mojo`) | **true limit**, **weak message** | `def len(value: StringSlice) -> Int: ...` has no instructions. The message does not say what to do. (A `...` in a *trait* method that is never called builds, so the refusal is reach-dependent, not spelling-dependent — correct, but worth knowing) |
| `a Optional receiver is stored in a container` | 1 (`std/iter/__init__.mojo`) | **true limit** | by-reference receiver work; **already pinned** by `byref_refuse_stored_in_a_list` (`test_formal_run.py:1672`). Not duplicated here |

## 3.1 `UNREPRESENTABLE_TYPE_CTORS` is a name list where the backend already knows the answer

`model.UNREPRESENTABLE_TYPE_CTORS` is a 14-name tuple. The backend does not
need it: `model.struct_fields` reads a struct's field count, and "a formal
value is one 64-bit word, so the field count is the whole of the decision" is
already the stated rule everywhere else in that file. The list is a hand-kept
duplicate of a derived fact, and it has a false entry:

```
std/builtin/dtype.mojo    DType   nfields=1  ['_mlir_value: Self._mlir_type']
```

**One field. A formal value is one 64-bit word. So a `DType` *is* one thing**
and the message "a formal value is one 64-bit word, and DType is not one thing"
is false. Minimal reproducer — two programs, identical apart from the struct's
name:

```mojo
# /tmp/t_d3.mojo — named DType
struct DType:
    var _mlir_value: Int
def main():
    var d = DType()
    d._mlir_value = 7
    print("v = %d\n", d._mlir_value)
```
```
build: constructing DType has no representation on this path (a formal value is
one 64-bit word, and DType is not one thing) — previously this emitted a call
to a symbol named 'DType' that nothing defines
```

```mojo
# /tmp/t_d5.mojo — the SAME struct, renamed
struct DTypeX:
    var _mlir_value: Int
def main():
    var d = DTypeX()
    d._mlir_value = 7
    print("v = %d\n", d._mlir_value)
```
```
Built: t_d5.aout
v = %d\n 7
```

Same shape, opposite verdict, decided by a spelling. And the `DType` refusal is
not even the *operative* one: the 1-argument form `DTypeX(7)` is refused by the
shape rule anyway (`DTypeX(...) takes no arguments on this path`), so what
actually stops the program is the arity rule, and the name list gets there first
and says something else.

**What it should be instead.** Delete the tuple and ask the struct: if the name
is not a struct in this image, it is an extern (today's fall-through); if it is
a struct, `_emit_struct_constructor` already knows whether its fields fit. A
name that is a struct *template* (`SIMD`, `List`, `Optional`, `Tuple`, …) is
the genuine unrepresentable case and should be recognised as such, by asking
whether the name is a generic — not by being typed into a list. **Cost: an
afternoon**, and the list stops being something a future edit has to remember
to update. Reported, not fixed: `formal/model.py` is hot, and D4 already has a
case in `test_formal_run.py` waiting on a reworded version of this very
message.

## 3.2 `String()` — a constructor mistaken for a conversion

`std/format/repr.mojo:28` is `var string = String()`. The refusal is:

> `String(...)` takes exactly one value to convert on this path (got 0
> argument(s))

The reason given is that "a conversion has one operand" — but `String()` is not
a conversion, it is the language's **zero-argument empty-string constructor**,
and a string on this path is a bare `char *` to NUL-terminated bytes interned
into `__TEXT,__text`. The empty string is the interned `""`, which this path
already has:

```
$ cat t_str.mojo
def main():
    var s = String("")
    print("len=%d\n", len(s))
$ fire.py build --formal --no-prove --backend=arm64 -o t_str t_str.mojo && ./t_str
Built
len=%d\n 0
```

So the value is representable, the correct answer is available, and the
refusal is over-strict with a reason that does not apply to the construct.
**Verdict: refusal-logic bug (over-refusal). What it should be:** route
`String()` / `StringRef()` with zero operands to the interned empty literal
rather than through the identity-conversion arity check, which should apply
only when there *is* an operand. **Cost: a few lines** in
`_emit_type_constructor`, in a file four agents are editing — reported.

---

# 4. The pins

Every true limit above is pinned by a case whose expected outcome is a
**refusal**, using the repo's existing mechanism: a `refuse:<needle>` entry in
`test_formal_run.py`'s `CASES` for the codegen limits, and a check in
`test_formal_imports.py` for the export rule. A `refuse:` case asserts that the
build **fails with that text**; so if the limit is closed — the refusal stops
firing — the case goes red, which is the same anti-rot direction `expect=`
markers use in `tools/suite.py` and the reason they are not a silenced test.
**Verified fail-when-removed for every pin listed here** — see §5.

## 4.1 Family 1, in `test_formal_imports.py`

| pin | asserts | fails when |
|---|---|---|
| `test_a_module_with_no_boundary_symbol_is_refused` | a module whose only public decl is a generic template builds to a **non-zero exit**, and the message names the module and says GENERIC | Stage 5 lands, or the export rule is relaxed |
| `test_a_generic_template_is_not_exported_under_its_base_name` | `_export_entries` on a generic-only module is `{}`, while the same module with one concrete function exports exactly that name | someone "fixes" the 33 files by exporting templates — the wrong answer this mechanism exists to prevent |
| `test_a_clib_named_definition_is_refused_not_blamed_on_privacy` | a module defining only `strlen` is refused, and the message does **not** say "every declaration in it is private" | bug 1b is fixed, or regresses |
| `test_a_concrete_and_a_generic_of_one_name_are_told_apart` | `_declared_api_shape` on `def f()` + `def f[T](…)` counts one concrete and one generic | bug 1a is fixed, or regresses |
| `test_a_public_generic_is_not_reported_as_private` | a module with two public generics and one private helper is not told "the only function it declares … which is both private and parametric" | bug 1c is fixed, or regresses |

## 4.2 Families 2 and 3, as `refuse:` cases in `test_formal_run.py`

| case | construct | needle |
|---|---|---|
| `limit_mlir_multi_element_template` | `__mlir_attr[\`x\`, n, \`y\`]` | `refuse:assembles an MLIR attribute from a template` |
| `limit_comptime_over_a_runtime_parameter` | `comptime n = len(xs)` in a function | `refuse_either:does not fold to a compile-time constant\|unsupported statement ComptimeVarStmt` |
| `limit_ellipsis_function_body` | `def f(v): ...` | `refuse:unsupported expression EllipsisLiteral` |

Three, not four, and the fourth is deliberately absent: a struct's
positional-argument construction is **already pinned** by
`struct_ctor_args_both_backends` (`test_formal_run.py:308`) — same needle, both
backends, same refusal — so a second case asserting the same thing would be a
parallel implementation of a pin that already exists rather than extra
coverage. Same for the `Optional`-receiver-in-a-container shape, pinned by
`byref_refuse_stored_in_a_list` (`test_formal_run.py:1672`).

---

# 5. Verification

## 5.1 The sweeps reproduce, and nothing moved

Four runs of `tools/formal_sweep.py` on this tree, both architectures, both
scopes:

| sweep | result |
|---|---|
| `--no-stdlib` (repo) arm64 | 284 files, PASS=80, coverage 80/120 = 66.7% |
| default (repo + `std/`) arm64 | 578 files, PASS=105, coverage 105/403 = 26.1% |
| `--no-stdlib --arch x86_64` | 284 files, PASS=79, coverage 79/119 = 66.4% |
| default `--arch x86_64` | 578 files, PASS=103, coverage 103/403 = 25.6% |

The two arm64 file/PASS counts reproduce the wave-start baselines exactly
(284/80 and 578/105). The coverage *denominators* are smaller than the
baseline's (120 vs 131, 403 vs 414) because three other agents' changes landed
in `formal/` between the baseline and this run — that is their movement, not
this document's.

File-level set diff against the baselines, both arm64 scopes: **0 new findings,
0 fixed, 33 class changes.** All 33 are D4's by-reference work in flight — 11
`CODEGEN → CODEGEN/DEPENDENCY` and 11 `CODEGEN → HOST-IMPORT`, plus the 11
duplicated across the two scopes. Three of the 33 are why family 1 reads 33
here and 30 in the baseline: `std/atomic/atomic.mojo`,
`std/gpu/sync/semaphore.mojo` and `std/utils/lock.mojo` had a *direct* refusal
replaced by a dependency chain whose terminal is `_assembly.mojo`. They were
already findings; only the blocking reason moved.

## 5.2 The pins, and the fail-when-removed demonstration

Every pin in §4 was shown to go **red** when its limit is removed. The limits
were removed in a scratch copy of the tree (`tar` to `/tmp`, `formal/` patched
there, this tree untouched), because `formal/` is shared with four other
agents:

| pin | how the limit was removed | result |
|---|---|---|
| `limit_mlir_multi_element_template` | `multi_index_kind` returns `None` for an MLIR base | **FAIL** — `--backend=arm64 BUILT a construct that has no representation … the binary is the real answer here` |
| `limit_comptime_over_a_runtime_parameter` | the `resolved is None` raise replaced by `resolved = ("int", 0)` | **FAIL** — same "BUILT" message |
| `limit_ellipsis_function_body` | `EllipsisLiteral` lowers to `mov x0, #0` on arm64 / a different message on x86-64 | **FAIL** — same "BUILT" message |
| `struct_ctor_args_both_backends` (pre-existing) | both `raise CodegenError` sites for positional struct construction disabled, both backends | **FAIL** — "refused, but not with the expected words", i.e. it now falls through to a deeper refusal, which is exactly what the needle is there to catch |
| `test_a_generic_template_is_not_exported_under_its_base_name` | `reflect.collect_exports_src` relaxed to admit generics | **FAIL** |
| `test_a_module_with_no_boundary_symbol_is_refused` | demonstrated differentially, because `build()` runs `fire.py` in a **subprocess** and an in-process patch of the export rule cannot reach it: the same harness over two modules differing only in genericity | `generic-only → rc=1` (refused), `concrete → rc=0` (builds), so the `returncode != 0` assertion is discriminating |

The three message-accuracy guards in `test_formal_imports.py` are the
anti-rot-in-both-directions demonstration for the expected-failure mechanism
itself, which was checked by deliberately breaking it in a copy of the test
file:

```
FAIL  a package dylib exports nothing and says namespace
      marked expect=… but it PASSES — drop the marker
STALE  a test that does not exist
      marked expect=… but is not in TESTS — drop the marker
formal imports: PASS=25 EXPECTED=3 FAIL=2      exit=1
```

So a marker that goes green is a failure, a marker for a test that no longer
exists is a failure, and neither can rot.

## 5.3 The suites

| command | result |
|---|---|
| `make check` | 7 passed, 0 failed, 0 skipped |
| `make check-formal` | 3 passed, 0 failed — `test_formal.py`: **PASS=40 KNOWN-GAP=3 FAIL=0** |
| `make check-formal-x86` | 3 passed, 0 failed — `test_formal.py --backend x86_64`: **PASS=43 KNOWN-GAP=0 FAIL=0** |
| `make check-formal-run` | 2 passed, 0 failed — `test_formal_run.py`: **PASS=161 FAIL=0** |
| `make check-formal-dylib` | 3 passed, 0 failed — `test_formal_dylib.py`: **PASS=11 FAIL=0** |
| `make check-formal-imports` | 3 passed, 0 failed — `test_formal_imports.py`: **PASS=26 EXPECTED=3 FAIL=0** (was 24/0) |
| `make check-formal-sweep` | 3 passed, 0 failed — `test_formal_sweep.py`: **Ran 55 tests … OK** |
| `python3 test_suite.py` | **43 passed, 0 failed** |

**No stale `EXPECTED_FAILURES` entry.** `test_formal.py`'s three arm64 markers
(`either`, `both`, `fib`) all still fail — `KNOWN-GAP=3` — and
`EXPECTED_FAILURES_X86_64` is empty and stays empty. `test_formal_run.py` has
no expected-failure list. The three new markers in `test_formal_imports.py` are
the only ones added, and all three fail for the reason each records.

`prooflib` built cleanly throughout (0.0 s, exit 0) — another agent's
`lib/ProofLib.lean` is in flight per `git status`, but the lock-and-recheck
from `c85c001` meant this wave never waited on it.

