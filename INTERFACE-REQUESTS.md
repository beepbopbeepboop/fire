# INTERFACE REQUESTS — FORMAL-PARALLEL round 1

**One file, all five agents, one section each.** `FORMAL-PARALLEL.md` §4
specifies the request format; this is where they are filed so the integrator
can apply them in merge order. Each request is **self-contained and
verified**: where a diff is given it has been applied to a scratch copy of the
target file and measured, so applying it is mechanical, not a design task.

A request that is only a paragraph is a request the integrator has to
re-derive. A request with a measured diff is a merge.

**Read this before applying anything here.** Requests A and B below are in
`reflect.py`, which is agent **[3]**'s exclusive write set. They are filed
*to* [3] and must not be applied until [3] has landed, or landed with them.
Everything else is independent.

---

## [2] → [3] — `reflect.py`: the runtime export table names 30 of 459 entry points

> **STATUS: APPLIED.** Both changes below are in the working tree
> (`git diff reflect.py` shows them verbatim), applied by [3] while this
> request was open. **Do not apply the diff again.** The one consequential
> follow-up — `test_runtime_header_scan.py`'s pinned count 452 → 447 — is done
> too, so the tree is consistent. Everything below is kept as the record of
> *why*, and because [4] and [5] are building on the export table this
> unlocked and should know what it now contains.

```
INTERFACE REQUEST  from=[2]  to=[3]  file=reflect.py
WHAT:   two changes, both verified, diff below and at the end of this section
WHY:    `export_csym` computes a Mojo OVERLOAD-MANGLED symbol for a C
        PROTOTYPE, so `build_stdlib_dylib.build()`'s `nm` cross-check rejects
        429 of `fire_runtime.h`'s 452 entry points as "stale" — a real
        definition the dylib has and does not advertise. The exported-symbol
        table is the input [3]'s word-shaped callable surface is derived from
        and the input [4]'s bind audit is supposed to be built on, so both are
        reading a table that is 94% missing.
BLOCKS: [3] item 1's "generated from the header by
        `reflect.collect_runtime_exports_h`" and [4] item 1's "replace the 19
        names with the linked library's real export table". Neither can be
        tested against a table that names 30 of 459 symbols.
```

**What the fix bought, measured on the `build()` path with the fix in place:**

```
export table: 458 of 459 runtime entry points advertised (0 misresolved, 1 undefined)
  declared with no definition in this dylib: py_tokenize
```

`py_tokenize` is the correct residual: it is defined by the self-hosted
compiler's own transpiled `fire_compiler.py`, not by the runtime, so the
runtime dylib must not advertise it. **[4]: this is now the real export table
your bind audit should be built on** — 458 symbols read off the header and
confirmed against `nm`, per architecture, from
`build_stdlib_dylib.runtime_export_entries(arch)`.

### A. `export_csym` overload-mangles a C prototype

`export_csym`'s `SYM_FUNCTION` branch is for a **Mojo function
declaration**: it computes `<module>_<name><overload-suffix>`, which is right
for `math.abs` and wrong for `MojoStr *mojo_str_new(char *)`, whose C symbol
is simply `_mojo_str_new`. `collect_runtime_exports_h` builds its entries with
`kind: SYM_FUNCTION` and no `module_prefix`, so they land in that branch and
come out as `mojo_str_new_0c2293` — a symbol nothing defines.

Measured, before:

```
$ python3 -c "...collect_runtime_exports_h('runtime/fire_runtime.h') + nm fire_runtime.o..."
header exports: 452
surviving build()'s nm cross-check: 26          # all of them coincidental
misresolved (defined, but export_csym named something else): 429
```

Measured, with the diff applied:

```
export table: 458 of 459 runtime entry points advertised (0 misresolved, 1 undefined)
  declared with no definition in this dylib: py_tokenize
```

458 is the count across all three runtime headers the dylib's objects provide
(`fire_runtime.h`, `fire_async_runtime.h`, `fire_coro_ctx.h`) — the coro/async
entry points are only in the total because the fix makes the two classes agree.
The one remaining is genuine: `py_tokenize` is defined by the self-hosted
compiler's own transpiled `fire_compiler.py`, not by the runtime, so the
runtime dylib must not advertise it. That is what the `nm` cross-check in
`build_stdlib_dylib.runtime_export_entries` is for, and it is now doing its
job instead of hiding behind the mangling.

