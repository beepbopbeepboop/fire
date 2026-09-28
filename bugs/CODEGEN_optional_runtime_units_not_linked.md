# CODEGEN_optional_runtime_units_not_linked: sqlite/zlib/ssl/ncurses have headers but no build rule

**Status: diagnosed, NOT fixed. The fix is designed and was implemented; it
regressed the self-hosted compiler and was reverted. Everything measured is
below so the next session starts from data rather than from zero.**

**Found 2026-09-27, while implementing FORMAL.md phase 0.** The premise of that
phase was "sqlite already works from gimple; make it work from formal too."
That premise is false, and this document is the correction.

## The defect

`runtime/` holds six C translation units. Exactly one of them is in a build path.

| unit | build rule? | header `#include`d unconditionally? | signatures in `_KNOWN_SIGS`? |
|---|---|---|---|
| `fire_runtime.c` | **yes** (`Makefile:333-334`, `fire.py:583`, `driver.py` via the stdlib dylib, `build_stdlib_dylib.py:498`, `build_module.py:89-94`, `comptime.py:78`) | yes | yes |
| `fire_sqlite3.c` | **no** | yes (`mojo/backend_gimple/module_gen.py:6788`) | yes (22, `gimple_codegen.py:2364-2386`) |
| `fire_zlib.c` | **no** | yes (`:6789`) | yes (6) |
| `fire_ssl.c` | **no** | yes (`:6790`) | yes (13) |
| `fire_ncurses.c` | **no** | yes (`:6791`) | yes (18) |
| `fire_python.c` | **no** | **no** | yes (15) |

That is the worst combination available: the generated C sees a prototype and
compiles clean, and the failure appears only at link. Measured:

```
$ python3 fire.py build -o sq test_sqlite3.mojo
Linking failed: Undefined symbols for architecture arm64:
  "_mojo_sqlite3_close", referenced from: __gimple_main in ...
  "_mojo_sqlite3_errmsg", ...
  "_mojo_sqlite3_exec", ...
  "_mojo_sqlite3_open", ...
  "_mojo_sqlite3_query", ...
ld: symbol(s) not found for architecture arm64
```

Nothing noticed, because **no suite entry built any `test_sqlite3*.mojo`** and
no `*.mojo` file in the tree calls any of these namespaces. The residue was
invisible from every direction.

## Two supporting lies, both now fixed

**`test_sqlite3_min_proof.lean` is not coverage of sqlite.** It is the only
thing in the repository whose name claimed otherwise. Its `main_go` is
`(0 : UInt64)` — the "semantics" model is a constant that opens no database; its
`main_code_bytes` is a hand-written literal blob, not the output of any compile
performed there; and both `main_compile_correct` and `main_compiles_correctly`
are `sorry`. It is a worked example of the three trust boundaries, presented as
a result.

Note it **cannot** be annotated to say so: every `*_proof.lean` is a gitignored
build artifact (`.gitignore:64`), untracked and rewritten by any formal build.
Editing it is possible and pointless. The correction has to live in a document
like this one.

**`reflect.collect_runtime_exports_h` was dropping every pointer return** —
fixed in the same change, and the fix is what makes any link audit possible at
all. `reflect._PROTO_RE`'s return-type group is `([\w][\w\s\*]*?)` (non-greedy,
may contain `*`) and the separator was a bare `\s+`; C writes `char *name(...)`
with the `*` attached to the type and no space before the name, so the match
failed and every pointer-returning declaration was invisible. `fire_runtime.h`
scanned 260 of 470, `fire_sqlite3.h` 15 of 22, `fire_python.h` 6 of 15. Since
`build_stdlib_dylib.py:750-751` builds the stdlib dylib's reflection table with
that function, **the shipped dylib was advertising 260 of its own 459 runtime
entry points** — a C client resolving `mojo_c_getenv` through reflection was
told the symbol did not exist. That half is landed, pinned by
`test_runtime_header_scan.py` (suite entry `rthdrscan`).

## The fix, and why it is not landed

A data-driven registry in `build_config.py` — one entry per optional unit
(source, header, link libraries), with the `mojo_<unit>_` namespace **derived
from the header's own export list** rather than hand-copied — plus, in each link
pipeline, the same probe `fire.py` and `driver.py` already apply three times
each for the generator `.cpp`, `fire_async_runtime.cpp` and the coroutine
runtime: *does the generated C reference this runtime's namespace?* If so,
compile that unit and link it with its libraries. `fire.py build` uses
`driver.compile_program` by default and falls back to `build_executable`, and
**both** need it — patching only the fallback changes nothing observable, which
is how the first attempt failed to fix anything.

