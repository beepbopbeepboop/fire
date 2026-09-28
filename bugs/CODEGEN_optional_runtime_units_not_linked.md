# CODEGEN_optional_runtime_units_not_linked: sqlite/zlib/ssl/ncurses have headers but no build rule

**Status: FIXED.** `runtime/fire_sqlite3.c` (and zlib/ssl/ncurses) are linked
when, and only when, the generated C calls them. `build_config.py` holds the
registry; both link pipelines apply the probe; `test_sqlite3_runtime.py` pins
it. Every `test_sqlite3*.mojo` builds, links **and runs** on both pipelines, and
`python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc` succeeds.

**The integrator should delete this file** (FORMAL-PARALLEL §5): the bug is
closed. What follows is kept because two of its conclusions were WRONG, and
both cost real time — a future session must not re-derive them.

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

## The fix, as landed

A data-driven registry in `build_config.py` -- one entry per optional unit
(source, header, link flags, dev package), with the `mojo_<unit>_` namespace
**derived** from the header's own export list via
`reflect.collect_runtime_exports_h` rather than hand-copied -- plus, in each
link pipeline, the same probe `fire.py` and `driver.py` already apply three
times each for the generator `.cpp`, `fire_async_runtime.cpp` and the coroutine
runtime: *does the generated C call into this runtime's namespace?* If so,
compile the unit and link it with its libraries.

Both pipelines need it. `fire.py build` uses `driver.compile_program` by
default and falls back to `build_executable`, and **patching only the fallback
changes nothing observable** -- which is how the first attempt failed to fix
anything.

`fire_python.c` is deliberately **excluded**: its whole surface is behind
`#if USE_PYTHON 0`, so linking it would convert a loud link error into a silent
NULL from every `mojo_python_*` call, and its header is not `#include`d either
so the failure stays loud.

`ssl` is **included** even though OpenSSL is not installed everywhere. A
registry row is a build RULE, not a claim that the dependency is present: the
header is `#include`d unconditionally, so a program calling `mojo_ssl_new` has
a prototype whether or not we can satisfy it. With the row it gets
`optional runtime compile failed (ssl, .../fire_ssl.c): fatal error:
openssl/ssl.h: No such file` plus the dev package to install; without it, the
same program gets `Undefined symbols ... _mojo_ssl_new`, which names none of
that and points at the wrong layer.

Result:

```
$ fire.py build -o full test_sqlite3.mojo && ./full
rows:
1
hello
2
world
```

### The regression that stopped it -- and the hypothesis that was WRONG

The self-hosted compile of `fire.py` (`make mojoc`, `bootstrap-stage2-cc`)
failed:

```
reflect.py:814:8: error: conflicting types for 'build_config_find_gcc'; have 'char *(void)'
reflect.py:817:8: error: conflicting types for 'build_config_find_gxx'; have 'char *(void)'
reflect.py:6628:8: error: conflicting types for 'build_config_find_gcc'; have 'char *(void)'
build_config.py:20:8: error: conflicting types for 'build_config_find_gxx'; have 'char *(void)'
```

**The first hypothesis in the original version of this document was wrong, and
so was the shape of the fix it recommended.** It said: "`OPTIONAL_RUNTIME_UNITS`
is the only module-level dict-literal-containing-lists newly introduced into a
module the self-host closure compiles, and the corruption may leak into the next
function's forward declaration ... the registry wants flat tuples instead of
nested dicts."

Measured: **flat tuples of flat strings reproduce the identical error.** So the
dict literal was never the cause. (The nested-container worry is real but is a
*different* failure -- see "two shape constraints" below -- and it is a silent
wrong-value, not a compile error.)

The actual cause, instrumented at `mojo/backend_gimple/module_gen.py`'s
imported-symbol extern block:

```
DBG build_config_find_gcc | inline_defined=False | global_inline_defs=True
    | func_return_types=int64_t | scan_sig='int64_t build_config_find_gcc (void)'
```