**This needs no change in `build_stdlib_dylib.py`.** Its cross-check already
asks `export_csym` what the symbol is and keeps the entry when `nm` agrees, so
a correct resolution is advertised automatically. The build also now *reports*
the shortfall by class, so if a resolution ever goes wrong again it says which
of the two ways it went wrong rather than printing a wall of "drop stale
export".

### B. the scanner reads `return f(x);` as a declaration

`_PROTO_RE`'s return-type group is non-greedy, so it matches a **statement
inside a `static inline` body**: at `fire_runtime.h:144` the line
`return mojo_fnptr_call_0(f);` parses as ret=`return`, name=`mojo_fnptr_call_0`,
and the scanner reports five prototypes that do not exist. They are then
correctly dropped as undefined, so the cost is a wrong diagnosis — and
`formal/build.py`'s bind audit, which is built on this scanner, would be told
the runtime declares `mojo_fnptr_call_0`.

**One trap in this diff, already hit and fixed — do not re-introduce it.** The
statement keywords must be matched as whole **tokens**. A substring test for
`do` matches `double`, and a first attempt at this change silently lost **11
real declarations** (`double mojo_max_double(void *args)` and friends) while
looking like it worked. The diff below strips `*` and splits; it is verified to
leave every other header's count untouched:

```
fire_runtime.h 447 (was 452: −5 phantums)   fire_ssl.h      13  unchanged
fire_sqlite3.h 22  unchanged                fire_ncurses.h  18  unchanged
fire_zlib.h      6  unchanged               fire_python.h   15  unchanged
```

### The diff (verified; `patch -p1` from the repo root)

```diff
--- a/reflect.py
+++ b/reflect.py
@@ -506,7 +506,17 @@ def export_csym(e: dict) -> str:
     already carry their mangled name inside the signature. Shared by
     emit_table_c (to forward-declare/address it) and build_stdlib_dylib.py
     (to verify, via `nm`, that the compiled object actually defines it before
-    trusting the export — see that module's `build()`)."""
+    trusting the export — see that module's `build()`).
+
+    An entry that carries its OWN `csym` is taken at its word, before any of
+    that. A C prototype is not a Mojo function declaration: it has no home
+    module to qualify and no overload suffix, because the C compiler already
+    gave it its name. `collect_runtime_exports_h` produces those entries and
+    is the one that knows this, so it states it there rather than leaving it
+    to be inferred here from the ABSENCE of a `module_prefix` — which is also
+    what a hand-built `extra_exports` entry looks like."""
+    if e.get('csym'):
+        return e['csym']
     if e['kind'] == SYM_FUNCTION:
         return _func_export_csym(e['name'], e['signature'], e.get('module_prefix', ''))
     return e['signature'].split('(', 1)[0].strip().split()[-1].lstrip('*')
@@ -597,11 +607,33 @@ def collect_runtime_exports_h(header_path: str) -> lis
         content = f.read()
     for m in _PROTO_RE.finditer(content):
         ret, name, params = m.group(1).strip(), m.group(2), m.group(3).strip()
-        if any(kw in ret for kw in ('typedef', 'struct', 'static', '#', 'extern')):
+        # `ret` is a non-greedy `[\w\s\*]*?`, so it happily begins at a
+        # STATEMENT KEYWORD: inside a `static inline` body the line
+        # `return mojo_fnptr_call_0(f);` matches the whole pattern with ret ==
+        # "return", and the scanner then reports a prototype that does not
+        # exist. These are the C keywords that are followed by an EXPRESSION,
+        # so they are the ones that can do this.
+        #
+        # Matched as whole TOKENS, not as substrings. Substring matching is
+        # how a first attempt at this lost 11 real declarations: "do" is a
+        # substring of "double", so `double mojo_max_double(void *args)` was
+        # rejected as a statement. `*` is stripped first because the group
+        # admits it, and `#` stays a substring test because a preprocessor
+        # line is not a type expression at all.
+        _ret_tokens = ret.replace('*', ' ').split()
+        if any(tok in ('typedef', 'struct', 'static', 'extern', 'return',
+                       'sizeof', 'case', 'do', 'else', 'goto', 'if', 'while',
+                       'switch') for tok in _ret_tokens) or '#' in ret:
             continue
         if name.startswith('_') or name in seen or name in _CLIB_SYMS:
             continue
         seen.add(name)
         sig = f"{ret} {name} ({params or 'void'})"
