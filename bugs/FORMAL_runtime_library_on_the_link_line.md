# FORMAL_runtime_library_on_the_link_line: the phase-2 payoff is landed and the header gap is CLOSED; two measured ceilings are open

**Status 2026-10-05 (`work/formal27-5`): the ELF HALF of this document's closing
claim was FALSE and is now corrected, and the two ceilings are re-measured on
this tree. Neither ceiling moved; the surface they are measured against grew.**

The claim was in three places — this document's last bullet,
`formal/build.py::runtime_library`'s own docstring, and the comment above the
export-trie reader in the same file — and all three said an ELF image "carries
one `lib_name` and no dependency list" and therefore "cannot carry a library at
all". **`build_elf` has taken a `deps` list and written one `DT_NEEDED` per
entry since the ELF emitter landed** — that is how an ELF image imports a module
library today — so a reader sent to look for the link line's capacity was sent
to look for a parameter that has been there all along, and the real reason went
unnamed. What is missing is an ELF **build** of `runtime/`:
`build_stdlib_dylib.runtime_dylib` builds a Mach-O dylib (its own
`_arch_or_die` checks the Mach-O that came out) and there is no ELF counterpart
beside it, so the manifest `runtime_library` would hand back names a file an ELF
loader cannot open — which is precisely what
`formal/build.py::_audit_link_line_containers` exists to refuse, from four bytes
of magic per file. The refusal the user sees (`formal/model.py`'s
`gimple_runtime_refusal`, the one function both backends read) no longer offers
"an image that cannot carry a library" as a reason; it names the container and
the other real reason, a name the library does not export. Pinned three ways in
`test_formal_runtime_link.py::test_elf_is_refused_for_the_container_and_not_for_
the_link_line`, which measures the `DT_NEEDED` pair out of a built ELF image's
own `.dynamic` rather than taking this paragraph's word for it.

**The ceilings, re-measured on this tree, both architectures byte-identical**
(the tool is a `Counter` over the export trie and `model.runtime_abi()`; the
script is §"Reproducing"):

| | this doc's §0.3 (2026-10-03) | now |
|---|---:|---:|
| word-shaped, on a formal image's link line | 258 | **272** |
| …of those, exported by the runtime library | 202 | **216** |
| …needing no heap handle | 163 | **176** |
| …needing a `void *` handle the path cannot produce | 39 | **40** |
| **ceiling 1**, word-shaped but not linked | 56 | **56**, same six families: `ncurses` 16, `sqlite3` 16, `ssl` 11, `python` 6, `metal` 5, `zlib` 2 |
| **ceiling 2**, exported and declared by no header | 4 | **4**, the same four non-`mojo_` names nothing refuses |

**So the phase-2 payoff GREW by 14 and closed nothing**, which is the same shape
as every previous re-measurement in this document and is worth saying once more
rather than leaving to be re-derived: a bigger linked surface is a bigger
surface to need a handle on, so ceiling 3 grows with the payoff rather than
being closed by it. **The 13 new names that need no handle are the whole of what
this round's re-measurement found**, and no `mojo_*` call that used to compile
stopped: the delta is additive in both directions of the same set.

**What is still open is unchanged and is not this document's to close:** ceiling
1 is a variant of `runtime_dylib` in `build_stdlib_dylib.py` keyed per optional
unit set, with `fire_ssl.c`'s missing OpenSSL headers deciding what it may link;
ceiling 3 is `FORMAL.md` phase 6. **Both are also blocked for a light worker in
a way worth recording**: closing either means building a `runtime_dylib`
variant, and `build_stdlib_dylib.py` is on this project's do-not-run list, so
the measurement that would justify either change cannot be taken here.

**`FORMAL.md` §2.2/§6's published figures are behind the tree** — it publishes
206 exported / 166 reachable where the same census measures 216 / 176, and
`test_formal_doc_truth.py` and `test_formal_runtime_link.py` are both red on
exactly that. Pre-existing, measured on this document's base, and filed as
`bugs/FORMAL_the_published_surface_figures_are_behind_the_tree.md` rather than
fixed here: `FORMAL.md`'s figure sweep is another branch's project
(`1dd68a48`/`ca50560f`, "DOCS vs REALITY"), and seven of its eight stale figures
have nothing to do with the link line.

**Re-measured 2026-10-04 (`work/formal19-4`): the "what this does not do" bullet
about proofs was STALE, and its replacement is a different doc's subject — so the
two ceilings this document names are still the two ceilings, and the honest next
step for the proof half now names an owner.** Measured, arm64,
`fire.py build --formal` (i.e. `prove=True`) on a program whose only call is a
linked entry point:

    printf("%d\n", mojo_strlen("hello"))

    runtime dylib: export table: 561 of 562 runtime entry points advertised
    build: universal theorem: 2 calls this walk cannot follow
      (0x1000004b8 -> 0x100000500 (opaque), 0x1000004d4 -> 0x10000050c
      (opaque)), and ONE halt address cannot discharge them. … The semantic
      model is emitted and correct for all of them; what is missing is the
      machine half.  Raised here rather than left to the walk, which reported
      this as a recursion problem.

