# COMPILE_FAIL: Lib/zipfile/__init__.py

## Status (2026-10-01 — the `'open'` ambiguity blocker is FIXED, and this file's own errors are down to 21; three of the six classes below are closed)

The single named blocker every entry below tracks is gone, and one of the
two error classes its own Status newly recorded is closed too. Measured
on this tree (`python3 tools/memslot.py --gb 8 --label zipfix2 -- python3
fire.py build -o .tmp/out/zipfile2
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py`): **exit 1, 186
`error:` lines, 21 of them in `zipfile/__init__.py`**, down from 191/24
immediately after the ambiguity fix.

**Fixed: the `mojo_max`/`mojo_min` arity class (3 of those 24).**
`n = max(n, self.MIN_READ_SIZE)` at line 1180 (and `min(n,
self._compress_left)` at 1202-1203) is a 2-arg `max`/`min` — a SCALAR
comparison — but `_ITERABLE_CONSUMING_BUILTINS` in
`mojo/middle/infra_infer.py` lists `max`/`min` because their
*one*-argument form reduces an iterable. So `_infer_param_types` marked
the unannotated `n` `is_iterated`, typed it `MojoList *`, and the call
lowered to the runtime's single-iterable `int64_t mojo_max(void *args)`:
"too many arguments to function 'mojo_max'; expected 1, have 2". Fixed by
gating that signal on arity for `max`/`min`/`divmod`/`round`, with
`test_gimple.py::test_scalar_arity_min_max_params_are_not_containers`
covering all three arities on both pipelines. `grep mojo_max .tmp/zipfix2.log`
is now **0**.

**Root cause of the original blocker** (which was filed as
`bugs/COMPILE_FAIL_open_is_ambiguous_from_transitive_registrations.md`,
now fixed and removed): `gen_module_impl`'s transitive-discovery loop
registered every inlined sibling's top-level FunctionDef names into
`_own_imported_func_home` as well as `_imported_func_home`. Tier 2 is
documented as "THIS exact gen_module call's own FromImportStmt scan …
never shared across temp_gens", and a sibling's *definition* is neither.
The collision rule on top turned two such registrations into
`_AMBIGUOUS_FUNC_HOME`, which `_func_qualifier` refuses for EVERY
reference to the name program-wide — so six unrelated siblings each
defining `open` made every bare `open(...)` in the closure uncompilable,
including zipfile's, which are the builtin. Fixed by dropping the
duplicated tier-2 registration (the `_imported_func_home.setdefault`
directly above it already records the same fact, in the tier that is
*documented* for whole-program observations). Regression:
`test_link_mode.py::test_builtin_open_is_not_ambiguous_from_transitive_siblings`
— its siblings' `open` bodies print, so the test asserts by their absence
that the builtin ran.

**A separate bare-`import` defect found while measuring this, filed not
fixed:** a bare `import X` + `<X>.<free_fn>(...)` module-qualified call
answers 0 on the link/build path where the same source is correct on the
single-TU inline path and where `from X import fn` is correct everywhere.
See `bugs/CODEGEN_bare_import_module_qualified_call_answers_zero.md`. It
is the shape behind four of `Lib/ctypes/util.py`'s errors, not this
file's.

**This file's own 21 remaining errors** (it contributed ZERO before the
ambiguity fix, because the refusal fired first — so every claim in the
entries below that its compile unit was clean was true only of a build
that never got to check it):

- **9 × cross-module struct-method / free-function symbols not declared in
  this TU** — `ArgumentParser___init__`, `_add_argument`, `_parse_args`.
  These are a DOWNSTREAM CONSEQUENCE, not a shape of their own, and the fix
  is not in zipfile: `argparse` itself refuses to compile in this closure
  (`cannot coerce MojoList * to MojoDict * (incompatible container kinds)
  … value='_t229' dest='args'`), so its symbols are never defined and every
  reference to them becomes an implicit declaration. The two errors at
  `zipfile/__init__.py:2383-2397` disappear the moment `argparse`
  compiles; a minimal two-file probe confirms the module-qualified struct
  path itself is sound (a bare `import lib` + `lib.Thing(1).go(2)`
  compiles, links and prints the right answer, at both module and
  function-body import scope).
- **12 × a `zipfile/_path`-internal genexp/annotation shape** at
  `__init__.py:741` and `:752` (`non-trivial conversion in 'component_ref'` /
  `'var_decl'`, and the `int64_t *` ↔ `int64_t` round-trip that follows):
  `zipfile._path`'s own `CompleteDirs`/`iterdir` declarations emit invalid
  C, and zipfile's use of them inherits it. This is the largest remaining
  class and the most specific to this file.

Downstream, `pathlib/__init__.py` is the largest single contributor (37
× `expected expression before '(' token` — a `match`/`case` or slice shape
zipfile's closure reaches that the interpreter suites do not), then
`compression/zstd/_zstdfile.py` (23 × pointer↔scalar `char *`/`int64_t`
coercions) and `shutil.py`. Each is a separate doc's subject; none is
specific to zipfile's codegen.

Doc kept open on two named classes, both with a filed root cause.

## Status (2026-09-30 — supersedes nothing; kept for the `open` ambiguity's history)

Re-ran everything on that branch rather than trusting the entries below.

**`Lib/zipfile/__init__.py` itself contributes ZERO `error:` lines.** Not
"no errors reached" — its compile unit is inline-compiled into the
whole-program unit and gcc accepts it. The file is still not BUILT,
because the program it belongs to is refused as a unit:

```
Error building: cannot compile module: 'open' is ambiguous — this program
transitively imports two different sibling modules that both define a free
function named 'open', ... and no enclosing `from X import ...` statement
in the current lexical scope binds the name for this specific reference.
```

Root-caused with an instrumented `_note_own_func_home` trace, and filed as
`bugs/COMPILE_FAIL_open_is_ambiguous_from_transitive_registrations.md`
with the tier fix it needs. NOT attempted there: it is a change to
`_func_qualifier`'s tier order, which
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
owns and which several recent entries here flag as easy to regress into a
SILENT wrong call.

## Status (2026-09-30, branch work/compile-fail-stdlib-misc — this file's OWN compile unit is now CLEAN; the whole-program build is refused by one honest, precisely-root-caused ambiguity message)

Re-ran everything on this branch rather than trusting the entries below.

**`Lib/zipfile/__init__.py` itself contributes ZERO `error:` lines.** Not
"no errors reached" — its compile unit is inline-compiled into the
whole-program unit and gcc accepts it. The file is still not BUILT,
because the program it belongs to is refused as a unit:

```
Error building: cannot compile module: 'open' is ambiguous — this program
transitively imports two different sibling modules that both define a free
function named 'open', ... and no enclosing `from X import ...` statement
in the current lexical scope binds the name for this specific reference.
```

`zipfile/__init__.py` never imports `open`; its bare `open(...)` uses
(line 266) are the BUILTIN. The ambiguity is manufactured by six
unrelated siblings' transitive import registrations (`codecs`, `tokenize`,
`bz2`, `lzma`, `compression.zstd._zstdfile`, …), all with
`record_scope=False`, colliding on one shared `_own_imported_func_home`
key. Root-caused with an instrumented `_note_own_func_home` trace, and
filed as `bugs/COMPILE_FAIL_open_is_ambiguous_from_transitive_registrations.md`
with the tier fix it needs. NOT attempted here: it is a change to
`_func_qualifier`'s tier order, which
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
owns and which several recent entries here flag as easy to regress into a
SILENT wrong call.