-        exports.append({'name': name, 'signature': sig, 'kind': SYM_FUNCTION})
+        # `csym`: this is a C prototype, so the C symbol IS `name` — no module
+        # qualifier, no overload suffix. Both are Mojo codegen concepts and
+        # applying them to a C declaration computes a symbol that does not
+        # exist, which is how 429 of fire_runtime.h's entry points went
+        # unadvertised (see INTERFACE-REQUESTS.md, request [2] -> [3] A).
+        exports.append({'name': name, 'signature': sig, 'kind': SYM_FUNCTION,
+                        'csym': name})
     return exports
```

**One consequential follow-up, and it landed in the same commit.** B removes
five entries, so `test_runtime_header_scan.py`'s pinned count for
`fire_runtime.h` changes 452 → **447**. That file is outside both write sets;
[2] took 459 → 452 for the header change and 452 → 447 for this one (see
below), so the two steps are separately attributable and both are done.

### Also in `reflect.py`, for [3] to apply or decline — `_CLIB_SYMS` for a DEFINITION

My own item (2) was to "decide it, or write down precisely why not". I have
decided, and the decision is **keep the exclusion unchanged**, because the
argument for changing it is false on this tree. The measurement, and the
correction it forces to `bugs/FORMAL_known_limits.md` §1.1, are in that
document under "§1.1, corrected". In short:

* `std/sys/terminate.mojo` does **not** define `exit`. It compiles to **no C at
  all** — the generated translation unit contains neither `def exit()` nor
  `def exit[intable]`, and `nm` reports only `__std_sys_terminate_toplevel` and
  `_std_sys_terminate_init`. §1.1 currently states as fact that it defines one.
* Where a module *does* define a `_CLIB_SYMS` name, the codegen already
  renames it, so no libc name is ever emitted bare and libc cannot be
  shadowed: `std/sys/_libc.mojo`'s `def exit(...)` becomes
  `_std_sys__libc_mojo_exit_9f63a2` and `std/io/file.mojo`'s `def open(...)`
  becomes `_std_io_file__open_file_1b532c`. The mechanism is
  `mojo/middle/types.py:799` (`_c_names`: a C keyword **or** a
  `_C_RESERVED_FUNCS` name becomes `mojo_<name>`), i.e. `doc/ABI.md`'s "C-keyword
  names get the documented `mojo_` prefix" extended to reserved libc names.
* 18 raw exports across 8 stdlib modules carry a `_CLIB_SYMS` name. Under
  `_c_names` not one of them reaches a dylib as a bare symbol.

So there is no shadowing to prevent. What the exclusion is actually doing is
keeping the reflection table's `name` and `addr` columns from disagreeing: an
entry named `open` whose address is `_std_io_file__open_file_1b532c` would be
worse than no entry. **No change to `_CLIB_SYMS` is requested.** If [3] reads
the evidence and disagrees, that is a legitimate outcome and the argument to
have — the measurement is above and in the bug doc, not in my head.

---

## [2] → integrator — `runtime/fire_runtime.h`, `runtime/fire_runtime.c`

```
INTERFACE REQUEST  from=[2]  to=integrator  file=runtime/fire_runtime.h
                         (and runtime/fire_runtime.c)
WHAT:   ALREADY APPLIED by [2], not as a request — flagged here because both
        files are in NO agent's write set and [2] took them under
        FORMAL-PARALLEL §1's "it belongs to whoever owns the nearest file"
        rule (build_stdlib_dylib.py owns `RUNTIME` and the export table
        derived from that header). Veto or reassign if that reading is wrong.
WHY:    eight declarations removed, seven of them dead and one of those
        (`int mojo_type(...)`) the single line that made clang unable to
        compile the runtime AT ALL, which is what blocked the x86-64 runtime
        dylib this round exists to produce.