It worked. Every `test_sqlite3*.mojo` built, linked and ran correctly:

```
$ fire.py build -o full test_sqlite3.mojo && ./full
rows:
1
hello
2
world
```

`fire_python.c` was deliberately **excluded** from the registry: its whole surface
is behind `#if USE_PYTHON 0`, so linking it would convert a loud link error into
a silent NULL from every `mojo_python_*` call, and its header is not
`#include`d either so the failure stays loud.

### The regression that stopped it

The self-hosted compile of `fire.py` (`make mojoc`, and
`bootstrap-stage2-cc`) failed:

```
reflect.py:814:8: error: conflicting types for 'build_config_find_gcc'; have 'char *(void)'
reflect.py:817:8: error: conflicting types for 'build_config_find_gxx'; have 'char *(void)'
reflect.py:6628:8: error: conflicting types for 'build_config_find_gcc'; have 'char *(void)'
build_config.py:20:8: error: conflicting types for 'build_config_find_gxx'; have 'char *(void)'
```

`make mojoc` **passes on a clean tree** (verified by stashing the change and
re-running), so this is a real regression, not a pre-existing failure.

**What was ruled out, by measurement:**

- Not `reflect.py`. Reverting `_PROTO_RE` to the original reproduces the error
  at the same places.
- Not `report_link_audit`, and not `re` in a self-hosted module. Deleting both
  and the `import re` reproduces it.
- Not the module-level `import build_config`. Moving it to function level — which
  is what every other optional import in `fire.py` and `driver.py` already does
  — reproduces it.
- Not `build_config.py` alone in any simple sense; reverting it changes the
  failure into a runtime `AttributeError` (expected, since `fire.py`/`driver.py`
  reference the new functions), so it could not be bisected that way.

**The shape of it.** `build_config_find_gcc` is emitted as a forward declaration
in at least three places (two in `reflect.py`, one in `build_config.py`) and
they disagree. The declaration is `char *(void)` — correct for `find_gcc`, which
returns a string literal. So a *definition* is arriving with a different
signature, or a second definition of the same symbol is being emitted into the
same translation unit. The generated C is one large `fire.ci` with `#line`
directives, and the "reflect.py:814" in that message is past the end of the
file it names — so the `#line` mapping is itself imprecise, which makes the
reported file:line unreliable as a starting point and the *emitted C* the only
trustworthy place to look.

**Why it was reverted rather than shipped.** `mojoc` is the self-hosted compiler.
`CLAUDE.md` makes the gate the definition of done for anything touching
`gimple_codegen.py` / `mojo/**` / `fire.py`, and a broken `mojoc` is a broken
gate on the two paths this whole programme exists to keep in agreement. Landing
phase 0 with a red `mojoc` to get sqlite working would trade the thing under test
for the thing being tested.

## Exact next step

One command, and it is the diagnostic, not a fix:

```
$ python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc
$ rg -n "build_config_find_gcc" fire.ci
```

`fire.ci` is written into the repository root by that build and is not cleaned
up. Two declarations and a definition, three call sites, and the emitted C will
say in one screen which pair disagrees and what the other signature is. The
hypothesis worth testing first: a *module-level dict literal containing lists*
(`OPTIONAL_RUNTIME_UNITS` is the only such construct newly introduced into a
module the self-host closure compiles) is mis-inferred, and the corruption
leaks into the next function's forward declaration. If so, the registry wants
flat tuples instead of nested dicts, which costs nothing.

If that is wrong, the next hypothesis is that `build_config.py` entering the
closure as a *transitive* dependency of `driver.py` (it was previously reached
only from `fire.py`) changes which module is compiled inline, and `fire.py`'s
`from build_config import find_gcc` plus a second inline copy both emit a
definition. `driver.py` and `fire.py` both being in the closure while
`build_config.py` is reached from both is the new thing here.

## What is already landed from this

- `reflect._PROTO_RE` accepts a pointer return. The stdlib dylib's reflection
  table goes from 260 to 459 runtime entry points. Pinned by
  `test_runtime_header_scan.py` / `rthdrscan`, by name, because a count
  assertion would need rewriting every time the runtime grows.
- `test_sqlite3_simple.mojo` called `mojo_print(n)` with an `int64` row count.
  `mojo_print` is the raw runtime sink, declared `void mojo_print(char *str)`
  (`runtime/fire_runtime.h:859`), so this dereferenced an integer as a pointer
  and **segfaulted**. It now uses `print`, the language builtin, which the
  codegen formats through to a string first. Real bug, found only because the
  link got fixed far enough to run the program — a good illustration of why
  "it builds" is not "it works".