A compiler-module function reachable through that block is declared **twice,
from two independent type inferences**:

* `module_loader.load_module_from_path`'s **text scan**, which defaults an
  *unannotated* `def` to `int64_t`, and
* the function **body's own returns**, which say `char *` for
  `find_gcc`/`find_gxx` (they return a string literal).

When both land in one translation unit, gcc rejects the pair. The block emits
one copy per importing module (measured: three -- fire.py, driver.py and the
module itself), and its `#ifndef` guard is **inert**: it uses the bare symbol
name as a macro and never `#define`s it.

**The fix is the annotation, not the container shape.** `find_gcc`/`find_gxx`
now carry `-> str`, which makes the scanner agree with the body:

```
$ python3 -c "...load_module_from_path('build_config.py')..."
find_gcc -> char * find_gcc (void)
```

**Do not "fix" the inert guard by adding a `#define`.** That was measured too:
widening the skip gate to drop symbols this TU already defines removes the
duplicates, and then every importer of a cross-module helper loses its only
declaration --

```
ast_rewriter.py:61: error: implicit declaration of function 'fire_compiler__as_str_9f63a2'
```

-- because that block is the *only* declaration for a symbol the module being
emitted merely imports. The `'signature' not in sym_info` escape hatch in that
gate is load-bearing. Both facts are now recorded in a comment at the gate
itself, so the next reader does not have to re-derive them.

### Two shape constraints on the table, both measured

The registry is a **flat tuple of flat tuples of flat strings** (the link flags
are one space-separated string, not a list), and this is load-bearing rather
than stylistic. `build_config` is compiled by the self-hosted backend into
`mojoc`, and a **nested** container is not usable there: reading an element of a
nested list is lowered to `mojo_list_get_int` regardless of the element's real
type, so `(unit, source, header, ['-lssl', '-lcrypto'])` silently compares a
string element against an int and yields a garbage link flag. Verified by
compiling and running a miniature:

```
MojoList * bc2_unit_libs_9f63a2 (int64_t unit) {
  ...
  _t12 = mojo_list_get_int (_e, 0);      /* _e[0] is the STRING 'sqlite3' */
  _t13 = _t12 == unit;                    /* comparing a string as an int    */
```

Second constraint: the namespace is derived, never hand-kept, so the
longest-common-prefix computation is the single point of truth. That makes the
registry a **consumer** of `reflect.collect_runtime_exports_h` with no file in
common with the scanner's author -- so `test_runtime_dylib.py` §7 pins the two
halves against each other (namespaces that do not cover exactly their own
symbols, namespaces that overlap, a runtime symbol inside a unit's namespace).

### The probe must be call-shaped, and that is not a refinement

The first landed probe asked "does the unit's namespace appear in the
generated C". **That is wrong, and it was caught by `mojoc` itself.**
`gimple_codegen._KNOWN_SIGS` carries all 59 optional-unit signatures as STRING
KEYS, so any build that compiles the compiler has every unit's symbol names in
the generated C as string-literal data. All four units matched a program that
calls none of them, and the measured cost was that the project's own compiler
could not be built without four system development packages installed -- on this
machine, with no OpenSSL, `fire.py build fire.py` tried to compile
`fire_ssl.c` because `_KNOWN_SIGS['mojo_ssl_context_new']` is a *string* in the
output.

So `build_config._called_in_c_code` requires the name to be followed by `(`,
allowing the whitespace this codegen emits before an argument list, and not
preceded by a quote. A docstring cannot false-positive either, because a
docstring reaches the generated C as a `_slit_N = "..."` initializer, i.e.
quoted. The imprecision is deliberately on the quiet side: a unit used in a
shape the probe does not recognise is MISSED, and a missed unit is a loud
`Undefined symbols` at link, whereas a spurious unit is a needless dependency.

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
