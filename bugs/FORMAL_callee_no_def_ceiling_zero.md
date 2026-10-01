# `callee has no definition on this path`: the ceiling is ZERO, and four of its five sentences were false

**Status: the refusal is now TRUE of every file it names (landed), and the
construct's ceiling is 0 of 12 — no file the sweep files under it can be
unblocked by anything done here. The hand-off itself is still refused, and the
step that would allow it is written down at the end.**

The row is `bugs/FORMAL_sweep_work_map_2026-09-30.md` row 8 (12 files, all
in-file, no dependency chain, so the bound and the value look identical on
paper). This document is the measurement of the second, and the split of the
row's one sentence into the five things it was standing for.

---

## 1. The ceiling, per file, on a cold CAS

Every file re-built with `model.frame_undefined_callee_refusal` patched to
`None` **in that process only** (nothing in the tree edited; §6 has the six
lines), so the build walks past this refusal and reports the next one:

    env GMOJO_HOME=$PWD/.tmp/gmojo_nc python3 next_refusal.py <file>

A cold CAS is not optional here: `cas.formal_build_key` does not fold in the
sources of the modules a file imports
(`bugs/FORMAL_sweep_cache_ignores_imports.md`), and nine of the twelve import
most of the standard library. Run twice — before the change and after it, on two
different cold CAS directories — and the second cause is identical in all
twelve.

