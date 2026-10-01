# FORMAL_imported_generic_reported_as_a_module_level_name: `module_global_refusal`'s `imported` branch names the wrong thing

**Found 2026-09-29 while landing the target-query evaluator; not fixed, because
it is in the export/dylib machinery and not in `construct:comptime-mlir-attr`.
Re-measured 2026-09-30, and two of the three claims below needed correcting —
read the note at the end before starting.**
The class it belongs to is the one `FORMAL_known_limits.md` exists to enforce: a
refusal that is *false about the file it is reported against* sends the reader
looking for a construct that is not there.

## What was run

```
$ python3 tools/formal_sweep.py ../modular/mojo/stdlib/std/sys/_assembly.mojo
CODEGEN/DEPENDENCY: …/std/sys/_assembly.mojo  (build: _assembly.mojo imports
  'std.collections.string.string_slice', which cannot be built either:
  inlined_assembly: '_get_kgen_string' is imported from
  `std.collections.string.string_slice`, so it is a module-level name of another
  module. This path compiles an import into a dylib, and a module-level name is
  not exported as a word — there is no storage for it here: every value a formal
  program can name lives in a function's own stack scratch, which is reclaimed
  when the function returns. Give it a function (a
  `std.collections.string.string_slice.fn()` call lowers) or write the value at
  the use site)
```

## What is wrong with it

`formal/model.py`'s `module_global_refusal`, the `site == "imported"` branch, is
written for a name that came from another module as a *value*. `_get_kgen_string`
is not a value:

```
$ rg -n '_get_kgen_string' ../modular/mojo/stdlib/std/collections/string/string_slice.mojo
2564:def _get_kgen_string[
2565:    string: StaticString, *extra: StaticString
2566:]() -> __mlir_type.`!kgen.string`:
```

It is a **function**, and a **generic** one. So:

* the advice is a no-op — "give it a function (`mod.fn()` call lowers)" is
  already satisfied, and a reader who follows it changes nothing;
* the actual reason is not stated at all: `reflect.EXCL_GENERIC`
  (`reflect.py:372`, used by `collect_exports_src` at 476) excludes a generic
  template from a module's export set, because a generic has no single concrete
  symbol — and `collect_exports_src`'s own docstring says the intent is that
  "importers see it as a generic and elaborate it on demand (ELABORATION.md)".
  There is no elaborator on the formal path, which is the whole of the gap.

That is also why this is not a one-word fix: the *right* sentence is a fifth
branch of `module_global_refusal`, and choosing it needs the fact "this name is a
generic", which `build.py`'s caller does not currently have. `reflect` already
computes it (`export_exclusions(src)` returns `EXCL_GENERIC` for exactly these
names), so the branch is derivable rather than hand-kept.

## What is expected

A refusal that distinguishes the two, e.g.:

> `'_get_kgen_string'` is a GENERIC imported from `std.collections.string.string_slice`, so it has no symbol in that module's dylib: a parametric function has no single concrete definition to export, and this path has no elaborator to instantiate it at the call site (ELABORATION.md describes the mechanism the real compiler uses). A concrete function in that module lowers as `mod.fn()`.

and keeps the existing sentence for a name that really is a module-level value.

## The exact next step

1. `formal/build.py`: where the `imported` symbol is placed in
   `check_module_symbols` (`M.module_symbol(name)` → `sym.site == "imported"`),
   also record whether the name is one of the exporting module's
   `EXCL_GENERIC` exclusions. That means threading the exporting module's
   `reflect.export_exclusions` result into the symbol — it is computed in
   `formal/imports.py` at dylib-build time, so the table is reachable, and the
   alternative (re-deriving it from source here) is a second copy of a rule
   `reflect` already owns.
2. `formal/model.py`: add the branch to `module_global_refusal`, keeping the
   existing one for a value.
3. `tools/formal_sweep.py`: the new wording needs a marker. It contains
   "module-level name", so it would land in whatever family that currently maps
   to — check with `python3 tools/formal_sweep.py`'s `--list` /
   `test_refusal_taxonomy.py` and add a family if the new one is genuinely
   different from "value with no representation".
4. Test: a two-file case in `test_formal_dylib.py` (a module exporting a generic,
   a program calling it) asserting the new words on both architectures.

## Why it matters beyond this file

`std/sys/_assembly.mojo` heads **17 of the 30 files** in
`FORMAL_known_limits.md`'s family 1, and it is the cycle that stops
`std/sys/info.mojo` — which is the terminal of **35 of the 46 files** in family
2. So a message that points at the wrong rule sits in front of the largest
concentration of unbuilt stdlib in the sweep, and every session that reads it
starts by looking for a missing module-level binding that is not missing.

Not measured: whether a generic call *across* a dylib boundary could be lowered
by elaborating the callee into the caller (which is what ELABORATION.md
describes, and which `formal/comptime_runner.py` is arguably half of already).
That is a much larger question than the message and is deliberately not claimed
here.

## Re-measured 2026-09-30, and what a next worker should measure first

Two of the three statements above no longer hold, and the second one changes
what the next step is.

**1. The quoted output does not reproduce for `std/sys/_assembly.mojo`.** That
file's own body is now refused for `__mlir_op` before the name walk runs
(`FORMAL_mlir_refusal_preemption.md`), so the sentence this doc is about is not
the one a reader sees there any more. The defect it describes is unchanged, and
the file is still the one that heads 17 of family 1's 30 — but the 30 seconds it
costs have moved to a message about inline assembly, which is the better answer
for that file and a worse one for a reader who wanted to know about the import.

**2. The `imported` branch is not what an imported GENERIC hits, so the fix as
written here would not fire on the case this doc is about.** Measured on this
tree with the minimal two-file case the doc does not have:

```mojo
# mylib/__init__.mojo
def widen[T: Intable](v: T) -> T:
    return v
def helper(x: Int) -> Int:
    return x + 1

# prog.mojo
from mylib import widen
def main() -> Int32:
    var v = widen(5)
    print("v=", v)
    return 0
```
```
build: prog.mojo: the image would bind 1 symbol(s) that nothing provides, so it
could not be loaded: widen. Nothing on this link line defines them: not the C
library, and not any library this program linked.
```

That is `_audit_bound_symbols`, not `module_global_refusal`. The export set
really is empty for a generic — that half of this doc is right, and
`test_formal_imports.py`'s `test_a_generic_template_is_not_exported_under_its_base_name`
pins it — but an empty export set surfaces as a name the LINK cannot bind rather
than as a `module_symbols` entry with `site == "imported"`, so the fifth branch
proposed above would be dead code for the very case that motivated it. Whoever
takes this on should decide which of the two diagnostics is the one worth
fixing, because they are reached from different places and fixing the wrong one
is a week of work that changes no message anybody reads.

**What is left of this doc, then:** the advice in the `imported` branch is a
no-op for a generic callee, and the message a reader actually gets for an
imported generic names a link line rather than genericity. Both name a cause the
reader cannot act on, and both are answered by the SAME fact —
`reflect.export_exclusions` already returns `EXCL_GENERIC` for these names, and
`reflect.py` already enumerates the sibling reasons a name has no single symbol
(`EXCL_OVERLOADED`, `EXCL_CLIB`) — so one piece of plumbing would serve both
messages, and the decision is only WHICH of the two to reach first.