Also landed this session and relevant to this file:
`b501954c` removed a crash that refused this file outright — see
`bugs/COMPILE_FAIL_importlib_resources_readers.md`'s entry for the shape.
`fire.py build` on `Lib/zipfile/__init__.py` now gets all the way to that
one refusal instead of dying in an `AttributeError`.

Doc kept open. The remaining work is the `'open'` ambiguity, which is now
a single, named, understood blocker rather than a wall of errors.

## Status (2026-09-07, end-to-end runtime investigated — blocked on `.py` link-mode module resolution + memoryview-in-generator, both architectural)

The task was "make a real zip round-trip (`from zipfile import ZipFile`,
`writestr`/`close`/`namelist`/`read`) actually work through `fire.py
build`". It does NOT, and the reasons are now precisely characterised —
this is a multi-feature stack, not a bug:

1. **`fire.py build` "succeeds" but silently stubs the whole module.**
   `from zipfile import ZipFile` never resolves in link/build mode.
   `imports.resolve_source()` / `imports.Resolver._find()` only probe
   `<dir>/<name>.mojo` and `<dir>/<name>/__init__.mojo` — never `.py` —
   and `_parsed_import()`'s candidate-path fallback only fires for
   leading-dot relative names. So `ZipFile(...)` lowers to an opaque
   `(int64_t)0`, every method call becomes a `int64_t.<m>() stubbed`
   no-op, and the driver prints `Built:` **even though the final link
   emitted "Undefined symbols" / the program segfaults or prints
   garbage** (`names: 8100139744743485279`). The `fire.py run`
   (interpreter) path "works" only because it delegates the import to
   host CPython's real `zipfile` — no compilation involved.

   Attempted fix (reverted — regresses `make check-selfhost`):
   - `imports.Resolver._find`: add `.py` / package `__init__.py`
     candidates (after the `.mojo` forms). Self-hosting `imports.py`
     then fails with `imports.py:85:1: error: invalid conversion in
     gimple call` — extending the 2-tuple `for cand in (...)` to a
     4-tuple trips self-host's tuple lowering.
   - `_register_link_imports`: the raw-source struct-detection regexes
     match only Mojo `struct <name>`, never Python `class <name>` — so
     even a *resolvable* `.py` class never reaches the
     `_link_inline_modules` inline-compile fallback. Adding a
     `\bclass\s+{name}\s*[(:]` branch is gate-clean on its own but
     inert without the resolution fix above, and a minimal repro
     (sibling `mylib.py` with `class Widget` + list-returning method,
     imported by an `app.mojo` built in link mode) **segfaults both
     before and after** — `Widget(3)` still unresolved →
     `mojo_list_len((MojoList*)0)`.
   - `module_loader.module_name_for_path`: a package `__init__.py`
     *outside* `STDLIB_PATH` returns the bare basename `__init__`, so
     every out-of-tree package gets the same `__init__` symbol prefix
     and `___init___ZipFile___init__`-style method symbols nothing
     defines (observed directly once resolution was forced with
     `MOJO_PATH`). Fixing it to use the parent-directory name is a
     real latent-bug fix but the extra `base` reassignment perturbs
     self-host's return-type inference for `module_name_for_path`
     (callers in `monomorphize.py` / `build_stdlib_dylib.py` /
     `driver.py` then get `assignment to int64_t from char *`).

2. **`_Extra.split` (`@classmethod` generator) + `memoryview(...)`.**
   Once resolution is forced (`MOJO_PATH=.../Lib`, all three patches
   above applied), the whole `zipfile` module is dropped with
   `skip .../zipfile/__init__.py: cannot compile module: function(s)
   split (generator) ... split: a call to unresolved callee
   'memoryview(...)' is not supported in a compiled generator/coroutine
   body` → falls back to interpreting → no compiled symbols → link
   fails. This is the same wall the older Status entries below track;
   the A3 stack-switch cutover did not remove it for this shape.

3. **Transitive Python stdlib surface.** Behind (1)/(2): `io.BytesIO`,
   `zlib`/`bz2`/`lzma` bindings, `struct`, `binascii`, `os.stat`/
   `seek`/`tell`, `shutil`, `importlib.util`, `threading` — each a
   separate stdlib-porting project, as prior entries already note.

**Isolated-compile status is unchanged and still green**:
`compile_to_gimple(do_imports=False)` on `Lib/zipfile/__init__.py` →
~628 KB C, `gcc-mp-15 -fgimple -fsyntax-only` exit 0, and the emitted
signatures are correct (`MojoList * ZipFile_namelist (ZipFile *)`,
`char * ZipFile_mojo_read (ZipFile *, int64_t, int64_t)` — the `read`
return type should be `MojoBytes *`, a minor separate return-inference
gap). No code changed this session; no regression. Not `git rm`'d.

---


## Status (2026-09-06, os.path.splitdrive/splitroot + reversed() LANDED): probe cleaner; still not end-to-end

Two more codegen gaps surfaced by the `MOJO_DEBUG=1
compile_to_gimple(do_imports=False)` probe are now FIXED:

