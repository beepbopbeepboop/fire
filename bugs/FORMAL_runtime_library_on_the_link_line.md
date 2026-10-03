# FORMAL_runtime_library_on_the_link_line: the phase-2 payoff is landed; three measured ceilings are open

FORMAL.md phase 2 made a `mojo_*` call *decidable* — `model.gimple_runtime_callable`
answers, from the runtime header's own types, whether a formal image could make
one, and the answer had been "no, and for one reason: the library" for every one
of them since. This records what that link line now carries, and — more to the
point — what it still does not.

**Status: the link line is done and measured; 56 of the word-shaped entry points
are still refused because the library does not define them (51 when this was
written; `mojo_metal_*` arrived after), 13 defined names are still refused
because no header declares them, and 32 of the linked ones need a heap handle
this path cannot produce. All three are written down below with the exact list
and the cost of closing each, and all three were re-measured on 2026-10-02
rather than carried forward.**

Round: agent [5] of the five-agent round of 2026-09-28.

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

## Ceiling 2 — 13 names the library exports and no header declares

**Is the refusal true? Yes, and the message says so** ("no header in runtime/
declares it, so there is no signature here to check"). It is a header gap, and
unlike ceiling 1 this one is not a capability limit at all.

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
| `mojo_tagged_int` `mojo_tagged_word_dyn` `mojo_tagged_tag_dyn` `mojo_tagged_list` `mojo_tagged_str` | `mojo_tagged_double` (returns a `double`), `mojo_double_bits` (takes one) — the float rule below, which is correct. `mojo_open` / `mojo_close` return and take `MojoFileHandle`, a typedef this rule reads as a box; see the trap. |

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

**What closing it costs.** Declarations in `runtime/fire_coro_ctx.h` for the six,
which is `runtime/`'s and unowned this round. Half a day for the five that are
genuinely word-shaped, and the `mojo_open`/`mojo_close` case needs a decision
rather than a declaration.

## Ceiling 3 — 18 linked entry points need a handle the path cannot produce

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

- **It is not a proof.** `formal/arm64_proof_gen.py` still raises `ValueError:
  unsupported: recursion argument bound` for ANY program containing a call
  (FORMAL.md §11.1, agent [2]'s scope), so `fire.py build --formal` on a
  `mojo_*` call reaches the binary and stops at the proof step.
  `test_formal_runtime_link.py` therefore runs `prove=False` throughout, and says
  so in its own docstring rather than asserting nothing quietly. When [2] lands,
  a linked `mojo_*` call will generate the same `extern_<sym>_step : True := by
  trivial` as any other extern — which is phase 3's job, not this one's.
- **The executable proof does not model the library.** `generate_arm64_proof`
  takes `(code, info)` and no dependency list, so the emitted proof is the same
  modulo the moved entry offset whether or not the library is there.
  `generate_dylib_proof` is used for module dylibs only.
- **ELF is unchanged.** `build_elf` carries one `lib_name` and no dependency
  list, so an ELF image cannot name a second library; `runtime_library` returns
  `None` rather than pretending, and the shared refusal says the link line is
  what is missing. `formal/elf.py` is not this file's to grow.