BLOCKS: nothing. Already landed and measured.
```

**Removed from `fire_runtime.h`** — all eight measured as *declared, defined
nowhere, and called by nothing*:

| name | why it is dead |
|---|---|
| `int mojo_type(...)` | a stub whose body is `return 0`, with zero callers. Also invalid ISO C: `(...)` with no named parameter is a hard error in clang, not a warning, so it made the whole of `fire_runtime.c` uncompilable by clang for either architecture. |
| `int mojo_obj_enter(int)` / `int mojo_obj_exit(int,int,int,int)` | `with` lowers to the DEFINING struct's own qualified method symbol, never to a bare dispatch helper. Measured in generated C: `std_runtime_tracing_Trace___enter__`, per `doc/ABI.md`'s module-qualified rule. |
| `int int___enter__(int)` / `int int___exit__(int,int,int,int)` | same measurement, same conclusion — the unqualified spelling has not been emitted since ABI v2. |
| `int tuple(int *args)` | appears in generated C only inside string literals. |
| `int64_t MojoList__write_to(MojoList *, ...)` | a Mojo method name in a C header; no such C symbol exists and none is called. |

**Kept, and the header now says why**, because the generalisation "a
declaration with no definition is a link failure" is wrong for exactly one
group and the distinction is load-bearing: `py_tokenize` (and `setattr`, and
the `int64_t_*` path shims) are declared for GENERATED code to call and are
defined by whoever links the image — for `py_tokenize` that is the
self-hosted compiler's own transpiled `fire_compiler.py` (it is in
`reflect._NO_MANGLE_FUNCS` and in `GimpleGen._KNOWN_SIGS` for exactly that
reason). The section header now says the definition is the linker's business,
so the next reader does not "fix" them by inventing a stub that returns 0.

**Consequence the integrator must know about:** both files are in
`cas._RUNTIME_SOURCES`, so this changes `compiler_fingerprint()` and
invalidates every cached module object and dylib. That is correct (an unused
prototype is not a behavioural change, but a *link-relevant* one), and the
cost is one cold rebuild. It is also why the change is behaviour-preserving
and was checked as such — `test_runtime_dylib.py` asserts the generated C for
a real program is byte-identical before and after, and the seven removals
touch no name any generated C references.

**Also applied outside my write set, same flag:** `test_runtime_header_scan.py`'s
pinned `fire_runtime.h` count 459 → 452, forced by the removals above. That
test's own docstring says a count assertion "has to be rewritten every time
the runtime grows a function"; it also has to be rewritten when the runtime
loses one, and the header comment now says so. The 452 → 447 step belongs to
the `reflect.py` diff above.

---

## [2] — reconciliation: [1] × [2] × [3] in one tree, verified working

[2] committed first, so [2] checked that the three sets of changes actually
work **together** rather than each passing alone. They do. Recorded here
because two of the three facts below are not visible from any one agent's diff.

**It works, end to end.** With [1]'s optional-unit registry, [2]'s per-arch
runtime dylib and [3]'s scanner fix all in the tree:

```
$ python3 fire.py build -o /tmp/sq test_sqlite3.mojo && /tmp/sq
rows: 1 hello 2 world                          # the round's only user-visible
                                                # broken thing, now fixed
$ python3 fire.py build -o /tmp/nosql <a program that never mentions sqlite>
$ otool -L /tmp/nosql | grep -iE 'sqlite|libz|libssl|crypto'
   (nothing)                                    # and the negative half holds:
                                                # it does not link libsqlite3
$ otool -L /tmp/sq | grep -i sqlite
  /usr/lib/libsqlite3.dylib                     # while the sqlite one does