1. **`os.path.splitdrive()` / `os.path.splitroot()`** were stubbed
   (`int.splitdrive() stubbed`). Used at `zipfile/__init__.py:647`
   (`os.path.normpath(os.path.splitdrive(arcname)[1])`). Implemented
   properly (POSIX): `int64_t_path_splitdrive` -> `['', p]` always;
   `int64_t_path_splitroot` -> `[drive, root, tail]` mirroring cpython
   `posixpath.splitroot` verbatim (1 or >=3 leading slashes -> `'/'`,
   exactly 2 -> `'//'`). Dispatched in `gimple_gen_methods.py` like
   `os.path.split` (list-as-tuple, `char*` elements); type resolution
   in `gimple_gen_resolve.py` / `gimple_gen_infra.py`. Commit `5d9352c`.

2. **Silently-dropped `for` loop** — `for zinfo in reversed(sorted(
   self.filelist, key=lambda z: z.header_offset))` at
   `zipfile/__init__.py:1612` (`_RealGetContents` central-directory
   concordance check). Root cause: `reversed()` had NO lowering at all,
   fell through to the generic dynamic-dispatch stub producing a
   `void *`, and `_gen_stmt_ForStmt` silently drops a `for` over an
   unrecognized `void *` iterable (`mojo_unsupported_iter`, body runs
   zero times). `reversed()` now lowers to an eagerly reversed COPY of a
   list / str / bytes sequence (semantically identical for the single
   forward consumption every call site does), carrying element types
   through; any other codegen type is now an honest `RuntimeError`
   refusal, not a silent drop. Runtime: `mojo_cstr_reverse`,
   `mojo_bytes_reverse`. Commit `36357fc`.

**zipfile re-probe:** `compile_to_gimple(do_imports=False)` -> ~628 KB
of C, `gcc-mp-15 -fgimple -fsyntax-only` **exit 0** (warnings only). No
more `for loop dropped` / `int.splitdrive() stubbed` notes. Remaining
probe noise is the broad transitive-stdlib gap set (compress/decompress
codecs, `io.BytesIO`, `os.stat`/`seek`/`tell`/`read` on file objects,
`_encode_filter_properties`, `argparse`, `warnings.warn`, ...) — NOT
zipfile-codegen-specific; each is a separate stdlib-surface project.

Regression tests: `test_gimple.py`
(`os_path_splitdrive_splitroot`, `reversed_list_str_and_sorted_chain`) +
`test_gimple_runner.py` (`gimple_os_path_splitdrive_splitroot`,
`gimple_reversed_list_str_sorted` — real build-and-run).

Still **NOT `git rm`'d** — a full `fire.py build` (transitive stdlib
imports) still does not complete: `_Extra(bytes)` subclassing +
`struct.Struct` class attr + `super().__new__` end-to-end link, plus
the broad stdlib file-object / codec surface above, remain.

---

## Status (2026-09-06, builtin `bytes` subclassing LANDED as a feature): `class _Extra(bytes)` now has real payload storage + inherited-op delegation; zipfile still blocked behind the generator-codegen wall

Builtin-`bytes` subclassing (`class X(bytes)`) landed in the compiled
path, mirroring the builtin-`dict`-subclass work (commit 58d5900):

- **Stage 1 — representation + `__new__`.** `gen_module_impl` computes
  `self._bytes_subclass_structs` (fixpoint over local struct bases
  bottoming out at builtin `bytes`) and synthesizes a hidden
  `_data: MojoBytes *` payload field on each. The construction site
  (`_lower_struct_constructor`) populates `_data` from the argument the
  subclass's `__new__` forwards to `super().__new__(cls, <arg>)` (payload
  arg index precomputed; defaults to arg 0); the `__new__` body itself is
  not emitted as a callable C method. `__init__` still runs for extra
  `self.<attr>` instance fields (`self.id = id`), handled by the ordinary
  `_collect_self_assigns` path.
- **Stage 2 — inherited op delegation + override precedence.** `len(x)`,
  `x[i]` (→int), `x[a:b]` (→bytes), `for c in x`, `x == y`, `x + y`,
  `x % y`, `x in y`, `bytes(x)`, `isinstance(x, bytes)` (True), and the
  bytes method family (`.decode`/`.hex`/`.startswith`/`.split`/`.replace`/
  `.strip`/`.find`/`.count`/...) all route through the existing bytes
  lowering against `inst->_data`. A subclass method/dunder override wins
  (`_struct_defines_method` check, like the dict work).
- **Stage 3 — `b''.join(<iterable of subclass instances>)`** converts each
  element to its `_data` payload before `mojo_bytes_join`.

Regression tests: `test_gimple.py` (`bytes_subclass_payload_and_inherited_
ops`, `bytes_subclass_method_override_wins`) + `test_gimple_runner.py`
(`gimple_bytes_subclass_shape`, `gimple_bytes_subclass_method_override`,
`gimple_bytes_subclass_join` — real build-and-run).

**zipfile re-probe:** `compile_to_gimple(do_imports=False)` +
`gcc -fgimple -fsyntax-only` still **exit 0, zero errors** (unchanged —
the bytes-subclass shape was already syntax-clean because `_Extra` and a
number of `ZipFile` methods that transitively reference generator code
(`_write_end_record` → `_Extra.strip` → the `_Extra.split` classmethod
generator, `_sanitize_windows_name`, ...) are dropped from the relaxed
`do_imports=False` probe rather than compiled). A real `fire.py build`
(root module, non-relaxed) still hits the `_Extra.split` / `read` /
`_get_decompressor` generator-codegen wall the older entries below track.
Bytes-subclassing is no longer a blocker; the generator-codegen wall
remains. **NOT `git rm`'d.**

---

## Status (2026-09-06, blocker 3 FIXED): `compile_to_gimple(do_imports=False)` is now `gcc -fgimple -fsyntax-only` CLEAN (0 errors, was 2)

**Blocker 3 — FIXED.** `ZipFile._sanitize_windows_name` (+ its
`PyZipFile` inherited copy): `arcname = (x.rstrip(' .') for x in
arcname.split(pathsep))` then `arcname = pathsep.join(x for x in arcname
if x)` — a generator expression bound to the `char *`-typed `arcname`
PARAMETER, then iterated by a second genexp. The two `gcc -fgimple`
errors were `non-trivial conversion in 'mem_ref'` on `x = *_t34;` (the
second genexp lowered `arcname` as a CHAR loop).