That is NOT the `ValueError: unsupported: recursion argument bound` the bullet
quotes, and the bullet's own parenthetical already says the walk "reports this as
a recursion problem" — the walk has been fixed to refuse by name and this
document was not updated with it. The wall is now the SECOND-call case, which is
`bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md` (and it is one call,
so `printf` contributes one and `mojo_strlen` the other). So: the link line is
not what stands between a linked `mojo_*` call and a proof, and whoever takes
that next should start from that doc rather than from this bullet.

FORMAL.md phase 2 made a `mojo_*` call *decidable* — `model.gimple_runtime_callable`
answers, from the runtime header's own types, whether a formal image could make
one, and the answer had been "no, and for one reason: the library" for every one
of them since. This records what that link line now carries, and — more to the
point — what it still does not.

**Status: ceiling 2 is CLOSED — all of it, and one of its two halves was closed
by a defect in the model's TYPE READER rather than by a declaration.**
`runtime/fire_runtime.h` declares `mojo_open` and `mojo_close` (§0.2's decision,
§0.3's edit), and `formal/model.py` now resolves the headers' `typedef` aliases,
which is what made `mojo_close` word-shaped at all: `MojoFileHandle` is
`typedef void*`, and read as a bare spelling it was refused as **"a by-value
aggregate, which is a struct in memory rather than a word"** — nine times over,
about eight pointers and one `int`. **258 word-shaped entry points now, 202 of
them on a formal image's link line, 39 of those needing a handle this path
cannot produce** (251 / 195 / 32 before this section), and the file-I/O trio
`mojo_open_file` / `mojo_write` / `mojo_read` / `mojo_close` builds, links and
RUNS on both architectures. What is left is ceiling 1 (56 entry points the
library does not link) and ceiling 3 (the handle), which is FORMAL.md phase 6
and was never this document's.

Round: agent [5] of the five-agent round of 2026-09-28.

## 0. What landed, 2026-10-03 (`work/formal10-4`): ceiling 2, the header gap

Ceiling 2 was "13 names the library exports and no header declares", and the doc
below says of the `mojo_tagged_*` family that it "is not a capability limit at
all". It is now closed for the six that matter, by declarations in
`runtime/fire_coro.h` beside the coroutine ABI they belong to:

```c
enum { MOJO_TAG_INT = 0, MOJO_TAG_STR = 1, MOJO_TAG_DOUBLE = 2,
       MOJO_TAG_LIST = 3, MOJO_TAG_NONE = 4 };
int64_t  mojo_tagged_int(int64_t box, int64_t p);
int64_t  mojo_tagged_word_dyn(int64_t box, int64_t p);
int64_t  mojo_tagged_tag_dyn(int64_t box, int64_t p);
char    *mojo_tagged_str(int64_t box, int64_t p);
int64_t  mojo_tagged_list(int64_t box, int64_t p);
double   mojo_tagged_double(int64_t box, int64_t p);
int64_t  mojo_double_bits(double d);
```

Three things about it, and each is a decision rather than a transcription:

* **`runtime/fire_coro.h`, not `fire_coro_ctx.h` as this doc suggested.** These
  are the generator's box accessors, `fire_coro_gen.c` includes `fire_coro.h`
  already, and `__mojo_coro_yield_tagged` — the producer of the box they read —
  is declared there. `fire_coro_ctx.h` is the fcontext context-switch primitive,
  which is a different seam.
* **The tag VALUES moved with them.** They were `#define`s in
  `fire_coro_gen.c`, so the only place that said what `mojo_tagged_tag_dyn`'s
  answer means was a `.c` file nothing includes. They are now an enum in the
  header and the `#define`s are gone: one vocabulary, beside the accessors that
  hand one back.
* **THE TRAP IS LEFT ALONE — and was wrong to be.** `mojo_open` /
  `mojo_close` are still undeclared *in this section*, for the reason this doc
  gives: the symbol the dylib exports is the Mojo stdlib's renamed pair and
  the C file's declaration is a different function behind the same name. §0.2
  measures that reason and finds it false, and §0.3 declares them.
  `test_formal_runtime_link.py`'s
  `test_the_tagged_box_accessors_are_declared_and_callable` pins that they are
  not declared with the C signature, so "close the ceiling" cannot become
  "declare whatever the export table lists".

Measured, both architectures, by a program that CALLS the accessors:

```
printf("tag=%d word=%d int=%d", mojo_tagged_tag_dyn(0, 0),
       mojo_tagged_word_dyn(0, 0), mojo_tagged_int(0, 0))
   ->  tag=4 word=0 int=0        # 4 == MOJO_TAG_NONE
```

`box = 0` is the one argument a formal program can produce (ceiling 3 is why),
and the accessors are total on it: an empty box has no element 0, so the tag
reads out of range and the typed readers read 0. **`MOJO_TAG_NONE` is 4 and not
0**, which is what makes the number evidence — a stubbed or mis-bound call would
also answer 0.

`mojo_tagged_double` and `mojo_double_bits` are declared too and are **still
correctly refused**: they cross the boundary as a `double`, which is one machine
word but not one value on this path (`_WORD_SCALARS`). The test asserts both
halves, because a header gap and a capability limit look identical from the
outside and only one of them was closed.

## 0.1 Re-measured 2026-10-03

| | this doc | 2026-10-01 | 2026-10-02 | 2026-10-03 | now (§0.3) |
|---|---|---|---|---|---|
| word-shaped, on a formal image's link line | 156 | 240 | 246 | 251 | **258** |
| …needing no heap handle | 138 | 152 | 158 | 163 | **163** |
| …needing a `void *` handle the path cannot produce | 18 | 32 | 32 | 32 | **39** |
| word-shaped but NOT linked (ceiling 1) | 51 | 51 | 56 | 56 | **56**, unchanged |
| exported by the library, declared by no header (ceiling 2) | 13 | 13 | 13 | 6 | **4**, and nothing refuses them |

Ceiling 1's six families are unchanged and re-measured as
`ncurses 16, sqlite3 16, ssl 11, python 6, metal 5, zlib 2` on both
architectures; ceiling 2's remaining six were `MojoParser`, `scan_expr`,
`note_list_literal`, `compile_to_gimple` (not in the `mojo_*` namespace, so they
bind normally and nothing refuses them) and the `mojo_open` / `mojo_close` trap,
and §0.3 closes the trap, leaving the first four — which is what the last column
counts.

Ceiling 3 grew with the payoff, as the table above shows: 32 linked entry points
need a `void *` handle, and the only things on this path that produce one are
`void *`-RETURNING entry points, which the word rule refuses. That is FORMAL.md
phase 6 and it is unchanged by this round — and it grew again to 39 in §0.3,
because every entry point the `typedef` fix made callable takes a handle. The
dependency is the same one, and §0.3 says what that means for what this whole
document is worth.

## 0.2 The trap, decided and measured (2026-10-03, `work/formal13-6`)

§"Ceiling 2" says the trap "needs a DECISION rather than a declaration — read
the definition the linker resolves, not the one the C file spells". Both halves
of that are now done, and the first one says the doc's reason was wrong in a way
that matters:

> **`mojo_open`/`mojo_close` are declared in `fire_runtime.c` as the C library's,
> while the SYMBOL the dylib exports is the Mojo stdlib's renamed pair behind
> the same name.**

**The stdlib is not in the link.** A formal image links
`build_stdlib_dylib.runtime_dylib`, which links `runtime_units(arch, None)` —
core, coroutine, async scheduler — and `fire_python.c` is deliberately never
linked (FORMAL.md phase 0: its header was never `#include`d, so the failure
stays loud). `runtime/fire_runtime.c:26` has `#define USE_PYTHON 0`, so the
definition behind the symbol is the `#else` arm at `:452` —
`MojoFileHandle mojo_open(char *filename, char *mode)` — and
`fire_runtime.h:1616` is `typedef void* MojoFileHandle`. **Both arms of that
`#if` carry the same C signature**, which is why one declaration serves either
build, and it is also why the header's own reason for not declaring them
("to avoid conflicting types") is a *type* conflict with the STDLIB's pair and
nothing else.

The half that decides whether a declaration is a formality is the export
mechanism, and this document never said it:

    runtime_export_entries = the HEADERS' entry points
                             INTERSECTED with the symbols the objects DEFINE

(`build_stdlib_dylib.py:1357`, and its own docstring says the intersection is
the point and that both halves fail in opposite directions.) **So a name no
header declares is not exported AT ALL.** That is why today's refusal — "no
header in runtime/ declares it, so there is no signature here to check" — is a
statement about the LINK LINE and not only about a signature, and why declaring
it is not a formality: the declaration is what puts it on the line.

**And the payoff, measured through the model's own word rule** (`_runtime_abi_entry`
on the two signatures the linker resolves):