```

**Merge order matters, in one place only.** `reflect.py`'s two changes
(request `[2] → [3]`, above) are **uncommitted**. `bdd76b0` alone still
advertises 30 of 459 runtime entry points; the 458 is the working tree. Land
`reflect.py` and the claim holds; do not and it does not.

**[1] and [3] are coupled through one function, and now that is pinned.**
`build_config.optional_unit_symbols` derives each unit's `mojo_<unit>_`
namespace as the longest common prefix of what `reflect.collect_runtime_exports_h`
reports for that unit's header. So a change to the scanner is a change to which
libraries a program links, with **no file in common** between the two agents.
The specific hazard: a scanner reporting a name that is not a real C symbol
feeds an invented string into a prefix computation, and the resulting
namespace is a prefix of nothing — the program that genuinely calls the unit
stops matching it and fails to link, or a near-miss matches the wrong unit and
the program silently links a library it never asked for. That scanner *did*
have that bug (it read `return f(x);` inside a `static inline` as a
declaration); it is fixed, and `test_runtime_dylib.py` §7 now fails if the
two halves ever disagree again — namespaces that do not cover exactly their
own symbols, namespaces that overlap each other, a runtime symbol falling
inside a unit's namespace, or a header promising a symbol its unit does not
define. Measured, all clean: 22/6/13/18 symbols, four disjoint namespaces, no
overlap with any of the runtime's.

### One defect in the combination, in [1]'s file, for [1] to take

`driver.compile_program` and `fire.py`'s `build_executable` handle a
**failing optional-unit compile** differently, and the worse one is on the
path FORMAL-PARALLEL says `fire.py build` normally takes:

```
fire.py build  ->  optional runtime compile failed (ssl, .../fire_ssl.c):
                   fire_ssl.c:2:10: fatal error: openssl/ssl.h: No such file
                   (names the unit, the source, and the compiler's own error)

driver.compile_program  ->  CalledProcessError: Command '['/opt/local/bin/
                   gcc-mp-15', '-fPIC', '-I.../runtime', '-O0', '-g3', '-c',
                   '-o', '/var/folders/.../mojo_optrt_owzc_1o0...
```

`driver.py`'s `_mk_opt` uses `subprocess.run(..., check=True)`; `fire.py`'s
equivalent checks `returncode` and prints the diagnostic. The fix is to copy
[1]'s own `fire.py` handling — the good version is already written, three
files away. Not loud-vs-silent (an exception is loud, exit non-zero), but a
traceback where the project has a habit of naming the thing that went wrong.

**This is reachable on this machine**, which makes it worth fixing rather than
filing: `fire_ssl.c` does `#include <openssl/ssl.h>` and OpenSSL is **not
installed here**, so the unit yields no object at all. Any program referencing
`mojo_ssl_*` cannot build until it is. Two consequences worth knowing:

* `test_runtime_dylib.py` reports `skip ssl: … 13 declared symbols are
  unchecked` with the compiler's reason, rather than passing quietly — 0 of 13
  checked is a materially weaker claim than 13 of 13 and must not read the
  same.
* Whether `fire_ssl.c` belongs in the registry **on a machine with no OpenSSL**
  is a registry question, not a code one, and the answer is arguable either
  way: the header is `#include`d unconditionally so a program calling
  `mojo_ssl_new` must get *something*, and a loud "this build needs OpenSSL"
  beats a bare `Undefined symbols` on the same line. Left to [1].

## Notes for the integrator, not requests

* **`build_stdlib_dylib.py` and `cas.py` changed shape, and the CAS domains
  moved.** `cas.dylib_link_key` is `mojo-dylib-link-v1` → `-v2` and the runtime
  dylib key is `mojo-rtdylib-v3` → `-v4`, both because the target architecture
  became a key input. Old entries are unreachable rather than wrong, which is
  the intended outcome, but it does mean the first `stdlib-dylib` after the
  merge is a cold build.
* **A new, smaller class of orphan is now visible, and it is not mine.**
  `python3 fire.py build <anything>` prints, from the by-class report added
  here:

  ```
  export table: 1957 of 1961 runtime entry points advertised (0 misresolved, 4 undefined)
    declared with no definition in this dylib: ord, ascii, atol, py_tokenize
  ```

  `py_tokenize` is expected (see above). The other three are **module**
  exports, not runtime ones: `std/collections/string/string.mojo` declares
  `ord`, `ascii` and `atol`, and no object in that build defines the symbol its
  export entry names. Before this change these were three lines of
  `drop stale export 'ord': …` indistinguishable from the 429 that were a real
  defect in a shared function; they are now named in their own right, which is
  how a thing like that becomes fixable. Not investigated — it is a
  `gimple_codegen`/stdlib question, outside every write set in this round.
* **`build_stdlib_dylib.build()`'s output path now depends on the arch.**
  `build_stdlib()` defaults to `build/libmojostdlib.<arch>.dylib` rather than
  `build/libmojostdlib.dylib`. Nothing calls it with a hard-coded path —
  `tools/suite.py`'s `stdlib-dylib` step is `b.build_stdlib()` with no
  arguments and uses the return value — so it works as written, but the
  comment above that step still names the old path and is now stale. That file
  is integrator-owned; this is a one-word comment fix, not a behaviour change.
* **The `-arch` flag cannot be trusted, and this bit [2] during the work.** The
  configured compiler is `/opt/local/bin/gcc-mp-15`, which ACCEPTS `-arch
  x86_64`, prints `warning: this compiler does not support x86 ('-arch' option
  ignored)`, and emits an **arm64** object at exit 0. It also has no `-m32` and
  no `--target`, so it cannot build for the other architecture at all. Every
  arch-carrying artifact is therefore verified by reading the Mach-O that came
  out (`build_stdlib_dylib.arches_of` / `_arch_or_die`) rather than by trusting
  the flag. This caught a live bug during the work: with `-arch` missing from
  the **link** step, `ld` took the host architecture, warned
  `ignoring file ...: found architecture 'x86_64', required architecture
  'arm64'` for every object, exited 0, and wrote an empty arm64 dylib.