Fix — a **bounded** narrowing (`gimple_gen_stmts.py`
`_seed_genexp_list_narrowing` + `_maybe_narrow_genexp_local`, hook in
`_lower_IdentExpr`, window-close in `_gen_stmt_AssignStmt`): a generator
expression assigned to a local, where a per-function flow-ordered
single-consumption analysis shows the local is read exactly once more —
and that read is the `.iterable` of a `for` / another comprehension — is
materialised as a LIST (semantically identical for a single forward
consumption). When the local already has a non-list C slot (a reassigned
parameter — the fresh-local case already worked via ordinary inference)
the list is stored into the slot as an opaque pointer and every later
read lowers as a properly-cast `MojoList *` until the name is rebound to
a non-genexp value. Conservative: a genexp local read more than once,
never iterated, or `global`-pinned is left untouched (its existing
behaviour / gcc error stands) — a twice-consumed genexp local still
compiles to the same unconditional materialisation it did before, never
a silent-wrong lazy second pass.

Also fixed an adjacent bug this uncovered: a comprehension `if x` filter
(`_gen_compr_append`) tested pointer-non-null instead of Python
truthiness, so an empty `char *` `""` wrongly passed — now routed
through `_ensure_bool_cond`. (`_sanitize_windows_name`'s `if x` needs
exactly this.)

**zipfile re-probe:** fresh `compile_to_gimple(do_imports=False)` +
`gcc-mp-15 -fgimple -fsyntax-only` → **exit 0, zero errors** (was 2).
No blocker 4 surfaced at the syntax-check level. `_Extra(bytes)`
subclassing + `struct.Struct` class attr + `super().__new__` remains a
documented feature-sized gap that would surface in a full link/run.

Full quality gate green: test_gimple.py 302/302, test_gimple_runner.py
44/44, test_module_cache.py 76/76 (new regression tests included),
test_gimple_generator_runner.py 85/4-known-fail, check-linkmode 3/3,
check-selfhost clean, compile_stdlib.py 664/664 (0 unexpected), stdlib
dylib from-scratch 0 skips, `make bootstrap` byte-identity — see commit.

Still not `git rm`'d — a full `fire.py build` (transitive stdlib
imports) was not completed this session (perf-bound under concurrent
machine load), and `_Extra(bytes)` subclassing still blocks an
end-to-end link.

---

## Status (2026-09-06, blockers 1 + 2 FIXED): down to ONE remaining blocker — genexp-held-in-a-local in `_sanitize_windows_name`

Two blockers landed this session. `compile_to_gimple(do_imports=False)`
now produces ~624 KB of C with exactly **2 gcc `-fgimple` errors left**
(the same error, in `ZipFile._sanitize_windows_name` and its
`PyZipFile` inherited copy).

**Blocker 1 — FIXED (commit `52107f5`).** `self._readbuffer = b''` in
`ZipExtFile.__init__` left the struct field typed `char *`, so
`buf = self._readbuffer[self._offset:]` went through `mojo_cstr_slice`
and `buf += self._read1(...)` (RHS `MojoBytes *`) fell to
`_lower_binary_tail`'s raw fallback, emitting `char* + (int64_t)MojoBytes*`
pointer arithmetic — garbage, and it also ICE'd GCC's GIMPLE frontend
(`internal compiler error: in build2, at tree.cc:5208`). Fixes:
`_collect_self_assigns` types a `b''` / `bytes()` / `bytearray()`
`self.<field>` assignment as `MojoBytes *`; `_infer_local_var_types`
now scans `var x = ...` VarDecl nodes (it only scanned AssignStmt
before); method return-type inference seeds inferred local var types so
`return <bytes-accumulator-local>` infers `MojoBytes *` not `int64_t`.
`ZipExtFile_mojo_read` / `read1` / `_read1` compile clean; ICE gone.

**Blocker 2 — FIXED (commit `00a2c25`).** `ZipFile.testzip`'s
`self.open(zinfo.filename, "r")` — `open` is a C-reserved name so the
mangled symbol is `..._ZipFile_mojo_open`, but the method's parameter
types were registered in `func_param_types` only under the raw key
`ZipFile_open`. `_emit_call` looks up by the mangled name, missed, and
skipped ALL argument coercion — a `char *` filename went straight into
the `int64_t name` (str|ZipInfo union) slot. `_lower_struct_method_call`
now mirrors the resolved param-type list onto the mangled key.