| file (relative to the stdlib's `std/`, or the repo) | callee | what stops it NEXT |
|---|---|---|
| `base64/base64.mojo` | `_b64encode` | **dependency**: `std.memory` → `builtin_slice.mojo` `Slice___eq__`, a field access through a parameter |
| `collections/_conditional.mojo` | `__get_mvalue_as_litref` | **dependency**: `std.builtin.device_passable` → `function.mojo`, `__mlir_attr[...]` |
| `collections/interval.mojo` | `debug_assert` | `a String receiver is passed to writer.write … method call on a value receiver` |
| `collections/list.mojo` | `iter` | `a List frame address is passed to origin_of() … a wrong category of argument` |
| `collections/optional.mojo` | `__get_mvalue_as_litref` | `a Optional receiver is passed to encoder.encode … method call on a value receiver` |
| `ffi/unsafe_union.mojo` | `__get_mvalue_as_litref` | **dependency**: `std.builtin.rebind` → `builtin_slice.mojo` |
| `format/_utils.mojo` | `ElementFn` | `a FormatStruct receiver is returned from a method … which did not create the frame` |
| `utils/coord.mojo` | `__get_mvalue_as_litref` | `a Coord receiver is passed to the call … method call on a value receiver` |
| `utils/variant.mojo` | `__get_mvalue_as_litref` | `a List frame address is passed to origin_of()` (value-only callee) |
| `formal/build.py` | `discover_closures` | **host import**: `copy` |
| `scripts/repro_ftplib_isolated.py` | `getattr` | **host import**: `subprocess` |
| `test_formal_call_proof_gen.py` | `hasattr` | **host import**: `ast` |

**Zero.** Six of the twelve are not `codegen` findings about this file at all
once this refusal is out of the way — they are `codegen/dependency` (3) or
`not-answerable/host-import` (3), which is where the sweep would classify them
if the import diagnosis were not preempted. **That preemption is its own defect
and its own document** — a frame refusal raised from `_prepare_functions` beats
the import diagnosis for any file that does both, which is 80 in-scope files,
and fixing it moves six rows of the map at once:
`FORMAL_frame_refusal_preempts_the_import_diagnosis.md`.

The other six are each behind a refusal that belongs to a *different* row of the
map: the method-call-on-a-value family (`formal-receiver-handoff`), the
value-only-callee family (`formal-frame-by-value`, `origin_of`), and the
frame-escape family (`formal-frame-escape`).

So the row's 12 is an upper bound with **no** slack, and this construct cannot
be worth a fix on file count. It is still worth something, and §2 is what.

## 2. The row's one sentence was five sentences, four of them false

The fifth branch of `frame_receiver_escape_refusal` said, of all of these:

> a X receiver is passed to `f()`, which is a name with no definition in hand:
> **this module's own functions are the only ones in this image**, and the
> symbol is unbound before the receiver's layout is a question. … there is no
> such callee here to be compiled.

Measured over 987 files (the repo, the stdlib's `std/` and `test/`), 41 files
reach this branch. After the change, by arm:

| arm | files | is the old sentence true of it? | minimal repro |
|---|---|---|---|
| **imported free function** — the callee is bound by a `from … import …` | **26** (2 in the sweep's default scope) | **NO, twice.** It IS compiled, into another module's library; and it is not one of this module's own functions. | `from lib import take_it` + `take_it(p)` |
| **compile-time parameter** — the callee is one of the enclosing `def[…]`'s parameters | 1 | **NO.** No compilation anywhere will define it until a call site instantiates it; nothing is missing. | `def drive[Fn: def(mut W)]` calling `Fn(w)` |
| **comptime reflection intrinsic** — `__get_mvalue_as_litref` | 5 | true but unhelpful: it names an MLIR-yielding intrinsic and says "look for a missing export" | `var lit = __get_mvalue_as_litref(q)` |
| **star import** — the callee is bound by nothing but a `from M import *` | 2 | **NO.** `M`'s export set may bind it, and that is a library this pass has not built. 22 stdlib files write one. | `from lib import *` + `take_it(p)` |
| **genuinely unbound** | 7 (4 in scope) | **YES** — the only one it was true of. | `mojo_print(p)` |

The two repro programs are five lines each and both are refused the same way on
arm64 and x86-64; they are `test_formal_run.py`'s
`byref_refuse_imported_free_function`, `byref_refuse_star_imported_free_function`,
`byref_refuse_compile_time_parameter` and `byref_refuse_reflection_intrinsic`.

A reader who believed the old sentence about `_b64encode` went looking for a
missing export of a module that exports it, or for a callee to add to the wrong
file — which is the failure mode this whole refusal family documents itself as
existing to prevent ("a message that asserts a mechanism which is not operating
sends the reader after a non-bug").

## 3. What landed

* `formal/model.py`: `frame_undefined_callee_refusal` — one classifier, five
  texts — and `frame_receiver_escape_refusal`'s fifth branch delegates to it,
  keeping its own five-case order (an ADDRESS constructor still returns `None`,
  which is what `Pointer(to=s)` depends on). One more case sits BEFORE the
  delegation and not in it: `FRAME_VARIADIC_BUILTIN_CALLS`, which is `print` —
  a name this backend compiles, so it never belonged in "no definition in hand"
  at all. §5 has the measurement.
* `formal/build.py`: `_check_frame_escapes`'s "not in this image" branch passes
  the three facts the classifier needs. `imported` is threaded from
  `_prepare_functions`, which is the only function that has the module
  statements.
* `formal/imports.py`: `imported_bound_names` (every name a `from … import …`
  binds here, private ones included) and `star_imported_modules`. Both read the
  AST, so they are available **before** `_resolve_imports` — which is where the
  frame analysis sits, and why they had to be AST readers and not manifest
  readers.
  `reexported_names` now shares `_from_import_bindings` with them; it is
  **byte-identical** to the loop it replaced over all 987 files (checked with
  `.tmp/diff_reexport.py`, `identical=987 differ=0`), which is the only reason
  that consolidation is safe: it is a table every dylib manifest is written
  from.

Nothing else moved: over the same 987 files, 41 messages changed and **all 41
are this construct** — no other file's message and **no file's class** changed.

**All five arms keep the clause `which is a name with no definition in hand`,
and that is load-bearing.** `tools/formal_sweep.py`'s `_FRAME_ESCAPES` and
`tools/formal_sweep_causes.py`'s cause table both key on that exact substring —
it is what keeps this family out of the `receiver passed as an argument` bucket
its own message begins with. An arm that reworded the opening would not fail
any test: it would quietly move every file it names into whichever family
matches next, with a wrong number in a table a planner acts on. The first
version of this split had four arms that did *not* keep it. Measured after the
fix: 41 files, and **all 41 still classify as `callee has no definition on this
path`** in both tools (`formal_sweep._refusal_family` and
`formal_sweep_causes`' label, run over the real messages).

## 4. What is NOT fixed, and the exact next step

The hand-off stays refused in all five arms, and for the imported arm that is
right rather than cautious. Measured, in the smallest program with the shape:

    # lib.mojo                        # prog.mojo
    struct P:                         from lib import P, take_it
      var a: Int                      def main(n):
      var b: Int                        var p = P()
                                      p.a = 3; p.b = 4
    def take_it(p: P) -> Int:           return take_it(p) + n
      return p.a + p.b

* **Same file**: builds, runs, returns **17** for `n = 10`. The hand-off into a
  callee's parameter is followed and is correct.
* **Two modules**: refused — and refused **inside the callee module**, before
  the caller's own refusal: there `p` is a parameter with no call site to
  establish it, and `p.a` is refused as "a field access through a base nothing
  establishes". A module is compiled with its own call sites, and the importing
  file's call site is not one of them.

So the missing thing is not the refusal, it is a **per-parameter contract in the
dylib manifest**: for each exported function, which parameters its own analysis
made frame holders and of which struct. With that, the importer can compare it
against the argument it is passing and either follow the address or refuse for a
real disagreement — the cross-image half of `_check_holder_agreements`, which
today stops at the module boundary. The manifest (`formal/imports.py`'s
`build_module_dylib`) records `exports` / `reexports` / `constants` / `module`
and no parameter information at all.

Two things that are NOT this row's work and are named here so nobody measures
this row twice for them:

1. **The callee module's own refusal** (`take_it(p: P)` with no call site) is the
   map's row 3, "a method parameter's field, with no call site to establish it"
   — 27 files, claimed by `formal-method-param-field`
   (`construct:method-param-field-access`). Until that lands, no cross-module
   free-function hand-off can be built at all, whatever the manifest carries.
2. **The 24 `test/` files** in the imported arm are outside the sweep's default
   scope (`DEFAULT_STDLIB_SUBTREES = ("std",)`), which is why the map says 12
   where the real population over all roots is 41. That is a property of the
   sweep's scope, not a disagreement about the taxonomy.

**Found in passing, not fixed, not this row's to fix:**
`bugs/FORMAL_aliased_reexport_publishes_the_wrong_name.md` — the sibling reader
this change added (`imported_bound_names`) records the name a `from … import`
BINDS, and `reexported_names` records the name the defining module gave it, so
`from leaf import base as aliased` in a package `__init__` publishes `base` and
the consumer's `aliased(21)` cannot bind. Measured, with the build refusing to
emit an image whose symbol nothing provides.

## 5. The histogram that found the last false clause

The name histogram per arm (over the 41, which is what a cause table prints per
row) is how the two remaining imprecisions in this family were found, and both
are now fixed:

| arm | names |
|---|---|
| imported free function | `_b64encode`, `_write_float` ×2, `assert_equal` ×10, `assert_true` ×2, `rand`, `randn`, `realpath`, `split`, `exists` ×2, `write_sequence_to`, `_count_utf8_continuation_bytes`, `_end_metal_trace_capture`, `keep` |
| comptime reflection intrinsic | `__get_mvalue_as_litref` ×5 |
| compile-time parameter | `ElementFn` |
| star import | `assert_true`, `assert_equal` |
| unbound | `getattr`, `hasattr`, `iter`, `debug_assert`, **`print`**, **`type_of`** |

* **`print` is a name this backend COMPILES** — `print("hi")` builds, runs and
  prints — so "no definition in hand" was false of it, and it is the most
  consequential name on this list: with the refusal lifted, `print(<frame>)`
  builds, runs, **exits 0** and prints the frame's ADDRESS as a decimal, 6102330608
  on arm64 and 13027830976 on x86-64 for the same source, and a different number
  on every run because the address moves. It now has its own refusal
  (`FRAME_VARIADIC_BUILTIN_CALLS`), deliberately NOT in `FRAME_C_VALUE_CALLS`,
  whose sentence says "a C library entry point" and `print` is Mojo's builtin
  lowered through `_emit_print` in each backend's call emitter. It says
  **"frame address is passed to"**, lowercase and not "receiver is passed to",
  because those are the two sweep markers either side of it: written as
  "receiver" this file counted in the position family, and written as
  "frame ADDRESS" it fell into `other refusal` — the bucket this taxonomy
  exists to empty. Both were numbers in the wrong column with no test failing,
  so the one file it moves (`test/builtin/test_default_writable_compile_fail.mojo`,
  out of the sweep's default scope) is counted in row 7 and not in this row:
* **`type_of(x)` is not implemented on this path at all** (no occurrence of the
  name in `formal/`), so for it the generic sentence is true and it stays there.
* `getattr`, `hasattr`, `iter` are host builtins with no Mojo source anywhere,
  and `debug_assert` is a stdlib function (`std/builtin/debug_assert.mojo`) that
  `std/collections/interval.mojo` does not import — so "nothing in this image
  binds it" is true of all four. The useful refinement for them ("the backend has
  no implementation of this builtin") would need a table of what the backend DOES
  implement, and the honest test for that today is a name somebody wrote down
  after measuring it — see the `print` note above for why that is a debt rather
  than a design.

**What would retire the table**: the emitter-level builtins are hard-coded per
backend (`formal/arm64_codegen.py:5157` and `formal/x86_64_codegen.py:4926` each
spell `if name == "print"`), so "which builtins does this backend compile" is
now in three places — two emitters and this model set. A single published
`model.EMITTER_BUILTINS` that both emitters' `if name == …` chains and
`FRAME_VARIADIC_BUILTIN_CALLS` read would make the three agree by construction;
that is a change to both backends' call emitters and is not this construct's to
make.

## 6. How to reproduce the measurement

**The row's numbers** come from the sweep's own tooling, which is committed:

    python3 tools/formal_sweep.py            # the run that produced the log
    python3 tools/formal_sweep_causes.py --min 5 build/sweep.log

**The per-file ceiling** needs one build per file with this refusal suppressed
IN-PROCESS — six lines, and no edit to the tree (which is why it is not a patch
and why it can be re-run on someone else's branch without touching it):

    import sys, os, tempfile; sys.path.insert(0, os.getcwd())
    from formal import model as M
    M.frame_undefined_callee_refusal = lambda *a, **k: None   # walk past it
    import formal.build as B
    B.compile_formal(sys.argv[1], prove=False,
                     output=os.path.join(tempfile.mkdtemp(), "a.out"))

Run it under a **cold CAS** (`env GMOJO_HOME=$PWD/.tmp/gmojo_nc`) — nine of the
twelve import most of the standard library, and `cas.formal_build_key` does not
fold a module's sources in (`bugs/FORMAL_sweep_cache_ignores_imports.md`), so a
warm CAS replays verdicts about those modules' old contents.

**The minimal programs** are `test_formal_run.py`'s `byref_refuse_*` cases —
imported free function, star import, compile-time parameter, reflection
intrinsic, bare method name, `print` of a frame, and the `byref_refuse_invisible_callee`
guard for the generic sentence — committed, each refusing identically on arm64
and x86-64:

    python3 test_formal_run.py byref_refuse_imported_free_function

**The 41-file census by arm** was taken with a parse-plus-one-pass probe rather
than 987 builds: the refusal is decided in `_prepare_functions`, which runs
before codegen, emit and link, so `formal.build.parse_module` +
`_imported_structs` + `_prepare_functions` per file answers "which refusal is
this file's" with no image and no CAS. That probe was scratch (`.tmp/`, not
committed — it is a one-off, and `tools/formal_sweep.py` is the committed
authority for the same question at the cost of a build per file).