| name | signature the linker resolves | word-shaped? | so |
|---|---|---|---|
| `mojo_close` | `void mojo_close(void *fh)` | **yes** | ceiling 2 → callable. A `void *` in ARGUMENT position is admitted (`model._ctype_is_word`'s `in_return=False`) |
| `mojo_open` | `void *mojo_open(char *, char *)` | **no** | ceiling 2 → **ceiling 3**: a `void *` RETURN is the shape `void *`-returning entry points are refused for |

So ceiling 2's remaining **six becomes five**, `mojo_open` moves to ceiling 3
(so ceiling 3 becomes 33 if the edit lands), and the edit is **one line in
`runtime/fire_runtime.h`** under the `#ifndef __MOJO_STDLIB_MODE__` guard
`mojo_write` already uses for exactly this stdlib-conflict reason. The four
non-`mojo_` names in the six (`MojoParser`, `scan_expr`, `note_list_literal`,
`compile_to_gimple`) are not in the namespace, so they bind normally and nothing
refuses them; with the trap gone, ceiling 2 is those four plus nothing.

**Why it was not taken in that session, and what it turned out to need.** It was
not taken because `runtime/fire_runtime.h` is on the COMPILED path's include
list (`mojo/backend_gimple` emits `#include` of it), so a change to it owes
`make check` and a `stdlib-dylib` run. That is still true; §0.3 is the change,
and §0.4 is what it was measured against. The measurement §0.2 pinned in
`test_formal_runtime_link.py` — both that the two names are in no header, and
what each one's word verdict would be — is what made the edit safe to make
without re-deriving anything, and the two checks that asserted "not in the
header table" went red on the day it landed, which is what they were for.

## 0.3 What landed: `typedef` resolution, and then the declaration
## (`work/formal16-6`)

**The declaration alone would not have worked, and finding that out is the
reason this section is here rather than "one line, done".** `mojo_close` is
declared as `void mojo_close(MojoFileHandle fh)`, and §0.2 measured its word
verdict through the spelling `void mojo_close(void *fh)` — which is the same
type, but not the spelling the header uses. Read as the header spells it,
`MojoFileHandle` was a base type in no scalar set, so `_ctype_is_word` said no
and `_box_why` produced this sentence:

> its first argument is `MojoFileHandle fh`, which is a by-value aggregate,
> which is a struct in memory rather than a word

**That sentence is false, and it was false nine times over.** The headers alias
eight of their types, and every alias in them is a scalar or a pointer:

| alias | declared | where | what the reader saw |
|---|---|---|---|
| `MojoFileHandle` | `typedef void*` | `fire_runtime.h:1643` | an unknown base type, i.e. a box |
| `mojo_coro_handle` | `typedef void *` | `fire_async_runtime.h:42` | the same |
| `mojo_fctx_t` | `typedef void *` | `fire_coro_ctx.h:37` | the same |
| `mojo_any`, `mojo_generic_func` | `typedef void*` | `fire_runtime.h:34,47` | the same |
| `mojo_string` | `typedef char*` | `fire_runtime.h:33` | the same |
| `mojo_int` | `typedef int` | `fire_runtime.h:31` | **an `int` refused as a struct** |
| `mojo_float` | `typedef float` | `fire_runtime.h:32` | **a `float` refused as a struct** |

**An alias is a second SPELLING of a type the rule already knows, and a rule
that reads the prototype without reading the `typedef` above it is reading half
the declaration.** So the fix is in the type reader, not in a name list:

* `reflect.collect_runtime_typedefs_h` — the same scanner that already reads
  these headers for the export table, asked for `typedef` aliases instead of
  prototypes. Scalar and pointer targets only: an alias to `struct`/`union`/
  `enum` is an aggregate by another name, and an aggregate is already a box
  under every rule that reads these prototypes, so resolving it would buy
  nothing and would put a C parser in the business of understanding a struct
  body. The scanner is the right home because a name list written into
  `formal/model.py` would rot the moment a header renamed one — which is what
  `_WORD_SCALARS` is *not*.
* `formal/model.py::_runtime_typedefs` + `_parse_ctype` — the resolution, with
  **depth accumulating** rather than being replaced: `MojoFileHandle *` is
  `void **`, a pointer to a pointer, which `_ctype_is_word` refuses in every
  position because the callee dereferences twice. Reading an alias as a word
  would have turned that refusal into a miscompile.
* `runtime/fire_runtime.h` — `mojo_open` and `mojo_close` declared under the
  `#ifndef __MOJO_STDLIB_MODE__` guard `mojo_write` already uses, with the
  definitions' own signatures. §0.2's decision, applied: both arms of
  `fire_runtime.c`'s `#if USE_PYTHON` carry the same C signature, so one
  declaration serves either build, and `MojoFileHandle` is `typedef void*`, so
  the C pair and the stdlib pair agree on the type as well as on the name.

**Six entry points moved, and every one of them for the same reason** — a
`typedef` the reader could not see, so a handle that is a `void *` was a box:

| name | before | after |
|---|---|---|
| `mojo_write`, `mojo_read` | not word-shaped (`MojoFileHandle`) | **word-shaped, callable** |
| `mojo_async_schedule_ready`, `mojo_async_schedule_timer`, `mojo_async_register_read`, `mojo_async_register_write` | not word-shaped (`mojo_coro_handle`) | **word-shaped, callable** |
| `mojo_close` | no header declared it | **declared, word-shaped, callable** |
| `mojo_open` | no header declared it | declared, still refused — its `void *` **return** is ceiling 3, and the refusal now says so instead of claiming no header declares the name |

Measured, both architectures, by a program that CALLS the trio:

```
w=-1 r=-1        # mojo_write(0, "hello", 5), mojo_read(0, 0, 8), mojo_close(0)
```

`0` is the only handle a formal program can produce — `mojo_open_file` is the
one entry point that returns a handle as a word, and it opens for reading only —
and the runtime checks both arguments (`fire_runtime.c:482`). **-1 is the
evidence and 0 would not be**: a call to nowhere, or a mis-bound one, answers
0, and a refusal replaced by an image that computes 0 is the failure
`test_formal_runtime_link.py` was built to catch.

**The counters, which the test computes rather than asserts:**

| | 2026-10-03 (before) | now |
|---|---|---|
| word-shaped, on a formal image's link line | 251 | **258** |
| …of those, exported by the runtime library | 195 | **202** |
| …needing no heap handle | 163 | **163** |
| …needing a `void *` handle the path cannot produce | 32 | **39** |
| exported by the library, declared by no header (ceiling 2) | 6 | **4** |

The third row not moving is the honest half and is worth reading: **every name
this section made callable is one that needs a handle**, which is ceiling 3.
The section bought a correct type vocabulary and a closed header gap, not a
file-I/O story — `mojo_read`'s `char *buffer` is an argument the callee writes
*through*, and this path has no addressable storage to hand it.

**A judgement this widens, stated because it was already live.** A `void *` in
ARGUMENT position is admitted on a reachability argument: a formal program
cannot produce a bad handle because it cannot produce one at all. That was
already true of 32 entry points (`mojo_vararg_call_*`, `mojo_closure_free`,
`mojo_str`, `mojo_obj_getattr` — every one of which would misbehave on a
literal 0), and these 7 join that class rather than opening it. What is
different about `mojo_async_*` is that a program *can* pass 0 to them and the
scheduler will dereference it, so a formal program calling
`mojo_async_schedule_ready(0)` now builds and crashes where it used to be
refused. No test here calls one: the four async names are asserted through the
table (`entry['word']`), not by execution, and that is the reason.

## 0.4 What was run against the header edit, and what the integrator still owes

`runtime/fire_runtime.h` is on the compiled path's include list, so the edit is
the one change in this document that is not verified by `formal/` alone.
Measured here, on both architectures:

| | result |
|---|---|
| `test_formal_runtime_link.py` | 153 passed, 0 failed (was 136) — builds ~20 images across both architectures |
| `test_runtime_header_scan.py` | 37 passed, 0 failed — the declaration LEDGER moves 544 → 546, read off the call as that file's own comment requires |
| `test_runtime_dylib.py` | 116 passed, 0 failed — the export table is `561 of 562 runtime entry points advertised (0 misresolved, 1 undefined: py_tokenize)`, so both new declarations cross the headers ∩ objects intersection |
| `test_gimple_runner.py` (compiled path, compile-and-execute) | 302 passed, 0 failed, 7 timed out — the generated-module TU that emits its own `void *mojo_open(char *, char *);` beside `#include <fire_runtime.h>` compiles, and a repeated declaration with an equivalent typedef is legal C |
| `test_formal_run.py gimple_runtime_sqlite_refused gimple_runtime_print_runs` | PASS=35 FAIL=0 — the ceiling-1 refusal and the phase-2 payoff are both unmoved |

**Still owed by the integrator:** `make check` and a `stdlib-dylib` run (the
export table above is computed by the same code path, but the gate's own
self-hosting steps are not in this table).

## Re-measured 2026-10-01 (`work/formal3-7`): the payoff grew, and the
## ceilings below are still the ceilings

The link line is not a fixed thing and this doc's numbers are the ones its
author measured on 2026-09-28. What is true now, from
`test_formal_runtime_link.py` (108 passed, 0 failed, which computes these
rather than asserting them — so it cannot rot into a wrong number without
going red):

| | this doc | 2026-10-01 | 2026-10-02 |
|---|---|---|---|
| word-shaped, on a formal image's link line | 156 | **240** | **246** |
| …needing no heap handle | 138 | **152** | **158** |
| …needing a `void *` handle the path cannot produce | 18 | **32** | **32** |
| word-shaped but NOT linked (ceiling 1) | 51 | 51 | **56** |
| exported by the library, declared by no header (ceiling 2) | 13 | 13 | **13**, same names |

So the phase-2 payoff has roughly grown by half again, and ceiling 3 (the heap)
has grown WITH it rather than being closed — which is expected, since a bigger
linked surface is a bigger surface to need a handle on. `FORMAL.md` phase 6 (the
proved slab allocator) is still what closes it, and the ratio has got no better.

**Ceiling 1 grew by FIVE, and the five are a family this doc did not have:**
`mojo_metal_{dispatch_count, failure_count, have_device, init, last_error}`,
declared in `runtime/fire_metal.h`. They are word-shaped, they are not in
`runtime_units(arch, None)`, and they are not a library outside libSystem either
— the Metal runtime is a framework `libSystem` does not carry, so they join the
other five families below rather than opening a sixth kind of gap. The other 51
are unchanged, which is the useful half: nothing was closed and nothing new
opened except Metal. Measured 2026-10-02 on `work/formal8-10`, arm64 and
x86-64 identical (246 / 190 linked / 158 without a handle / 32 with one, both
architectures — `test_formal_runtime_link.py::test_link_line_is_the_dylibs_exports`,
whose own output carries the numbers, so this table is a transcription of a
report rather than a claim of its own).

The export table grew with them: `runtime dylib: export table: 557 of 558
runtime entry points advertised (0 misresolved, 1 undefined: py_tokenize)`.

**Ceiling 1 is otherwise unchanged and is still pinned by a test with a
measured note.**
`runtime_dylib` still links `runtime_units(arch, None)` — core, coroutine,
async scheduler — and not the optional units, and
`test_word_shaped_but_not_exported_links_nothing` asserts the measured fact
that `mojo_sqlite3_close` is word-shaped and NOT exported, that a program whose
only runtime call is that one links nothing, and that the refusal names the
situation rather than blaming the mechanism. What closing it costs is unchanged
too: a variant of `runtime_dylib` in `build_stdlib_dylib.py`, keyed per unit
set, with `fire_ssl.c`'s missing OpenSSL headers on a host that has none — and
`build_stdlib_dylib.py` is still not `formal/`'s to grow.

**Ceiling 2 is unchanged and `formal/`'s.** Still declarations in
`runtime/fire_coro_ctx.h` for the six `mojo_tagged_*`/`mojo_double_bits` names,
still the `mojo_open`/`mojo_close` trap (the dylib exports a DIFFERENT function
from the one `fire_runtime.c` declares), and still `runtime/`'s file.

Nothing in this doc's three ceilings was closed by anyone in the meantime, and
nothing was closed by accident either — which is the useful part of the
re-measurement: the numbers moved, the walls did not.

---

## What landed

| | where | what it is |
|---|---|---|
| the decision | `formal/build.py`, `_runtime_library_for` | a `mojo_*` word call whose name the runtime library really exports puts that library on the image's link line |
| the export table | `formal/build.py`, `macho_dylib_exports` | an independent Mach-O export-trie reader — the structure dyld itself consults |
| the manifest | `formal/build.py`, `runtime_manifest` | the same manifest a module dylib gets, so `load_dylib_manifests` reads the runtime with no special case |
| the word rule, tightened | `formal/model.py`, `_ctype_is_word` / `_box_why` | 12 entry points removed from the word set, every one measured |
| coverage | `test_formal_runtime_link.py` | 108 checks, both architectures |

**The number moved from 0 to 138.** Before: a formal image linked libSystem and
nothing else, so *no* word-shaped call was callable. After:

| | count | of the 540 entry points the headers declare |
|---|---|---|
| word-shaped, on a formal image's link line | **156** | a `mojo_*` call, all types one word, and the library exports the name |
| …of those, needing no heap handle | **138** | a formal program can actually *obtain* every argument today |
| …needing a `void *` handle the path cannot produce | 18 | see ceiling 3 |
| word-shaped but NOT linked | 51 | see ceiling 1 |
| not word-shaped, correctly refused | 321 | unchanged; the refusal still names the type |

Measured, not projected: `mojo_strlen("hello")` on both arm64 and x86-64 builds,
links and returns 5, and `mojo_print` reaches stdout. `test_formal_runtime_link.py`
runs the image and checks the exit code on both architectures, because a refusal
replaced by an image that builds and computes the wrong number is the failure
this whole programme is about and is invisible to any check that stops at the
compiler's exit code.

**The sweep coverage number does not move, and that is the finding.** Of the 593
files in the sweep's corpus, **0** would newly link the library. Five
(`test_sqlite3*.mojo`, repo root) name a `mojo_*` call and are refused under
ceiling 1. A coverage number measures constructs, not library reach, so the
phase-2 payoff is real and invisible to it.

---

## Ceiling 1 — 56 word-shaped entry points the library does not export (51 when
## this was written; the five `mojo_metal_*` names arrived after)

**Is the refusal true? Yes.** These are calls the image genuinely cannot make.

`runtime_dylib` (`build_stdlib_dylib.py:981`) links `runtime_units(arch, None)`:
the core runtime, the coroutine runtime and the async scheduler. It does **not**
link the OPTIONAL units `fire_sqlite3.c`, `fire_ssl.c`, `fire_zlib.c`,
`fire_ncurses.c`, which the gimple path compiles on demand
via `build_config.OPTIONAL_RUNTIME_UNITS`. So `mojo_strlen` is in the library
and `mojo_sqlite3_step` is not, and both are word-shaped.

| family | count | unit |
|---|---|---|
| `mojo_sqlite3_*` | 16 | `fire_sqlite3.c` (`-lsqlite3`) |
| `mojo_ncurses_*` | 16 | `fire_ncurses.c` (`-lncurses`) |
| `mojo_ssl_*` | 11 | `fire_ssl.c` (`-lssl -lcrypto`) |
| `mojo_python_*` | 6 | `fire_python.c` — **deliberately never linked** (see below) |
| `mojo_zlib_*` | 2 | `fire_zlib.c` (`-lz`) |
| `mojo_metal_*` | 5 | `fire_metal.m` — added after this doc was written (2026-10-02); a framework libSystem does not carry, so it is the same kind of gap as the other four |

**`fire_python.c` is not a gap and must not be closed.** Its whole surface is
`#if USE_PYTHON 0` stubs, the default; linking it converts a loud link error into
a silent NULL, and FORMAL.md phase 0's decision is that its header was never
`#include`d so the failure stays loud. 6 of these 56 are correct refusals and 50
are a real ceiling.

**What closing it costs.** One change in `build_stdlib_dylib.py`, which is
explicitly unowned this round: a variant of `runtime_dylib` that compiles the
optional units the caller names and passes their `-l` flags to `_dylink`, keyed
per unit set in the CAS. Half a day, and it is not purely mechanical:

- **`fire_ssl.c` does not compile on a host without OpenSSL headers.** Measured
  on this machine: `runtime/fire_ssl.c:2:10: fatal error: openssl/ssl.h: No such
  file or directory` — `test_runtime_dylib.py` already skips ssl for that
  reason. A formal build that named a `mojo_ssl_*` call would then fail with a C
  compiler error instead of a Mojo refusal, so the mechanism has to be
  "link what compiles, refuse the rest", and the refusal has to say which.
- Each unit set is a separate CAS key, so this multiplies the artifacts, and the
  `undefined=False` link plus the `__mojo_reflect` table (which forward-declares
  and takes the address of every advertised entry) has to hold for each.

**INTERFACE REQUEST filed** — see `INTERFACE-REQUESTS-agent5.md`.

## Ceiling 2 — CLOSED, all thirteen of them (§0, §0.3)

**This section is what the rest of it WAS.** The header gap is gone: the six
`mojo_tagged_*` / `mojo_double_bits` names were declared in §0, and `mojo_open`
and `mojo_close` in §0.3. What remains in the map is the four non-`mojo_` names
below, and nothing refuses them.

The export trie carries 478 C-spelled names and 465 of them are declared
somewhere in `runtime/`. Thirteen are not, and **nine** of those thirteen carry
the `mojo_` prefix, so they are refused for want of a signature while being
perfectly linkable:

    runtime/fire_coro_gen.c   mojo_tagged_int  mojo_tagged_str  mojo_tagged_list
                              mojo_tagged_double  mojo_tagged_word_dyn
                              mojo_tagged_tag_dyn  mojo_double_bits
    runtime/fire_runtime.c    mojo_open  mojo_close  MojoParser
                              scan_expr  note_list_literal  compile_to_gimple

`runtime/fire_coro_gen.c` is the one that matters, and not for the count. The
`mojo_tagged_*` family is the **tagged-value representation**, and it takes its
box as a raw `int64_t`:

    int64_t mojo_tagged_int (int64_t box, int64_t p)
    char   *mojo_tagged_str (int64_t box, int64_t p)

That is the encoding FORMAL.md §5 converges on — a container as one 64-bit word
rather than as a `MojoList *` a formal image cannot interpret — and it is
already written, already compiled into the dylib, and already exported. Measured
against the model's own word rule, **five of the nine** are word-shaped:

| would become callable | still refused, and why |
|---|---|
| `mojo_tagged_int` `mojo_tagged_word_dyn` `mojo_tagged_tag_dyn` `mojo_tagged_list` `mojo_tagged_str` | `mojo_tagged_double` (returns a `double`), `mojo_double_bits` (takes one) — the float rule below, which is correct. `mojo_open` / `mojo_close` are declared now (§0.3): `mojo_close` is callable, and `mojo_open` is refused for its `void *` RETURN, which is ceiling 3. |

The other four (`MojoParser`, `scan_expr`, `note_list_literal`,
`compile_to_gimple`) are NOT in the namespace — `is_gimple_runtime_builtin`
answers False for them — so they take the ordinary extern path and bind normally
once the library is on the line. They are listed here only because the map
carries them, not because anything refuses them.

**The trap, and the reason this is not a one-line header edit.** `mojo_open` and
`mojo_close` are declared in `fire_runtime.c` as `mojo_open(char *, char *) ->
MojoFileHandle` — and `fire_runtime.h:998` says in a comment that they are
*defined by the Mojo stdlib*, renamed from `open`/`close`; the C definitions in
that file are the fallback for non-stdlib builds. So the `mojo_open` the dylib
exports is a *different function* from the `mojo_open` `fire_runtime.c` declares.
Declaring the C one would create a signature that does not match the definition
behind the symbol, which is the exact class of mismatch
`build_stdlib_dylib.runtime_export_entries` already reports as MISRESOLVED and
that the export-csym rule was fixed for. Whoever closes this has to read the
definition the linker actually resolves, not the one the C file spells.

**What closing it cost: §0, 2026-10-03.** The six are declared, in
`runtime/fire_coro.h` rather than the `fire_coro_ctx.h` this section suggested,
with the tag values moved out of the `.c` and the `mojo_open`/`mojo_close` trap
left alone deliberately. What is left of this ceiling is the trap, which needs a
DECISION rather than a declaration — read the definition the linker resolves,
not the one the C file spells — and the four non-`mojo_` names, which nothing
refuses.

## Ceiling 3 — 39 linked entry points need a handle the path cannot produce
## (32 when the table above was written; §0.3 added the seven `void *`-handle
## entry points whose `typedef` the type reader could not see)

**Is the refusal true? Yes.** These are word-shaped, exported and linked, and a
formal program still cannot call them, because every one takes a `void *` and
the only things on this path that produce a `void *` are `void *`-RETURNING
entry points — which the word rule refuses, correctly, because the caller would
have to read what is behind the address and the declaration does not say.

18 of the 156. The loop closes only with a heap, so this is the same dependency
as FORMAL.md phase 6 (the proved slab allocator) and belongs to that phase, not
here.

**A judgement recorded and deliberately not overridden.** `void *` in ARGUMENT
position is *admitted* by the word rule, on a reachability argument rather than
a type argument: a well-typed formal program cannot produce a bad one, because it
cannot produce one at all. That is stated in `formal/model.py` and pinned by
`test_formal_runtime_link.py::test_word_rule_moved_only_where_measured`, so it
cannot be dropped silently. Tightening it would cut the linked surface from 156
to 138 at the cost of converting a program that cannot work anyway into one that
reports why. Recorded here as a live judgement, not as a settled fact.

---

## The 12 word-shaped entry points this change removed

Every one is named in `test_formal_runtime_link.py::LOST` and asserted by reason,
not by count — a count alone passes when the wrong twelve moved.

| why | count | names |
|---|---|---|
| a **floating-point** type crossing the boundary | 10 | `mojo_div_double` `mojo_div_float` `mojo_make_float` `mojo_max_double` `mojo_min_double` `mojo_python_to_double` `mojo_repr_float` `mojo_sqlite3_bind_double` `mojo_sqlite3_column_double` `mojo_sum_double` |
| a pointer the callee **dereferences** | 2 | `mojo_set_argv` (`const char **`) `mojo_regex_lastgroup` (`const char **`, `const int64_t *`) |

**The float half was a measured silent wrong answer, not a precaution.** With the
library linked and the old rule, `var x: Float64 = 2.5; return mojo_div_double(x, x)`
built, ran, and returned **2** — the integer 2.5 truncated, in X0, read by the
callee as the bit pattern of a `double` — where the answer is 1. A formal value
is a 64-bit word holding an *integer*; `float`/`double` are one machine word but
not one value on this path, and `_WORD_SCALARS` now says so.

This was latent while every `mojo_*` call was refused. Linking the library is what
made it reachable, which is why closing it is the price of admission for the
change and not a separate cleanup. 219 → 207.

---

## What this does not do

- **It is not a proof, and the reason has MOVED** (re-measured at the head of
  this file, 2026-10-04): it used to be `ValueError: unsupported: recursion
  argument bound` for ANY program containing a call, and it is now the
  second-call refusal the walk raises by name —
  "2 calls this walk cannot follow … ONE halt address cannot discharge them" —
  which is `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md`. The link
  line is not the wall. `test_formal_runtime_link.py` still runs `prove=False`
  throughout, and still says so in its own docstring rather than asserting
  nothing quietly; that remains true and its reason is now the one above.
- **The executable proof does not model the library.** `generate_arm64_proof`
  takes `(code, info)` and no dependency list, so the emitted proof is the same
  modulo the moved entry offset whether or not the library is there.
  `generate_dylib_proof` is used for module dylibs only.
- **ELF is unchanged in what it can LINK, and the reason it cannot link the
  runtime is the container.** `build_elf` takes a `deps` list and writes one
  `DT_NEEDED` per entry, so an ELF image can name a second library — measured,
  not read off a signature: `test_formal_runtime_link.py` builds an ELF image
  with two and reads both names out of its `.dynamic`. What does not exist is an
  ELF build of `runtime/`, so `runtime_library` returns `None` rather than
  handing back a manifest naming a Mach-O dylib, and the shared refusal says so
  (the Status at the head of this file is the whole account; the sentence this
  bullet used to carry — "one `lib_name` and no dependency list" — was false and
  is deleted with the fix). `formal/elf.py` grew an emitter and a `deps` list on
  another branch's work, which is what made the old sentence wrong.


## Reproducing

Everything in the 2026-10-05 Status is one pure-Python census — the export trie
and `model.runtime_abi()`, no build and no Lean — plus the one test that pins
the ELF half. Both architectures are in the same loop because the numbers are
identical and a reader should be able to see that rather than take it:

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label ceil -- python3 .tmp/ceilings.py
python3 tools/memslot.py --gb 8 --label t -- \
    python3 test_formal_runtime_link.py            # 159 passed, 4 failed
python3 tools/memslot.py --gb 8 --label t -- \
    python3 -c "import test_formal_runtime_link as T; \
        T.test_elf_is_refused_for_the_container_and_not_for_the_link_line()"
```

`test_formal_runtime_link.py`'s **4 failures are pre-existing and are not this
document's**: they compare the live count against `FORMAL.md` §6 phase 2's
published `206`/`166`, which the tree has outgrown (`1dd68a48` published them on
2026-10-04; `runtime/` and `build_stdlib_dylib.py` have changed since, and this
branch touches neither). `test_formal_doc_truth.py` is red on the same drift
(8 checks, 7 of them the same figures). `.tmp/ceilings.py` is scratch and is not
committed — `.tmp/` is git-ignored — and the loop is five lines: `word` from
`model.runtime_abi()`, `exported` from `runtime_library(arch, "macho")["map"]`,
`ceiling 1` as the difference, `ceiling 2` as
`macho_dylib_exports(runtime_dylib(arch=arch))` minus the ABI table, and the
`void *` parameter test `test_formal_runtime_link.py` already owns.