**REMAINING BLOCKER — genexp bound to a local, then iterated
(`_sanitize_windows_name`).** `arcname = (x.rstrip(' .') for x in
arcname.split(pathsep))` then `arcname = pathsep.join(x for x in arcname
if x)`. The scalar model can't hold a genexp object in a local, so
`arcname` stays `char *` and the second loop lowers as CHAR iteration
(`x = *_t34`) colliding with the char*-typed loop var from the first
loop — `non-trivial conversion in 'mem_ref'` x2. This is the
local-held-generator-consumed-as-iterable feature family (same as
fsutil.py's six-generator refusal list). Genuinely feature-sized; not
attempted this session.

Behind it still: `pwd=None` unannotated param has been de-risked by
blocker 2's coercion fix but not re-verified end-to-end past the
`_sanitize_windows_name` error; `_Extra(bytes)` subclassing +
`struct.Struct` class attr + `super().__new__` (feature-sized).

Still not `git rm`'d — does not compile end-to-end.

---

## Status (2026-09-06, GCC-ICE root-caused): NOT the module-constants theory — real cause is `buf += <bytes>` lowered as invalid `char* + int64_t` pointer arithmetic

Investigated the "~60 module-level constants re-materialized as LOCAL
declarations inside `ZipExtFile_mojo_read`" theory from the previous
Status entry. **That theory is wrong / already-resolved.** Fresh
`compile_to_gimple(do_imports=False)` on current master: every module
constant (`ZIP_STORED`, `ZIP_ZSTANDARD`, `_CD_*`, `_FH_*`, ...) is
correctly emitted ONCE as a file-scope `struct _root_toplev`
field + a `root__mojo_global_get_*` accessor, and every function body
reads it as `_root_globals.<name>` — there is NO per-function local
copy anywhere in the 625 KB of generated C (grep-confirmed: `  int
ZIP_ZSTANDARD;` etc. appear only inside the struct definition block,
lines ~1078-1200, never inside a function). A minimal 40-constant
repro confirms the same. Added `test_gimple.py` regression test
`many_module_constants_are_file_scope_globals` to lock this in.

**The GCC ICE (`internal compiler error: in build2, at tree.cc:5208`)
is real but mis-attributed.** GCC's GIMPLE frontend prints the ICE
location as a `struct _root_toplev` FIELD_DECL line (`int
ZIP_ZSTANDARD;` / `int _FH_CRC;` — it shifts as the struct shifts) and
`In function 'ZipExtFile_mojo_read'` / `ZipExtFile_read1`, but the real
trigger is a statement in the `ZipExtFile.read*` family. Root-caused by
delta-reduction to a self-contained 8-line repro:

```c
typedef long int64_t;
void __GIMPLE f (char * buf, int64_t k)
{
  char * _t25;
bb_2:
  _t25 = buf + k;      /* char* + int64_t, result dead / used only across a BB edge */
  return;
}
```

`gcc-15 -fgimple -fsyntax-only` ICEs at `build2`, tree.cc:5208 on that
one statement. It does NOT ICE when the `char* + int` result is
consumed in straight-line code in the same basic block (`buf = _t25;
return buf;`) — so it is a genuine GCC GIMPLE-FE bug in how it lowers
`pointer + non-sizetype-integer` to `POINTER_PLUS_EXPR` when the result
crosses a CFG edge.

But the generated statement is *also* semantically wrong on our side.
It comes from `ZipExtFile.read`/`read1`/`_read1`'s
`buf += self._read1(...)` accumulation, where `buf` was typed `char *`
(from `self._readbuffer[self._offset:]` → `mojo_cstr_slice`, a `char *`)
and the RHS is a `MojoBytes *`. `_lower_binary_tail` has no
`char * + MojoBytes *` case, so it falls to the raw
`{lv} {op} {rv}` fallback and emits `buf + (int64_t)data` — pointer
arithmetic by the *address* of the bytes object. Pure garbage even if
GCC accepted it.

**Real fix = the bytes value type**, which landed: `buf` must be a real bytes
value (`MojoBytes *`) end-to-end so `buf += data` routes to
`mojo_bytes_concat`, which the existing `MojoBytes * + MojoBytes *`
case in `_lower_binary_tail` already handles. A narrow
`char * + MojoBytes *` → `mojo_str_cat(buf, mojo_bytes_to_cstr(data))`
shim would stop the ICE but silently truncates on the embedded NUL
bytes that ZIP extra fields legitimately contain — deliberately NOT
taken (matches the NUL-termination hazard already flagged in older
entries below). Touching the shared `_lower_binary_tail` also trips the
full gimple/codegen quality gate (bootstrap byte-identity +
compile_stdlib U-count), disproportionate for a lossy shim.

Behind this ICE the previously-documented blockers still stand:
`pwd=None` unannotated param, genexp-held-in-local in
`_sanitize_windows_name`, `_Extra(bytes)` subclassing.

Still not `git rm`'d — does not compile end-to-end.

## Status (2026-09-06, bound-container-method-as-value): blocker #2 FIXED; module now dies later, on a GCC internal compiler error

Blocker #2 (`'MojoBytes' has no member named 'append'` — `_ZipDecrypter.
decrypter`'s `result = bytearray(); append = result.append` then
`append(x)`) is **FIXED**. `_lower_MemberExpr`'s builtin-method-as-value
branch and `_lower_builtin_bound_method_call` only handled
`MojoList`/`MojoDict`/`MojoSet` receivers; a `MojoBytes *` /
`MojoMemoryView *` receiver fell through to a struct-field read and
emitted an invalid `->append`. Both sites now route bytes/bytearray via
`_lower_bytes_method` and memoryview via `_lower_memoryview_method`,
matching the direct-call spelling. Minimal repros (list/dict/set/
bytearray `.append`/`.setdefault`/`.add` bound to a local + called in a
loop; the exact `_ZipDecrypter.decrypter` shape) compile+link+run.

Fresh `compile_to_gimple(do_imports=False)` now produces ~625 KB of C
that gets further and dies on a NEW first blocker:

**NEXT BLOCKER — GCC internal compiler error in `ZipExtFile_mojo_read`.**
`gcc -fgimple -fsyntax-only`: `internal compiler error: in build2, at
tree.cc:5208` on `int ZIP_ZSTANDARD;` — one of ~60 module-level
zipfile constants (`ZIP_STORED`, `_CD_*`, `_FH_*`, ...) hoisted as
locals into `ZipExtFile_mojo_read`. This is a GCC crash (not a Mojo
codegen diagnostic), triggered by that function's very large local-decl
block; feature/​infra-sized (either shrink the hoisted-constant set per
function, or fold module constants into real file-scope globals). The
`pwd=None` unannotated param, genexp-held-in-local, and `_Extra`
subclassing blockers documented below still stand behind it.

Still not `git rm`'d — does not compile end-to-end.

## Status (2026-09-06, bytes-value-type Stage 4): generator-body memoryview refusal GONE; module now dies later, on real ordinary-path bytes-codegen bugs

`gimple_gen_coro._eligible` now accepts a `@classmethod` generator whose
body doesn't reference `cls`, so `_Extra.split` is lowered by the A3
stack-switch backend (ordinary codegen, full memoryview support) instead
of the C++ emitter that refused `memoryview(...)`. The up-front
`RuntimeError("cannot compile module: function(s) split ...")` is GONE —
`compile_to_gimple(do_imports=False)` now produces ~763 KB of C.

That C does NOT yet `gcc -fgimple` clean. The error set moved from a
generator-gate refusal to real ordinary-path bugs (exactly the §5.5
"a previously-refused generator that still fails is now a real
ordinary-path bug, exposed" outcome):

1. **FIXED (2026-09-06)** — `mojo_bytes_new_lit (_slit_NNNN, N)` "invalid
   argument to gimple call". Every `b'...'` / `b''` literal passed the
   `_slit_` string-pool GLOBAL directly as a call argument;
   `-fgimple` strict mode requires it loaded into a local first (the
   plain `char *` string-literal path already does this). Fixed at both
   bytes-literal emit sites in `gimple_gen_exprs.py` (`_lower_String
   Literal` bytes branch + `_lit_bytes` in the bytes `%`-format path).
   Minimal repro (`b''.join(parts)` in a classmethod, `b'%d' % x`) now
   compiles.
2. **`'MojoBytes' has no member named 'append'`** (`_ZipDecrypter.
   decrypter`: `result = bytearray(); append = result.append`). This is
   the bound-method-of-a-container-value-held-in-a-local gap (`append =
   result.append` then `append(x)`), not bytes-specific. `result.
   append(x)` directly compiles fine. First hard blocker now.
3. The previously-documented further blockers still stand behind these:
   `pwd=None` unannotated param (read/testzip -> mojo_open), genexp-held-
   in-local in `_sanitize_windows_name`, `_Extra(bytes)` subclassing +
   `struct.Struct` class attr + `super().__new__`.

Still not `git rm`'d — does not compile end-to-end.

## Status (2026-09-06, bytes-value-type Stage 3): ordinary-path memoryview NOW implemented; coroutine-body memoryview still refused

`bytes`/`bytearray`/`memoryview` value types landed in the ordinary
GIMPLE path: `memoryview(<bytes|bytearray>)`,
`mv[i]`, `mv[a:b]` (non-copying sub-view), `len`, iteration, `.tobytes`,
`.hex`, `.cast`, `mv == b'...'`, `bytes(mv)` all compile + run.

BUT `_Extra.split` is a **`@classmethod` generator**, and the C++
coroutine-body emitter (`gimple_cpp_core.py` ~line 3582) still refuses
`memoryview(...)` as an unresolved callee — the ordinary-path
constructor lowering does not reach it. Fresh
`gimple_codegen.compile_to_gimple(src)` reproduces byte-for-byte:
`split: a call to unresolved callee 'memoryview(...)' is not supported
in a compiled generator/coroutine body`. Wiring memoryview into the
coroutine-body emitter is a separate, self-contained follow-up; even
once done, this file still has the ≥3 other documented blockers
(pwd=None unannotated param, genexp-held-in-local in
`_sanitize_windows_name`, FileHeader int32 under-widening residue). Not
`git rm`'d.

## Status (re-verified 2026-08-26, worktree-agent-a21934cd6fb7c6509 @ master `e60b9cd`): memoryview refusal confirmed unchanged

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` on the
file against this worktree (fast-forwarded to master `e60b9cd`):
byte-for-byte the same up-front refusal — `split` (the `_Extra.split`
classmethod generator) refused for `memoryview(...)` being an
unresolved callee in a compiled generator/coroutine body. The {ptr,len}
view type remains genuinely feature-sized across both code paths;
`pwd=None` stays on the excluded unannotated-init-param family;
genexp-held-in-local stays feature-sized. Per this session's mandate,
not attempted; no code change.

## Status (re-verified 2026-08-26, worktree fix/opencode-misc1 @ `e1e12bb`): memoryview refusal confirmed unchanged

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` on the
file against this worktree (includes this session's dict-keyed
%-formatting landing, commit `e1e12bb` — unrelated to memoryview):
byte-for-byte the same up-front refusal — `split: a call to unresolved
callee 'memoryview(...)' is not supported in a compiled generator/
coroutine body`. Re-confirmed by grep that `memoryview` still has zero
real implementation in `gimple_codegen.py`/`gimple_cpp_core.py` (only
the refusal-message string). The {ptr,len} view type remains genuinely
feature-sized across both code paths; `pwd=None` stays on the excluded
unannotated-init-param family; genexp-held-in-local stays feature-sized.
Not attempted; no code change.

## Status (re-verified 2026-08-26, worktree fix/rest-remainder19c): memoryview refusal confirmed as the first blocker, unchanged; other documented aspects re-checked and still accurate

Fresh `compile_to_gimple_with_cpp(do_imports=False)` on the file alone
reproduces byte-for-byte: `split: a call to unresolved callee
'memoryview(...)' is not supported in a compiled generator/coroutine
body`. Per this round's scope, deliberately did NOT attempt the
excluded `pwd=None` unannotated-init-param mechanism. Re-checked that
the other three documented groups (memoryview, genexp-held-in-local,
pwd=None) are still accurately described relative to current source —
they are; nothing in this campaign's very recent landings
(super()/self.__class__ construction lowering, generator value-
carrying return-slot, str-method families) touches memoryview support,
which remains genuinely absent from both the plain GIMPLE path and the
C++ coroutine path (grepped both `gimple_codegen.py` and
`gimple_cpp_core.py` for `memoryview` — zero real implementations,
only the refusal-message string literal). Not attempted; feature-sized.
No code change.

## Status (re-verified 2026-08-25, wtOpencode_group3): memoryview refusal confirmed as the first blocker, unchanged

Fresh isolated generation (`compile_to_gimple_with_cpp` on the file
alone) reproduces the documented up-front refusal byte-for-byte:
`split: a call to unresolved callee 'memoryview(...)' is not supported
in a compiled generator/coroutine body`. A full safety-wrapped
`fire.py build` was also attempted but got watcher-killed at the 300s
wall-clock cap during transitive-import processing (machine heavily
contended by concurrent agents' builds this session; zero zipfile-
attributed gcc errors in the partial log before the kill — consistent,
not a new data point). The doc's classification stands: memoryview
needs a real {ptr,len} view type across both code paths (feature-sized;
NUL-termination hazard noted below still applies); `pwd=None` stays on
the excluded unannotated-init-param family; genexp-held-in-local stays
feature-sized. No code change.

## Status (updated 2026-08-25, wtOpencode_zipfile / fix/opencode-zipfile -- TWO of the four groups FIXED, error set shifted again)

Re-ran fresh. The error set has SHIFTED again since the 2026-08-24
re-check: issue group (1)'s call-site half was fixed on another branch
(2c9fe02, "module-qualify + cross-module hint compiled generator
symbols") between sessions, so compilation now gets further and dies
EARLIER, on a new first-order blocker inside `_Extra.split` itself:

```
Error building: cannot compile module: function(s) split (generator ...)
 Unsupported shape(s): split: a call to unresolved callee
 'memoryview(...)' is not supported in a compiled generator/coroutine
 body (...)
```

**NEW FIRST BLOCKER — memoryview in a compiled generator body.**
`_Extra.split` (a `@classmethod` generator) does `rest = memoryview(data)`
then `while rest:` + slices. `memoryview` has NO implementation anywhere
in this codegen (zero occurrences outside bugs/ docs): strings/bytes are
NUL-terminated `char *`, and there is no {ptr,len} buffer-view value.
Honest support means a real view type (slicing producing sub-views,
length-based truthiness, `.nbytes`) across BOTH the ordinary GIMPLE path
and the C++ coroutine-body path — zipfile also uses `memoryview` in
`_ZipWriteFile.write` (~line 1334, non-generator). Note the NUL-
termination problem too: ZIP extra fields legitimately contain 0x00
bytes, so even a char*-identity lowering would be semantically wrong.
Feature-sized; not attempted.

To expose the blockers BEHIND it, diagnosed against a scratch copy
(`/tmp/zipdiag/zf.py`, `split`'s body de-memoryview'd — diagnostic only,
no runtime fidelity claimed for that copy). With memoryview out of the
way the remaining error set is exactly four gcc diagnostics, and TWO of
the doc's four groups are now genuinely FIXED (all four quality gates
green after each change; test_gimple 253/253, test_module_cache 76/76,
self-host clean, stdlib dylib 0 skips):

1. **FIXED (commit 6fc759a) — group (2), FileHeader int32 under-widening.**
   Root cause was NOT struct-field narrowing as theorized below (the
   `self.compress_size = 0` fields are typed int64_t just fine). The real
   bug: `_gen_stmt_MultiAssignStmt` declared a first-time chained-assign
   target from the RAW lowered RHS type — literal `0` lowers to C 'int' —
   ignoring the function-wide `_inferred_var_types` hint that the single-
   target path (`_assign_target`) has consulted since
   CODEGEN_multi_assign_local_var_type_not_inferred.md. That hint DOES
   see `file_size = 0xffffffff` later in the body (int64_t), so honoring
   it declares the locals int64_t and both "non-trivial conversion in
   'integer_cst'" errors and the comparison-operand error vanish.
   Verified end-to-end: minimal repro (chained zero-init + 0xffffffff
   reassign + ZIP64_LIMIT comparison) compiles AND returns correct
   values (zip64 sentinel path fires: 2x4294967295).

2. **FIXED (commit 4d3626d) — group (1) RESIDUE, `_Extra.strip`'s
   `cls.split(data)` call.** After 2c9fe02 one -Wint-conversion remained:
   `_lower_method_call`'s generator-method branch passed the
   POST-resolution receiver pair to `<base>_start`; the classmethod-
   receiver block had by then retagged `cls`'s int64_t pair to
   `'_Extra *'`, and coercing that into the start function's slot 0
   (the opaque never-read int64_t cls placeholder per
   gimple_cpp_async.py's param_ctypes) went through
   `_ensure_local('_Extra *', 'cls')` → `_Extra * _t6 = cls;`. Now, when
   slot 0 of the registered start signature is 'int64_t' (exactly the
   classmethod-placeholder shape) and the receiver lowered to a scalar,
   the raw pre-resolution pair is passed straight through. Verified
   end-to-end with a minimal classmethod-generator + genexp-consumed-by-
   join repro: compiles AND produces correct output.

3. **FIXED (commit 4094f7a) — NEW residual found this session.**
   `ZipFile._sanitize_windows_name`: "request for member
   '_windows_illegal_name_trans_table' in something not a structure or
   union". The method-scalar-observation pass mapped call args onto
   parameter names excluding only 'self', so the instance-called
   classmethod `self._sanitize_windows_name(arcname, os.path.sep)`
   observed arcname's 'char *' evidence onto `cls` (and shifted every
   later observation up a slot). cls then being 'char *' made the body's
   `cls._windows_illegal_name_trans_table = table` write emit a raw
   `cls->_attr` field store on a non-struct. Classmethods now exclude
   their implicit `cls` receiver from arg→param mapping. Both x2 error
   groups gone.

REMAINING after these fixes (scratch copy; real file additionally blocked
by memoryview above):

- **pwd caller/callee disagreement x2 (read/testzip → mojo_open)** —
  unchanged in substance: callee `open(..., pwd=None)`'s slot resolved
  int64_t while `read`'s forwarded `pwd` is inferred 'char *'. Confirmed
  this is exactly the unannotated-None-default-param family
  (bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md, which
  supersedes the removed
  CODEGEN_unannotated_init_param_field_type_defaults_int64.md);
  explicitly out of scope this session per campaign rules. Still open.
- **`_sanitize_windows_name` "non-trivial conversion in 'mem_ref'" x2**
  — different root cause than the (now-fixed) member-store error: the
  source REBINDS `arcname` to a generator-expression OBJECT
  (`arcname = (x.rstrip(' .') for x in arcname.split(pathsep))`) and the
  next statement ITERATES that local (`pathsep.join(x for x in arcname
  if x)`). This scalar model can't hold a genexp object in a local, so
  `arcname` stays char* and the second loop lowered as CHAR iteration
  (`x = *_t36` deref) colliding with the char*-typed loop var declared by
  the first loop. Local-held generator/genexp consumed as an iterable is
  the same feature-sized family recorded on fsutil.py's six-generator
  refusal list; not attempted.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C4 cluster. All four residual issues (classmethod-generator receiver-passing mismatch in `_Extra.strip`; `int`/`int64_t` struct-field width under-inference in `FileHeader`; the `pwd=None` caller/callee signature disagreement) are unaffected by this session's two landed fixes elsewhere (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies -- none of this file's own blockers touch string methods or stdin/stdout/stderr-named fields). Still structural / shared fragile type-inference machinery; untouched.


Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-23, wt09 fix/stdlib-mods `945af88` — unchanged in substance)

Re-ran the repro fresh. Same four issue groups as the 2026-08-09
analysis below, none fixed this pass either:

```
error: assignment to '_Extra *' from 'int64_t' ... makes pointer from
       integer without a cast          (_Extra.strip, line 228)
error: non-trivial conversion in 'integer_cst'   (x2, FileHeader ~547-548)
error: passing argument 2/3 of 'ZipFile_mojo_open'/'PyZipFile_mojo_open'
       makes integer from pointer without a cast  (~1666/1690/1699, pwd)
```

Assessment reconfirmed for each: (1) `_Extra.strip`'s `cls.split(data)`
call site vs. the classmethod-generator machinery that per the write-up
below took three incidents to stabilize — deliberately untouched;
(2) FileHeader's compress_size/file_size locals under-widened from the
`int`-typed struct fields (themselves narrowed from literal-`0` init) —
a shared field-typing-machinery change, not narrow; (3) the `pwd=None`
caller/callee signature disagreement — same unannotated-param family.
Still open; no code changes made this pass.

## Status (updated 2026-08-09)

Re-ran fresh; error set has SHIFTED since the previous write-up (some
line numbers moved, the previous vague "line-number misattribution,
not root-caused further" writeup is replaced below with concrete root
causes for each). Nothing fixed this session — all four are either a
new instance of an already-tracked structural gap, or open up a
genuinely new one; none looked safely narrow enough to touch given
this session's time budget and this codebase's documented history of
narrow-looking fixes to shared type-inference machinery causing broad
silent regressions.

```
error: assignment to '_Extra *' from 'int64_t' makes pointer from
       integer without a cast          (line 228)
error: non-trivial conversion in 'integer_cst'   (x2, near line 567,
       actually ZipInfo.FileHeader ~line 547-548)
error: mismatching comparison operand types       (near line 625,
       actually ZipInfo.FileHeader ~line 542)
error: passing argument 3 of 'ZipFile_mojo_open' makes integer from
       pointer without a cast           (line 1690)
error: passing argument 3 of 'PyZipFile_mojo_open' makes integer from
       pointer without a cast           (line 1699)
```

1. **Line 228, `_Extra.strip`** (a `@classmethod`, NOT itself a
   generator — it calls `cls.split(data)`, which IS a `@classmethod`
   generator, from inside a generator-expression consumed by
   `b''.join(...)`). Traced via the generated `.ci`:
   `_Extra_strip(int64_t cls, int64_t data, int64_t xids)`'s body does
   `_t6 = cls;` into a temp DECLARED `_Extra *`, then
   `_mojogen__Extra_split_start(_t5, data)` (the generator's start
   function) — i.e. codegen is trying to pass `cls` as a real `_Extra
   *` receiver pointer to the generator constructor, but `cls`'s own
   parameter is declared plain `int64_t` in `_Extra_strip`'s own
   signature. This is a NEW manifestation of the classmethod-generator
   family already tracked in `bugs/hard/
   CODEGEN_generator_classmethod_first_param_must_be_self.md` (marked
   FIXED for the "a generator METHOD's own first param is cls" case),
   but this is the mirror shape: a NON-generator method CALLING another
   class's classmethod generator via `cls.method(...)`. `split`'s own
   `cls` (unused in `split`'s body — it calls `_Extra.read_one(...)` by
   bare class name, not `cls.read_one`) gets compiled as an opaque,
   never-read `int64_t cls` placeholder per that fix's documented
   approach — but the CALL SITE in `strip` doesn't know that and tries
   to pass a real pointer value anyway. Fixing this correctly means
   teaching the `cls.method(...)` call-site lowering (wherever it
   decides how to pass the receiver arg to a classmethod-generator's
   start function) to agree with how that generator's OWN parameter got
   compiled — genuinely touches the same fragile classmethod-generator
   machinery that took three separate incidents to get right the first
   time (per that doc's own history). Classified structural; not
   attempted.

2. **`ZipInfo.FileHeader`, lines ~530-548** (GCC's own `#line`
   attribution points at 567/625 — blank/docstring lines past the
   function, the same "-fgimple errors point at the last-seen `#line`
   directive, not the real one" pattern noted in the previous version
   of this doc; the REAL culprit is inside `FileHeader`, confirmed via
   GCC's own printed statement text, e.g. `file_size = 4294967295;`).
   `compress_size`/`file_size` are LOCAL variables:
   `if ...: CRC = compress_size = file_size = 0` (a chained multi-
   assign, RHS `0`) `else: compress_size = self.compress_size;
   file_size = self.file_size` (a plain single assign from a STRUCT
   FIELD). Whichever assignment `_infer_local_var_types`'s whole-body
   pre-pass used to lock these locals' declared C type picked plain
   `int` (32-bit) — almost certainly inherited from
   `self.compress_size`/`self.file_size`'s own STRUCT FIELD ctype,
   itself narrowed to `int` because `ZipInfo.__init__` only ever
   initializes them with the small literal `0` (line 480-481). Later in
   the SAME function, `file_size = 0xffffffff; compress_size =
   0xffffffff` (~547-548, real ZIP64 sentinel values, both
   4294967295 — exceeds `INT32_MAX`) assigns a literal that doesn't fit
   the locked-in 32-bit `int`, which `-fgimple` rejects outright
   ("non-trivial conversion in 'integer_cst'") rather than silently
   truncating. The "mismatching comparison operand types" error a few
   lines earlier (`zip64 = file_size > ZIP64_LIMIT or ...`, ZIP64_LIMIT
   = `(1 << 31) - 1`, an `int64_t`-range constant) is the SAME root
   cause: comparing the (wrongly 32-bit) `file_size` against a value
   the codegen infers as 64-bit. This is a struct-field-type-
   propagation gap (a plain-Python `int` field whose only *literal*
   initializer happens to fit 32 bits gets under-widened, then a later
   *local* reassignment with a value that needs the full 64 bits
   breaks) — recognized as matching this session's "struct-field
   type-propagation gap on assignment" pattern, but the actual fix
   surface (wherever a struct field's ctype gets decided from its
   `__init__` literal initializers) is shared machinery touched by
   several other already-fragile field-typing bugs in this session's
   history; not attempted given the same caution.

3. **Lines 1690/1699, `ZipFile.read`/`PyZipFile` opening a member with
   a password**: `def read(self, name, pwd=None): with self.open(name,
   "r", pwd) as fp: ...` — `pwd` is an unannotated `bytes | None = None`
   parameter forwarded positionally into `self.open(...)`'s own `pwd`
   parameter (also `bytes | None = None`). The call site's `pwd` value
   resolves to `int64_t` (the standard "unannotated param defaulting
   from a bare `None` literal infers int64_t" gap, same family as
   `bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md`), while the
   callee's OWN declared parameter type for
   `pwd` apparently resolved differently (a pointer type, from some
   OTHER call site elsewhere in the file that passes a real bytes
   value) — a caller/callee signature disagreement, "makes integer
   from pointer without a cast". Same structural class; not
   attempted here for the same reason as issue 2 above (shared
   call-argument type-inference machinery).

None fixed here. All four are either instances of already-tracked
structural gaps or open a closely related new one in the same
machinery — kept open rather than force a narrow-looking fix into
code this session's own history shows is easy to silently break
broadly.

Exit code: 1
