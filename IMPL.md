# Implemented Features

This document records features that are fully implemented and working.
See `PLAN.md` for future and deferred work, and `STDLIB.md` for the
current stdlib transpilation status, what fails, and remaining gaps.

**Current Status** (as of 2026-06-05):
- **Stdlib transpilation**: 642/643 `.mojo` files across the whole upstream
  stdlib tree (`benchmarks`, `std`, `test`, `tools`) transpile through
  `mojo_compiler.py`. The single failure is nested t-strings — see `STDLIB.md`.
- **GIMPLE unit suite** (`make check-gimple`): 153/153 passing.
- **Execution suite** (`make check-runner`): 8/8 passing.
- **Module-cache suite** (`make check-modcache`): 15/15 passing — stages 1-6 of
  `MODULE_CACHE_DESIGN.md`, exercised end-to-end (link, dylib, CAS, reflection,
  monomorphization, comptime).
- `make check` = gimple + runner + module-cache (all green). The self-hosting
  bootstrap (`make bootstrap`: stage1-3 + `validate-all`) is a **separate**
  target, not gated into `check`. **Update 2026-07-06**: stage1/stage2/stage3/
  `verify` now pass cleanly with zero crashes anywhere in the transitive
  closure (the historical stage-2 segfault and a long chain of follow-on bugs
  are fixed — see "Recent Work (2026-07)" below). `validate-all` still fails
  its file-count check — a real but separate, pre-existing gap: the `stage1:`
  Makefile target only ever dumps `mojo.py` itself, never loops over the
  other ~40 test/core files the way `stage2`/`stage3` do.

---

## Recent Work (2026-06)

- **Module cache, stages 1–2** (see `MODULE_CACHE_DESIGN.md`, `ABI.md`) — moving
  the import boundary from inline-transpile toward a cached-dylib/CAS model.
  - **MLIR floor** (`mlir.py`): the stdlib's scalar newtypes (`Int` = a newtype
    over `__mlir_type.index` = `int64_t`) and their `__mlir_op`/`__mlir_attr`/
    `__mlir_type` operations lower to plain C. Table-driven; ~130 stdlib opcodes
    classified (≈59 lowered, the rest deferred-with-reason: GPU/coro/atomics/…).
    Includes `external_call` → direct C syscalls (e.g. `write`), `index`/`pop`/
    `arith` arithmetic+compares, casts, memory ops (`pop.load/store/offset`),
    struct GEP (`kgen.struct.extract/gep`, `pop.array.get`), and a `Span`
    `{_data,_len}` model — enough that the real `FileDescriptor.write_bytes`
    lowers natively to `write(fd, Span_unsafe_ptr(b), b->_len)`.
  - **Stage 1 — extern-decl import boundary** (`link_imports` in
    `gimple_codegen.py`): imports emit `extern` decls (signatures from
    `module_loader`, contract in `ABI.md`) instead of inlining bodies; the
    transitive-closure compile remains the artifact builder. Off by default.
  - **Stage 2 — stdlib dylib** (`build_stdlib_dylib.py`, `make stdlib-dylib`):
    bundle library modules + runtime into `build/libmojostdlib.dylib`; a client
    compiled in link mode produces a ~1.5 KB object and links `-lmojostdlib`,
    with bodies demand-paged from the dylib. Verified end-to-end (link + run).
  - **Stage 3 (tier 1) — content-addressed store** (`cas.py`): module objects are
    keyed by a content hash of *all* compile inputs (ABI version + compiler-source
    fingerprint + toolchain/target + module source + imported signatures), so a
    hit is provably the same output. Dup-tolerant: temp-write + atomic
    `os.replace` publish, hash-named immutable artifacts, no coordination.
    Integrated into the dylib build: warm = load (no codegen/gcc), cold = compile,
    source/compiler/ABI change = miss. Tier 2 (sharded single-flight + TTL leases,
    the shm `cas.c`) is deferred-by-design until concurrent load justifies it.
  - **Stage 4 — reflection layer** (`reflect.h`, `reflect.py`): each dylib exports
    a plain-C-ABI `__mojo_reflect` table (symbol name + C signature + address).
    The compiler's own import path reads it (`module_loader.read_reflection`, via
    ctypes), and so can any C-ABI consumer — verified by a pure-C program that
    `dlopen`s the dylib, walks the table, and calls functions by address. One
    unified import interface; full polyglot interop.
  - **Stage 5 — monomorphization engine** (`monomorphize.py`,
    `cas.instantiation_key`): a generic instantiation is keyed by (template
    identity + concrete type args + comptime params) and published into the
    shared CAS — instantiate once, ever. Verified: `box_id[Int64]` and
    `box_id[Float64]` cache as distinct objects, re-instantiating `box_id[Int64]`
    is a hit, and the cached object links + runs. (Substitution is textual/demo;
    the production path is AST-driven via `DispatchSolver`.)
  - **Stage 6 — comptime as cached machine code** (`comptime.py`): a comptime
    function is compiled to a CAS-cached dylib *once*, then the compiler
    `dlopen`s it and **calls** it with the comptime args — real machine code at
    compile time, not tree interpretation. Verified with loop (`fact`) and
    recursion (`fib`) matching interpreted references; the dylib is compiled once
    and reused across calls (2 misses / 4 hits). `_eval_const_*` remains the
    fallback (foundation-first).
  - **Wired into the CLI** (`imports.py`, `driver.py`, `mojo.py`): `mojo build`/
    `run` now go through the module-cache system. `import` is the seam — it
    resolves each module to its CAS dylib, wires the `__mojo_reflect` ABI, and
    **records the dylib on the program's link line** (`gen._link_dylibs`;
    `compile_linked` returns them). The **runtime is a first-class dylib**
    (`build_stdlib_dylib.runtime_dylib`); module dylibs no longer bundle it
    (`-undefined dynamic_lookup`) and depend on it. The driver is thin: compile
    the client (link mode) + link the runtime dylib + every recorded import dylib;
    the OS loader binds the symbols (we don't reinvent dyld). The whole program is
    content-addressed (warm run = instant copy), with a fallback to the inline
    builder. Verified end-to-end: `mojo t.mojo` with 0, 1, and 2 imports runs and
    links exactly the recorded dylibs. Symbol clashes across modules are resolved
    by `<module>_name` (convention today; systematic mangling is the next step).
  - **Module-resolution authority** (`imports.Resolver`): our `sys.modules`. One
    ordered search path — `$MOJO_PATH` first (ours), then `$PYTHONPATH` (superset
    of Python), then project/runtime/stdlib — and **exactly one module per
    fully-qualified name**: first match wins, is cached, and is shared by every
    importer, so `import io` denotes one `io` everywhere (no two `io`s coexisting).
    Shadowed candidates are reported, first-wins (Python semantics). Identity (the
    FQ name) drives link-line dedup and the `<module>_` symbol prefix; codegen and
    driver share the one authority.
- **`make check` repair** — the generated `main()` wrapper unconditionally
  called `_toplevel()`, but that function is only emitted when a module has
  top-level statements. Programs with a `main` and no top-level code (every
  test case) hit an implicit declaration. The codegen now pre-scans for
  top-level statements (`_has_toplevel_code`) and trims the call when empty,
  emits-and-calls otherwise. Module top-levels use `{module}_` prefixed names.
- **`compile_stdlib.py`** now scans the entire stdlib tree, not just `std/`:
  `DEFAULT_ROOTS = [benchmarks, std, test, tools]`, with a `--roots` flag. It
  also invokes `sys.executable` rather than a bare `python` (absent on some
  hosts), which had been silently failing every subprocess.
- **New front-end syntax** driven by the benchmarks/test corpus:
  - Calling-convention markers on function types and declarations:
    `def(...) thin abi("C") -> T`, `fn ... abi("C") -> T:`. `raises` lexes as a
    keyword (unlike `thin`/`abi`), so qualifier loops accept both token kinds.
  - Template strings: `t"..."` (single-level; nested t-strings unsupported).
  - Comptime-call-in-type chains: `-> ref[s] _field_types_of[Self.T]()[idx]`.
  - `with EXPR as <kw>:` — keywords allowed as the `as` alias (via `_ident()`).
  - `comptime for a, b in ...` — tuple targets in comptime for-loops.
  - Multi-clause comprehensions: `{a*b for a in xs for b in ys}` (list/set/dict).
  - Extended slices with step: `a[::2]`, `a[1:-1:1]`, `a[::-1]`.
  - Multi-dimensional slice subscripts: `a[0:2, ::]`, `a[:, 0]`, via a unified
    `_parse_subscript_item()` model.
  - Parenthesized ownership binding targets: `(var x), (ref y) = ...`.

---

## Recent Work (2026-07)

### Exceptions actually work at runtime on macOS arm64

`mojo_try_push` wrapped `setjmp` in a function that returns — `longjmp` to a
`jmp_buf` whose `setjmp` frame has already returned is undefined behavior, and
on macOS arm64 it silently resumed *after* the raise site instead of entering
the handler, so every compiled `try/except` took the non-exception path and
`raise` was a no-op. Fixed by making `mojo_try_push` a `#define` macro in
`mojo_runtime.h` so `setjmp` executes directly in the caller's frame.
`ABI.md` documents the macro nature of this entry point.

That fix was necessary but not sufficient: the "stage-2 bootstrap segfault"
class turned out to be at least nine separate, independent bugs, found one at
a time by running `stage2/mojo --dump ../mojo.py` (then every `.mojo`/`.py`
file) under lldb until they stopped crashing:

- `os.environ.get`/`[]`/`in`/assignment had no lowering (fell to
  `mojo_obj_getattr`'s stub → null deref) — added `ast_rewriter.py`'s
  `os_environ_*` rules.
- `str.rsplit` was an unimplemented stub returning a null `MojoList *` —
  real `mojo_str_rsplit` added.
- No list/string accessor normalized negative indices (`list[-1]` read
  `data[-1]`, out of bounds) — fixed in `mojo_list_get_int/get_double/
  get_str/set_*` and `mojo_str_char_at`.
- Container truthiness (`if some_list:`) was a pointer-null check, not a
  length check — fixed to call `mojo_list_len`/`mojo_dict_len`/
  `mojo_set_len`/`mojo_truthy_cstr`, all NULL-safe.
- Ternary expressions evaluated both branches unconditionally — worked
  around at two call sites here; fixed at the root below.
- `subprocess.run(...).returncode`/`.stdout`/`.stderr`, `sys.stdin.read()`,
  `platform.system()`/`.machine()` had no implementation — real runtime
  functions added (`mojo_subprocess_run`, `mojo_stdin_read`,
  `mojo_platform_system`/`_machine`), wired via `ast_rewriter.py`.
- `_TYPE_MAP` had a literal `None` dict key, crashing `MojoDict` construction
  (string-keyed only) — the entry was dead code; removed.
- `__name__` was hardcoded to `"__main__"` for *every* compiled module, root
  or transitively imported, so every inlined script's own
  `if __name__ == '__main__': main()` guard fired as a side effect of being
  imported. Now resolves per-module via `self.module_name`.
- Fixing `__name__` exposed a masked double-invocation bug: the generated
  `main()` wrapper called `_toplevel()` (which now correctly runs the root's
  own `if __name__ ==`) *and then* called `_gimple_main()` again
  unconditionally. Every self-hosted program's `main()` was running twice.

With all of the above, `make bootstrap`'s stage1/stage2/stage3/`verify`
sequence passes cleanly.

### Ternary expressions branch for real instead of evaluating both sides

`_lower_TernaryExpr` used to lower `a if cond else b` by unconditionally
emitting code for *both* `then_val` and `else_val`, then selecting between
the two already-computed results — a correctness bug for any branch with a
side effect (I/O, a function call), not just waste. Found via
`sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1]).read()` reading
stdin unconditionally even when a file argv was given. Now emits a real
branch (two basic blocks + a merge label) and only evaluates the taken side;
the merged result type is determined via `_quick_type` on both branches
(estimates a C type without emitting code — the same "look, don't run"
contract used for list/tuple literal element-type inference) so the shared
result temp can be declared before either branch runs. Verified with a test
program: only the taken branch's `print()` fires.

`and`/`or` (`_lower_BinaryOp`) had the identical eager-both-operands shape;
fixed the same way (real branch, only the taken side evaluated) in both the
interpreter (`eval_BinaryOp`) and the compiled path (`_lower_binary`) —
verified with `x = f() or g()`, where `g()` no longer runs once `f()` is
truthy.

### Struct reflection no longer collides across same-named classes in different modules

`struct_field_types` (`gen_module`, `gimple_codegen.py`) is scanned once per
self-hosted closure across every transitively-imported module, keyed by bare
class name — but that scan *merged* fields from every `StructDef` node found
under a given name into one shared entry, rather than treating a same-named
`StructDef` from an unrelated module as a distinct class. `mojo_compiler.py`
and `ast_nodes.py` (reachable via `myinterpreter.py`'s import, which uses
`ast_nodes` only for method-parameter type annotations, never actually
instantiating its classes) both define their own unrelated `FunctionDef`
(and `ExprStmt`, `StringLiteral`, `CallExpr`, …) dataclasses with different
field layouts. Since `_struct_type_id` (the runtime dispatch tag for
`getattr()`/`setattr()`/`dataclasses.fields()`/the field-by-field `repr()`
added earlier this session) hashes only the bare name, every real
`FunctionDef` instance — regardless of which module's shape it actually
is — got read through whichever definition's fields happened to merge in
last, corrupting field offsets. Reproduced independently via `repr(ast)` on
`hello.mojo`'s own trivial two-statement AST: `FunctionDef(...)` grew a
phantom `is_static` field (only `ast_nodes.py`'s `FunctionDef` has one).

Fixed by tracking, per struct name, the `id()` of the *first* `StructDef`
AST node whose fields were merged in (`_struct_name_owner`) — any later
`StructDef` with the same name but different node identity is skipped
entirely rather than having its fields merged in. This map has to be shared
across every `temp_gen` sub-compile the same way `struct_field_types`
itself already is: `do_imports`'s per-module recursion compiles each
imported module through its own `GimpleGen` instance, so a name claimed
while compiling one module must stay claimed when a different sub-compile
later reaches an unrelated same-named class in another module — a
call-local dict would reset per sub-compile and miss the collision.
Verified: `hello.mojo`'s self-hosted `repr(ast)` no longer has the phantom
`is_static` field. Not a complete fix for byte-identical `.ast` output
(fields typed generically as Python `object` are a separate, real,
currently-accepted limitation — see `PLAN.md`), but the specific
cross-module data corruption is gone. A full fix would give struct type IDs
module-qualified names instead of just the bare class name; not attempted
here (see `PLAN.md`).

### Real regex engine: `.finditer()` and compile-time-foldable `.sub()`

`re.Pattern.finditer()` had no codegen lowering at all — `for m in
pattern.finditer(s):` fell through to the "unsupported iterable" branch,
which silently dropped the entire loop body (zero iterations, no error, no
crash). `mojo_compiler.py`'s own `py_tokenize` uses exactly this pattern as
its core lexer loop, so the self-hosted, *compiled* tokenizer silently
produced an empty token stream for every input. This mattered beyond
diagnostics: `mojo --dump`'s main `.ci` generation routes through a
subprocess that runs the real *interpreted* tokenizer/parser, so
`make bootstrap`'s `verify` step gave no signal at all about whether the
self-hosted Parser/tokenizer actually *worked* when executed — only the
`.tok`/`.ast` diagnostic dump code calls the compiled `Parser`/`py_tokenize`
directly, in-process, which is exactly where this surfaced.

An interim step made the gap loud instead of silent:
`mojo_unsupported_iter(type_name)` prints a greppable diagnostic instead of
emitting nothing (deliberately not `abort()`, since this is a legitimate,
cataloged feature gap that `mojo.py`'s own dump handler wraps in
`try`/`except`, and `abort()`'s `SIGABRT` can't be caught at the Mojo level).

The real fix: `regex_compile.py` (new file) is a compile-time-only Python
regex parser/emitter — a backtracking NFA over a flat node array
(char/any/class/concat/alt/group/repeat, greedy and non-greedy, named
groups, `{m,n}`). `runtime/mojo_runtime.c`'s `mojo_regex_search`/
`mojo_regex_lastgroup`/`mojo_regex_substr` walk it at runtime via an
explicit continuation-list struct (no closures — GIMPLE has none).
`_gen_for_regex_iter` (`gimple_codegen.py`) wires `for m in
<pattern>.finditer(text):` to it. Validated by comparing the self-hosted
tokenizer's token stream against real Python's on real source files.

Making tokenization *actually run* for the first time immediately surfaced a
cascade of previously-unreachable bugs elsewhere in the self-hosted closure
— none specific to regex, just never exercised until real input reached the
Parser:

- `strcmp` on a genuine NULL `char *` (a `str = None` default parameter)
  segfaulted — fixed with a null-safe `mojo_cstr_cmp`.
- This codegen's `and`/`or`/ternary never short-circuit (both operands
  always evaluate). Two of `mojo_compiler.py`'s own guards relied on
  short-circuiting to protect indexing/attribute-access on empty strings or
  non-`IdentExpr` nodes; fixed by rewriting as explicit nested `if`s.
- A struct method's varargs-packing sentinel (`func_param_types[mangled]`
  ending in `'...'`) gets overwritten with the method's concrete C signature
  once its body is emitted (needed so forward declarations match), silently
  disabling `*args` packing for every call site compiled afterward —
  `self._is_kw("as")` cast a raw string pointer straight to `MojoList *` and
  segfaulted in `mojo_list_contains_str`. Fixed by preferring
  `_mangled_signature_ctypes`'s untouched sentinel copy in `_emit_call`.
- Tuple-unpack assignments (`a, b = x[:n], x[n:]`) never ran the "remember
  the real pointer type behind this int64_t-boxed local" logic that plain
  assignments do — a sliced string got misread as `MojoList *` by
  `len()`/indexing, crashing across every test/stdlib file once the parser
  genuinely ran on them. Fixed via a shared `_track_pointer_actual_type`
  helper used by both assignment paths, plus the same missing check in
  `_lower_builtin_len`/`_lower_subscript`.
- `ord()`/`chr()` were dead variadic stubs with zero real implementation.
- `mojo_compiler.py`'s raw/byte-prefixed string literals (`r'...'`,
  `b'...'`) never had their prefix stripped, only their quotes — general,
  pre-existing, highest-impact for `_TOKEN_RE` itself since
  `_TOKEN_RE = re.compile(r'...')` is *itself* an r-string.

**Follow-on fix**: `re.sub()` still used POSIX `regcomp`/`regexec`
(`mojo_re_sub_fn`) — a different re operation from `.finditer()`, needing
its own fix. `mojo_compiler.py`'s own `replace_multiline_strings` (hides
multi-line triple-quoted strings *before* line-based tokenization) calls
`re.sub()` with `\s`/`\S`/non-greedy `*?`, none of which POSIX ERE supports;
`regcomp` failed and `mojo_re_sub_fn`'s "compile failed → return input
unchanged" fallback made the substitution a silent no-op, so a module
docstring got split into physical lines and mis-tokenized one line at a
time — reaching a bare-annotation parse path with a non-`IdentExpr` node
that (via the ternary-eager-eval bug, fixed above) called `mojo_obj_getattr`
and aborted (this was the `example_imports.mojo` crash). Fixed by adding
compile-time constant-folding (`_try_const_fold_str`, handles literal
concatenation/repetition and already-folded locals like `_dq = '"' * 3`) so
a foldable `re.sub()` pattern routes through the same regex engine via a new
`mojo_regex_sub_fn`, falling back to the POSIX path for anything the engine
doesn't support (e.g. lookahead `(?=...)`, found in a *different*
`gimple_codegen.py` pattern during this fix). Also fixed an incidental bug
where `_regex_progs_defined` could get permanently poisoned — marked
"already emitted" for patterns whose emitting compile attempt later failed
and got rolled back by an ancestor module's exception handler — silently
dropping other, unrelated modules' regex array declarations file-wide.

Also fixed the same eager-ternary-evaluation shape directly in
`mojo_compiler.py`'s own bare-annotation and bracket-subscript-keyword-arg
parsing (`expr.name if isinstance(expr, IdentExpr) else None` was calling
`.name` unconditionally).

Not yet done: `.findall()`/`.split()` still have no lowering; `re` flags
still aren't honored by either regex backend; see `PLAN.md`.

### `re.sub(pattern, repl, src)` fixed for a plain replacement string, not just a callback

Real Python's `re.sub` accepts either a callback *or* a plain replacement
string as its second argument, but this codegen's `re.sub()` lowering
(both the POSIX `mojo_re_sub_fn` path and the new engine-backed
`mojo_regex_sub_fn` path above) always assumed a callback: a plain
replacement string got cast straight to a function pointer and then
*called* — a `SIGILL` calling the string's own bytes as machine code.
Confirmed via `monomorphize.py`'s own `safe_suffix`
(`re.sub(r'[^A-Za-z0-9_]', '_', s)`) and `monomorphize_source`
(`re.sub(rf'\b{re.escape(tp)}\b', str(concrete), src)`), both real,
exercised logic — reproduced directly with a minimal test program
(`SIGILL`, exit 132) and verified the fix produces output matching real
Python exactly. This is a pre-existing bug, not introduced by the
`.finditer()`/`re.sub()` work above (the callback-resolution logic was
only extracted into a shared helper, `_lower_re_sub_callback`, not
changed) — `safe_suffix`'s pattern just newly reaches the real engine
(being compile-time-foldable) instead of silently no-opping via the old
POSIX path, which is what surfaced it.

Fixed by adding `_re_sub_repl_is_callback(cb_arg)`: in this restricted
codegen, the only way to reference "a function" is by a bare,
undeclared name (a closure tracked in `_closure_envs`, or a plain
top-level `def` name) — a bare identifier that's already a known local
or global *variable* can't be one, which is the tell used to distinguish
the two `re.sub()` forms. The string-replacement form now routes through
two new runtime functions mirroring the callback ones minus the callback
machinery: `mojo_re_sub_str` (POSIX) and `mojo_regex_sub_str`
(engine-backed) — both a straightforward find/replace loop appending the
literal replacement string. No backreference support (`\1` etc. in
`repl`), since nothing in this codebase's actual usage needs it.

**Found but not fixed while investigating this: `re.search()`/`re.match()`
have zero real implementation as expressions** — a `re`/pattern receiver
is typed as a plain scalar, so `re.search(pat, s)` falls through
`_lower_method_call`'s generic "unknown method on a scalar receiver"
fallback and silently returns the *receiver's own value* unchanged
(diagnosable via `MOJO_DEBUG=1`, but not caught by `-fsyntax-only`, so
`compile_stdlib.py`'s 647/647 doesn't catch it either). Confirmed via
`monomorphize.py`'s `compile_fn`, whose `m = re.search(...)` /
`name = m.group(1)` compiles to `m = re;` / `name = (char *)m;` — a
wild-pointer read, not the captured text. See `PLAN.md` — this is a real,
standalone feature (a genuine Match-or-None representation), not a quick
patch, so left there rather than attempted alongside the `re.sub()` fix.

### `compile_stdlib.py` reaches 595/0 — every stdlib file compiles

Last of the original 3 failures (`test_unsafe_pointer_v2.mojo`,
`test_string_slice.mojo`, `test_span.mojo`) fixed. Root causes (none touched
`_lower_binary`'s `_is_raw_ptr` dispatch, despite an earlier same-day attempt
along that path regressing 3 other files and being reverted):

- `_lower_slice`'s `Span *` `_len` computation mixed an uncast integer
  literal with an int64_t temp when the stop bound was a bare literal.
- `_mojo_type`'s `UnsafePointer[X, Origin]` branch passed the entire
  multi-arg bracket interior to the recursive element-type lookup, silently
  defaulting to `int64_t` — added `_split_top_level_commas`.
- `_resolve_type` learned to resolve a bracket's element against
  `struct_field_types` too, so `UnsafePointer[MoveOnly_Int,
  MutExternalOrigin]` resolves to `MoveOnly_Int *` instead of falling
  through to `int64_t`. Guarded so `_TYPE_MAP` scalar newtypes still win.
- `_gen_stmt_MultiAssignStmt`'s subscript-write case had no raw-pointer
  branch (only `_gen_stmt_AugAssignStmt`'s did); `_lower_pointer_method`'s
  `init_pointee_*` methods assumed the pointee was always scalar. Both
  fixed to match their already-correct sibling patterns.
- Nested generic-struct type arguments (`alloc[MoveOnly[Int]]`) needed
  pre-elaborating the inner generic and re-deriving the outer generic's
  return type via `_resolve_type`. This required making
  `_imported_generic_structs` actually get populated for the first time (it
  had been entirely dead code — the only writer was gated behind a flag
  `compile_stdlib.py` never sets), via a new
  `_register_imported_generic_structs`. That exposed two more dormant bugs
  in the never-before-exercised `_elaborate_generic_struct_call` path: no
  concreteness check on type args (self-referential generics got wrongly
  monomorphized against an unbound placeholder), and no signature-aware
  method mangling (overloaded methods produced conflicting `extern`
  declarations). Both fixed by aborting elaboration on either condition,
  falling back to whatever path already handled that struct before.
- `Span`'s own subscript gained the same `_elem_types` side-table tracking
  `MojoList *` already has.

### Smaller fixes

- **`_TYPE_MAP` vs `ABI.md` divergence**: already matched (`Int → int64_t`,
  `Bool → _Bool`); stale discrepancy comment removed.
- **`fix_gimple_*.py` post-processing scripts removed as legacy** — the
  codegen now emits proper GIMPLE directly (`_emit_call` loads globals/
  literals into temps, casts in call args extracted to temps, struct
  typedefs ordered before forward declarations).
- **Struct method extern-stub guard collision**: the `#ifndef` guard for an
  unknown struct method's variadic stub now uses
  `_MOJO_STUB_{struct}_{method}` (upper-cased) consistently, avoiding
  collisions between names differing only in case.
- **`try` body ending in `return` used to skip `finally` entirely** — return
  statements in a `try` body are now intercepted to jump to `finally` first,
  then execute the return after cleanup.
- **GIMPLE `setjmp` address computation** used invalid `&_array[idx]`
  syntax — now uses `(void *)&_mojo_exc_stack[idx]`, which compiles.
- **`MOJO_STDLIB` env var is now optional** — `module_loader.py`/
  `module_spec_gen.py` hardcode the real modular stdlib checkout path
  directly.
- **`stdlib/lexer.mojo`'s `tokenize` signature mismatch fixed** —
  `runtime/mojo_runtime.h` now declares `int64_t tokenize(char *)` matching
  the frozen stdlib lexer, instead of `MojoList *tokenize(char *)`.

---

## Architecture

The Mojo reference implementation consists of:

| File | Role | How generated |
|---|---|---|
| `mojo_compiler.py` | Lexer, parser, and AST | Generated by `compiler_gen.py` from `.md` specs via `python run.py` |
| `generated_dispatch.py` | Operator/type/dispatch tables for GIMPLE backend | Generated by `gimple_spec_gen.py` from `GNU-EXTENSIONS.md` + `gimple-type-system.md` via `python run.py` |
| `gimple_codegen.py` | Lowers AST to C with `__GIMPLE` annotations | Hand-written; imports from `generated_dispatch.py` |
| `module_loader.py` | Resolves and loads `.mojo` modules | Generated by `module_spec_gen.py` from `GNU-EXTENSIONS.md` |
| `test_gimple.py` | 142-test unit suite for the GIMPLE backend | Hand-written |
| `compile_stdlib.py` | Batch-transpiles the whole stdlib tree (643 files across `benchmarks`/`std`/`test`/`tools`); `--roots`/`--module` to narrow | Hand-written |

**Build**: `python run.py` regenerates both `mojo_compiler.py` and `generated_dispatch.py` from their respective specs in one step.

**Spec files**: `.md` files define language semantics. Key files: `mojo-operators.md`, `mojo-simple-statements.md`, `mojo-expressions.md`, `mojo-function-declarations.md`, `mojo-manual-*.md`, `GNU-EXTENSIONS.md` (GIMPLE lowering rules), `gimple-type-system.md` (type lattice), and the seven `gimple-*.md` specification files.

---

## CLI Frontend

The Mojo CLI (`build/mojo`) provides upstream-compatible command interface:

| Command | Description |
|---------|-------------|
| `mojo repl` | Interactive REPL with Python-compatible eval/exec |
| `mojo run <file.mojo>` | Compile and execute a Mojo file |
| `mojo <file.mojo>` | Shorthand for `mojo run` |
| `mojo build <file.mojo> -o <output>` | Compile to ELF executable |
| `mojo compile <file.mojo>` | Compile to object file (sets `-o` to basename) |
| `mojo --help` / `-h` | Display usage information |
| `mojo --version` / `-v` | Show version string |

**Implementation**: `build_mojo_cli.py` generates the CLI script at build time. The script wraps `gimple_codegen.py` to compile Mojo source to C with `__GIMPLE` annotations, then uses system `gcc` (or `gcc-mp-15` on macOS) to link and execute.

---

## Layout Rules

The tokenizer implements all four layout rules:

- **Indentation** — 4 spaces per level; produces `INDENT`/`DEDENT` tokens that drive block scope.
- **Line continuation** — a physical line ending with `\` is joined to the next line before lexing; the pair counts as one logical line.
- **Semicolons** — `;` separates multiple statements on one physical line; each segment emits its own `NEWLINE` token.
- **Comments** — `#` to end of line is stripped before lexing (full-line and inline); the tokenizer also skips entirely blank lines.

---

## Literals

- **Integer**: decimal, hex (`0x`/`0X`), octal (`0o`/`0O`), binary (`0b`/`0B`)
- **Float**: standard, scientific notation, leading-dot
- **Boolean**: `True`, `False`
- **None**: `None`
- **Self**: `Self`
- **String**: single/double/triple-quoted
- **Ellipsis**: `...` (three consecutive DOT tokens → `EllipsisLiteral` → emits `...`)

Source: `mojo-literals.md`

---

## Expression Operators

Full 15-level precedence table including:
- Arithmetic: `+`, `-`, `*`, `/`, `//`, `%`, `**`
- Bitwise: `&`, `|`, `^`, `~`, `<<`, `>>`
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Logical: `and`, `or`, `not`
- Membership: `in`, `not in`
- Identity: `is`, `is not`
- Augmented assignment: `+=`, `-=`, `*=`, `/=`, `//=`, `%=`, `**=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `@=`
- Unpacking operators:
  - `*args` — positional unpacking in function calls and subscripts
  - `**kwargs` — dictionary unpacking in function calls (e.g., `func(a, **options)`)

Source: `mojo-operators.md`

---

## Expressions

- List literals `[1, 2, 3]`
- Dict literals `{"k": v}`
- Set literals `{1, 2}`
- Tuple literals `(1,)`
- Member access `obj.field`
- Subscript `a[i]`, chained subscripts `Type[A=Int][B=Float]`
- Slices, including step and multi-dimensional forms: `a[i:j]`, `a[::2]`,
  `a[1:-1:1]`, `a[::-1]`, `a[0:2, ::]`, `a[:, 0]` (unified `_parse_subscript_item`)
- Function calls with unpacking: `func(*args)`, `func(**kwargs)`
- Subscript unpacking: `Type[*Ts]`, `expr[*indices]`
- Function types in type position: `def(...) thin abi("C") raises -> T`
- Ternary `x if cond else y`
- List/set/dict comprehensions, including multiple `for` clauses
  (`{a*b for a in xs for b in ys}`)
- Template strings `t"..."` (single-level)
- Walrus `:=`
- Call expressions

Source: `mojo-expressions.md`

---

## Simple Statements

| Statement | Python output |
|---|---|
| `return [expr]` | `return [expr]` |
| `raise expr` | `raise expr` |
| `break` | `break` |
| `continue` | `continue` |
| `pass` | `pass` |
| `assert cond` | `assert cond` |

Source: `mojo-simple-statements.md`, `mojo-keywords.md`

---

## Import Statements

- `import module`
- `import module as alias`
- `from module import name`
- `from module import name as alias`
- `from module import *` (wildcard)

Source: `mojo-simple-statements.md`

---

## Assignment Statements

- `var name: Type = value` (declaration)
- `var a, b = expr` (tuple unpacking in var declaration)
- `name = value` (assignment)
- `a, b = expr` (tuple unpacking in assignment statement)
- `name op= value` (augmented assignment, all operators)
- Destructuring with multiple assignment targets

Source: `mojo-simple-statements.md`

---

## Control Flow

- `if` / `elif` / `else`
- `while` (with optional `else`)
- `for … in …` (with optional `else`)

Source: `mojo-compound-statements.md`

---

## Error Handling

- `try` / `except ExcType as e:` / `except:` / `else:` / `finally:`

Source: `mojo-compound-statements.md`

---

## Context Managers

- `with expr as alias:` / `with expr:` — alias may be a keyword (e.g. `as out`)

Source: `mojo-compound-statements.md`

---

## Compile-Time Control Flow

- `comptime if cond:` (emitted as `if cond:  # comptime`)
- `comptime if cond: ... elif other: ...` — elif clauses supported with full conditional chains
- `comptime for x in iter:` (emitted as `for x in iter:  # comptime`)
- `comptime for a, b in iter:` — tuple targets and convention-keyword prefixes
- `comptime assert expr` → `assert expr`
- `comptime assert expr, "msg"` → `assert expr, "msg"`
- `comptime NAME = expr` → `NAME = expr`

Source: `mojo-compound-statements.md`

---

## Functions

- `def name(params) -> RetType:` — standard function definition
- `fn name(params) -> RetType:` — alternative keyword for function definition (Mojo-specific)
- `def name(params):` — no return type
- Optional `raises` keyword (stripped, not emitted)
- `@staticmethod` decorator
- Keyword-only parameters: `*` separator followed by optional convention keywords and parameter name
  - Example: `def func(a, *, var x: Int, mut y: Int)` — params after `*` are keyword-only
  - Convention keywords (`var`, `mut`, `ref`, `out`, `read`, `deinit`) recognized after `*` separator
  - Parsed and stripped in Python output; GIMPLE backend uses for `const` qualifiers
- Argument-convention prefixes (`read`, `mut`, `var`, `ref`, `out`, `deinit`) — retained in `FunctionDef.param_convs` dict; **stripped from Python output** (invalid Python syntax); GIMPLE backend uses them for `const` qualifiers
- Generic `[T, ...]` type-parameter blocks — skipped by `_skip_bracketed()` in parser; not emitted
- Default parameter values — parsed and dropped (only positional params in output)
- Transfer operator `^` — postfix ownership transfer operator (e.g., `return x^`, `y = z^`) recognized and skipped in codegen
- `where` clauses — parsed and skipped
- Chained subscripts in type annotations: `Type[A=Int][B=Float]` — multiple consecutive bracket blocks in type annotations are fully consumed
- Type unpacking in parameters: `def foo(*args: *Ts)` — unpacking syntax in type annotations recognized

Source: `mojo-function-declarations.md`, `mojo-manual-values.md`

---

## Structs → Python Classes

- `struct Name:` / `class Name:` — both keywords supported for class definition
- `struct Name[T]:` / `class Name[T]:` — with generic type parameters
- `struct Name(Trait1, Trait2):` / `class Name(Trait1, Trait2):` — with trait inheritance
- `@fieldwise_init` decorator → auto-generates `__init__(self, field1, field2, ...)` from `var` fields
- Methods emitted as regular `def` methods under the class
- Generic type params `[T]` stripped from struct name
- Argument-convention prefixes stripped from method params

Source: `mojo-struct-definition.md`, `mojo-manual-values.md`

---

## Traits → Abstract Base Classes

- `trait Name:` → `class Name:  # trait` (with `from abc import abstractmethod` in header)
- Methods with `...` or `pass` body → decorated with `@abstractmethod`
- Concrete trait methods emitted as regular `def`

Source: `mojo-trait-definition.md`

---

## Pointer Type Stubs

`OwnedPointer`, `ArcPointer`, `Pointer`, `UnsafePointer` emitted as stub Python
classes with `__getitem__`/`__setitem__` forwarding to an inner `_value`.

Source: `mojo-manual-pointers.md`

---

## Reflection API Stubs

`struct_field_count[T]()`, `struct_field_names[T]()`, `struct_field_types[T]()`,
`__struct_field_ref()`, `conforms_to()`, `trait_downcast()` — all emitted as
stub Python functions returning sensible defaults.

Source: `mojo-manual-reflection.md`

---

## `Layout` / `LayoutTensor` Stubs

`Layout` and `LayoutTensor` emitted as stub classes with `row_major()`, `col_major()`,
`tile()`, `__getitem__`, `__setitem__`. Real multi-dimensional indexing semantics
are not translatable to pure Python.

Source: `mojo-manual-gpu.md`

---

## Python Interop Stubs

`_python_import(name)` helper emitted using `importlib.import_module`.

Source: `mojo-manual-python.md`

---

## Testing Framework Stubs

The following are emitted as runnable Python functions:

- `assert_equal(a, b, msg="")`
- `assert_true(v, msg="")`
- `assert_false(v, msg="")`
- `assert_not_equal(a, b, msg="")`
- `assert_almost_equal(a, b, atol=1e-6, msg="")`
- `assert_raises(contains="")` — context manager
- `TestSuite` — stub class with `discover_tests()` / `run()`

Source: `mojo-tools-and-faq.md`

---

## GPU Stubs

Stub classes emitted for `DeviceContext`, `DeviceBuffer`, `HostBuffer` with
`# TODO` comments indicating full GPU codegen is deferred.

Source: `mojo-manual-gpu.md`

---

## Special Syntax Forms

Parser support for Mojo special syntax forms:

### Extension Declarations

- `__extension Type: methods` — Declares additional methods on an existing type
- Parsed as statement-level construct with type name and method block
- Emitted as Python code within class body

### MLIR Operations — lowered to C/GIMPLE via `mlir.py`

The stdlib's builtin scalars are newtypes over MLIR builtin types
(`struct Int: var _mlir_value: __mlir_type.index`), and their methods are thin
wrappers over MLIR ops (`__mlir_op.\`index.add\``). We strip-mine those semantics
and replay them as plain C primitives so the *real* library compiles. The whole
MLIR surface used across the stdlib (~130 distinct opcodes) is classified, in one
pass, in **`mlir.py`** — table-driven, dialects-as-data.

- **`__mlir_type.<t>`** → C type via `mlir.type_to_c` (`index`/`iN`/`uiN`/`fN` →
  C scalars; `!kgen.string` → `char *`; `!llvm.ptr*`/`!kgen.pointer<…>` → C
  pointers). Hooked in `_mojo_type`.
- **`__mlir_attr.\`…\``** → `mlir.parse_attr`: typed int (`0 : index` → `0`),
  scalar-simd constant (`#kgen.simd<7>` → `7`), or comparison predicate
  (`#index<cmp_predicate slt>` / `#kgen<cmp_pred ne>`). Constants lower in
  `_lower_MemberExpr`; predicates are read at the op call site.
- **`__mlir_op.\`dialect.op\`[attrs](args)`** → `mlir.lower_op` /
  `_maybe_lower_mlir_op`. Lowered now: `index`/`pop`/`arith` arithmetic,
  min/max, unary math, `fma`/`select`, all compares (predicate from `[…]` attrs),
  the cast/bitcast family, ownership/ref no-ops, and the memory/lvalue ops
  (`pop.load` → `*p`, `pop.store` → `*p = v`, `pop.offset`/`pop.array.gep` →
  `_mojo_at_` helper). The `[name=value]` op params survive parsing via
  `SubscriptExpr.attrs`.
- **Deferred (explicit, with a reason via `mlir.deferral_reason`)**: GPU
  (`nvvm.*`/`rocdl.*` — see `METAL.md`), coroutines (`co.*`), atomics, true
  vector SIMD, allocation/symbols, and compiler-internal `kgen`/`variant`/struct
  GEP. The codegen emits an honest `/* mlir …: deferred: <reason> */` stub.
- **Parser**: a bare `__mlir_op` statement is a real side-effecting op (e.g.
  `pop.store`) and parses as an expression statement so the backend lowers it.
  `__mlir_region` (region decl) and `__mlir_attr`/`__mlir_type` bare statements
  remain opaque no-ops.

---

## GIMPLE Specification & Code Generation

### Complete GIMPLE Specifications

Seven comprehensive GIMPLE lowering specifications created (700+ lines):

- **gimple-type-system.md** — Type lattice, promotion rules, rank system, type inference
- **gimple-runtime.md** — Container/exception/string/memory APIs (~140 functions documented)
- **gimple-exceptions.md** — Try/except/finally lowering, exception context stack
- **gimple-closures.md** — Nested function capture analysis, lifting, environment structs
- **gimple-iterators.md** — Range/container/struct iterator protocols, for-loop lowering
- **gimple-memory.md** — Pointer operations, UnsafePointer, pointer dereferencing helpers
- **gimple-generics.md** — Generic type parameter handling, monomorphization strategy

### Spec-Driven Code Generation (gimple_spec_gen.py)

**Extraction Capabilities** (from GNU-EXTENSIONS.md and gimple-type-system.md):

- **Operators**: 23 operators extracted (binary arithmetic, comparison, logical, bitwise, unary, augmented)
- **Statements**: 9 statement types (variable declaration, assignment, if, while, for, return, try/except, raise, comprehensions)
- **Expressions**: 7 expression types (literals, collections, subscript, member access, calls, ternary, walrus)
- **Type System**: 13 types with complete rank mappings (signed/unsigned integers, floats)

**Code Generation Output**:

- Operator dispatch tables (`_BINARY_OPS`, `_UNARY_OPS`, `_AUGMENTED_OPS`)
- Type promotion code (`_SIGNED`, `_UNSIGNED`, `_FLOAT` rank tables)
- Statement dispatch mapping (`_STATEMENT_HANDLERS`)
- Expression dispatch mapping (`_EXPRESSION_HANDLERS`)

**Usage**:
```bash
python gimple_spec_gen.py --generate all           # Generate all dispatch code
python gimple_spec_gen.py --show-stats             # Show extraction statistics
python gimple_spec_gen.py --show-structure         # Show code generation structure
```

**Integration Status**: ✅ Complete

`gimple_spec_gen.py` generates `generated_dispatch.py`, which `gimple_codegen.py` imports directly. No duplicate hardcoded tables remain.

| Table | Source spec | Lines saved |
|---|---|---|
| `_SIGNED`, `_UNSIGNED`, `_FLOAT` | `gimple-type-system.md` | 3 |
| `_BIN_OPS`, `_CMP_OPS` | `GNU-EXTENSIONS.md` | 15 |
| `_STMT_DISPATCH` | gimple_spec_gen.py (21 entries) | 23 |
| `_EXPR_DISPATCH` | gimple_spec_gen.py (19 entries) | 21 |

`gen_stmt()` and `lower_expr()` now dispatch via dict lookup to `_gen_stmt_*` and `_lower_*` handler methods — one method per AST node type. Adding a new statement or expression handler requires only: (1) add method, (2) add entry to the appropriate dispatch table in `gimple_spec_gen.py`, (3) regenerate with `python run.py`.

**Regeneration**: `python run.py` regenerates both `mojo_compiler.py` and `generated_dispatch.py` in one step.

Note: Hand-written portion includes variable type inference, memory management helpers, closure environment handling, module initialization, and runtime function declarations — logic-heavy components that are difficult to specify declaratively.

---

### GIMPLE Codegen Implementation

Mojo → GIMPLE C backend (`gimple_codegen.py`).  
Compile with `/opt/local/bin/gcc-mp-15 -fgimple`.  Test with `make check-gimple` (142 tests).

### Core

- Function definitions (`def`) with typed params and return type
- Variable declarations (`var x: T = val`)
- Simple assignments (`x = expr`)
- Multi-target assignment (`a = b = expr`) → `MultiAssignStmt`
- Augmented assignment (`x += expr`, `x -= expr`, `x //= expr`, `x **= expr`, etc.) — type-promotion via `TypeLattice.join` so `int += int64_t` promotes both operands before the op
- Bare assignments without `var` (type inferred from RHS)
- Assignment to struct field (`obj.field = val`) and array element (`arr[i] = val`)
- **Argument conventions** (`read`/`mut`/`var`/`ref`/`out`/`deinit`) — retained in `FunctionDef.param_convs`; `read`/`ref` on pointer params emit `const T *` in both forward declaration and definition

---

### Expressions

- Integer, float, bool literals
- String literals (`char *`, no runtime ops)
- Arithmetic: `+ - * / % & | ^ << >>` — operands promoted to common type per `TypeLattice.join` before emit; no implicit `int + int64_t` mismatch in GIMPLE
- `**` operator: `pow()` for floats; `(int) pow((double) a, (double) b)` for ints
- `//` floor division: `__mojo_floordiv()` helper for ints; `__builtin_floor(a/b)` for floats
- Comparison: `== != < <= > >=` → `_Bool` result
- **`is` / `is not`** → pointer identity (`void *` cast + `==` / `!=`) for reference types; value `==`/`!=` for scalars
- **`MojoStr ==` / `!=`** → `mojo_str_eq()` + `!= 0` / `== 0`
- Logical: `and or` → `&& ||`
- Unary: `- ~` and `not` (lowered to `== 0`)
- Ternary expression (`x if c else y`)
- **Walrus expression** `(x := expr)` → assign and return same variable; complex LHS: `obj.field := expr` stores via `->` / `.`; `lst[i] := expr` / `p[i] := expr` dispatches to `mojo_list_set_*` or raw pointer write
- Function calls with return-type inference (symbol table pre-pass + runtime table)
- Struct field read via `MemberExpr` → `obj.field` or `obj->field`
- Array/pointer element read via `SubscriptExpr` → `_mojo_at_T(p, i)` + `*addr` for plain pointers (pointer arithmetic forbidden in `__GIMPLE`); `mojo_list_get_int/double/str` for `MojoList *`; `mojo_str_char_at` for `MojoStr *`; `mojo_dict_get_int/double/str` for `MojoDict *` (value type tracked per variable)
- **`len(x)`** built-in dispatch → `mojo_str_len` / `mojo_list_len` / `mojo_dict_len` / `mojo_set_len` based on argument type
- `x in range(n)` / `x in range(a, b)` → comparison chain with `_Bool & _Bool`
- `x not in range(n)` / `x not in range(a, b)` → negated comparison chain
- **List literals** `[a, b, c]` → `mojo_list_new()` + `mojo_list_append_*()` calls
- **Dict literals** `{k: v, ...}` → `mojo_dict_new()` + `mojo_dict_set_*()` calls
- **Set literals** `{a, b, c}` → `mojo_set_new()` + `mojo_set_add_*()` calls
- **Tuple literals** `(a, b, c)` → lowered as `MojoList *`
- `x in list_var` / `x not in list_var` → `mojo_list_contains_*()`
- `k in dict_var` / `k not in dict_var` → `mojo_dict_contains()`
- `x in set_var` / `x not in set_var` → `mojo_set_contains_*()`
- **List comprehensions** `[expr for x in range/list/str/dict/set]`
- **Set comprehensions** `{expr for x in range/list/str/dict/set}`
- **Dict comprehensions** `{k: v for x in range/list/str/dict/set}`
- **`MojoList + MojoList`** → `mojo_list_concat(a, b)` with elem-type propagation
- **`SliceExpr`** on `MojoStr *` → `mojo_str_slice`; on `MojoList *` → `mojo_list_slice`; on plain pointer → pointer offset
- **`@` matrix multiply operator** → calls `StructName___matmul__(left, right)` method; TODO for high-performance BLAS/SIMD implementation

---

### Statements

- `return` (with and without value) — return-type coercion emits to a temp before `return tmp` (GIMPLE forbids cast in return)
- `if / elif / else` → basic block + goto lowering
- `while` loop → basic block + goto lowering
- `for i in range(n/a,b/a,b,s)` → while loop with `bb_post` increment block
- `for i in range(a, b, step)` with non-literal step → ternary condition on step sign
- **`for x in list_var`** → MojoList iteration with int cast at API boundary
- **`for c in str_var`** → MojoStr char iteration via `mojo_str_char_at`
- **`for k in dict_var`** → `MojoDictIter` (new/next/key/free); key assigned via `const char *` temp to avoid cast-on-call-result in GIMPLE
- **`for x in set_var`** → `MojoSetIter` (new/next/val_int/free)
- **`try / else`** body → runs on clean try exit
- **`try / except ExcType as name`** → `name` bound to `mojo_exc_msg_get()` on exception entry
- **`raise "msg"`** → `mojo_exc_msg_set(msg)` before `mojo_raise()`
- **Multi-target assignment** (`a = b = x`) — targets may be `IdentExpr`, `MemberExpr`, or `SubscriptExpr`
- `break` / `continue` (with loop stack tracking)
- Nested loops (loop stack)
- `pass` statement (no-op)
- `assert expr` / **`assert expr, msg`** → conditional `__builtin_trap`; message printed via `puts`/`printf` before trap
- `print(...)` → `printf` with format-string dispatch per argument type
- Expression statement (call for side-effects)
- **`raise`** (bare) → `mojo_raise()` runtime call
- **`try / except / finally`** → `mojo_try_push()` / `mojo_exc_pop()` / basic block lowering
- **`with expr as alias`** → exception-safe: calls `__enter__`, pushes exc frame, calls `__exit__` on both normal and exception paths via `mojo_try_push`/`mojo_exc_pop`/`mojo_raise`
- **Struct definitions** → emits C `typedef struct { ... } Name;` + method functions (mangled `Name_method`)
- **Struct constructors** `TypeName(arg1, arg2)` → calls `_alloc_TypeName()` helper (emitted in preamble); `sizeof(T)` inside `__GIMPLE` is only valid when `T` appears in the function signature, so allocation is delegated to a `__GIMPLE` helper whose return type is `TypeName *`
- **Struct type resolution** — user-defined struct names → `StructName *`; field access via `->` with type lookup
- **Trait definitions** → emits `typedef struct Name_vtable { ret (*method)(params); ... } Name_vtable;`
- **Return type coercion** — `return` casts via intermediate temp (not inline cast) when declared type differs from expr type
- **Closures / nested functions** — upvar capture pre-pass (`_used_idents_node` / `_declared_vars_body`) computes free variables; env struct typedef + `_alloc_EnvName()` helper emitted before outer function; inner function lifted to top level as `outer_inner(EnvName *_env, ...)` reading captures via `_env->name`; call sites rewritten to pass the env pointer; `ClosureInfo` records per-closure metadata
- **Arbitrary iterator protocol** — `for x in obj` where obj is a struct with `__iter__` / `__has_next__` / `__next__` methods: creates iterator via `__iter__`, loops with `__has_next__` as condition, advances with `__next__`; also works in comprehensions
- **`UnsafePointer[T]` method calls** — `.load()` → `*p`; `.store(v)` → `*p = v`; `.offset(n)` → `_mojo_at_T(p, (int64_t)n)` helper; `.free()` → `free(p)`; `.initialize_pointee(v)` → `*p = v`
- **`UnsafePointer[T]` type resolution** — `_mojo_type("UnsafePointer[Int]")` → `int64_t *`; `OwnedPointer`/`ArcPointer`/`Pointer` all resolve similarly
- **Dict value type dispatch** — `_dict_val_types` dict tracks value C type per dict variable from first literal pair; `d[k]` dispatches to `mojo_dict_get_int/double/str` accordingly; type propagated through assignments
- **Generic `[T]` type params** — `_skip_bracketed()` in parser skips `[T, ...]` blocks; GIMPLE backend uses concrete type inference naturally (monomorphic output)
- **Struct method calls** `obj.method(args)` — `_lower_method_call` detects `MemberExpr` func; dispatches to raw-pointer ops for `UnsafePointer` types or to mangled name `StructName_method(self, args)` for user-defined struct methods
- **`comptime if`** — condition evaluated at codegen time via `_eval_const_bool`; only the live branch is emitted, dead branch is dropped entirely; falls back to a regular `if` when condition is not a compile-time constant
- **`comptime for`** — `range(...)` with all-literal arguments is fully unrolled: body emitted N times with loop variable set to each concrete value; zero loop overhead in generated GIMPLE; skipped with a comment if iterable is not constant
- **`from module import name`** — module_loader.py resolves `.mojo` files and extracts function signatures; extern declarations emitted in C preamble: `extern RetType name (void);`; supports stdlib modules (`std.X`) and local test modules

---

### Type System

### TypeLattice
C11 usual arithmetic conversion rules encoded as a lattice join:

| Tier | Types |
|---|---|
| Signed int | `int8_t` < `int16_t` < `int32_t`/`int` < `int64_t` |
| Unsigned int | `uint8_t` < `uint16_t` < `uint32_t` < `uint64_t` |
| Float | `__fp16` < `float` < `double` |

- `join(signed, unsigned)` → unsigned at wider rank
- `join(int, float)` → float
- Mixed-type binary ops: both operands cast to `join(lt, rt)` before emit
- Mixed-type augmented assignment: same promotion before the op

### EscapeAnalyzer
Conservative escape analysis on function bodies:
- A struct variable "escapes" if it appears in: `ReturnStmt`, a call argument, or a container-store (list/dict/set append)
- Used by `LayoutSolver` to decide STACK vs HEAP

### LayoutSolver
Determines allocation strategy for struct constructor expressions:

| Condition | Strategy | Lowering |
|---|---|---|
| Function has `try` block | HEAP | `malloc(sizeof(T))` |
| Variable escapes | HEAP | `malloc(sizeof(T))` |
| Otherwise | STACK | `__builtin_alloca(sizeof(T))` |

### Container element type tracking
`_elem_types` dict maps container variable name → element C type:
- Set at list/tuple literal creation (`_infer_list_elem_type`)
- Propagated through assignment and `mojo_list_concat`
- Used to select `mojo_list_get_int/double/str` at subscript sites

`_dict_val_types` dict maps dict variable name → value C type:
- Set at dict literal creation from type of first value expression
- Propagated through assignment
- Used to select `mojo_dict_get_int/double/str` at subscript sites

### Return type inference
Pre-pass for unannotated functions:
- `_collect_return_types` recursively scans all `ReturnStmt` nodes
- `_quick_type` evaluates expression types without emitting code
- `TypeLattice.join_all` produces the LUB of all collected types

---

### Runtime (`runtime/`)

- `runtime/mojo_runtime.h` — type declarations and function prototypes
- `runtime/mojo_runtime.c` — implementations of all four runtime types + exception helpers
- `build/libmojo.dylib` — compiled shared library (built with `make build/libmojo.dylib`)

### Exception support
| Function | Description |
|---|---|
| `mojo_try_push()` | Increment exc stack, call `setjmp`; returns 0 normally, non-0 on exception |
| `mojo_exc_pop()` | Decrement exc stack |
| `mojo_raise()` | `longjmp` to current exc frame |
| `mojo_exc_msg_set(msg)` | Store string message before `mojo_raise()` |
| `mojo_exc_msg_get()` | Retrieve message in except handler (empty string if none) |

### MojoList
Dynamic array of `int64_t` slots.  Doubles stored as bit-casts; string pointers cast to `int64_t`.

| Function | Description |
|---|---|
| `mojo_list_new()` | Allocate empty list |
| `mojo_list_append_int/double/str()` | Append element |
| `mojo_list_get_int/double/str()` | Element access by index |
| `mojo_list_set_int/double/str()` | In-place element mutation |
| `mojo_list_slice(l, start, stop)` | Allocate sublist copy |
| `mojo_list_concat(a, b)` | Concatenate two lists |
| `mojo_list_len()` | Number of elements |
| `mojo_list_contains_int/double/str()` | Membership test |
| `mojo_list_print()` | Debug print |

### MojoStr
Heap-allocated string with explicit length.

| Function | Description |
|---|---|
| `mojo_str_new(s)` | Create from `char *` |
| `mojo_str_concat(a, b)` | Concatenate |
| `mojo_str_len/data/eq()` | Length / data / equality |
| `mojo_str_char_at(s, i)` | Character at index |
| `mojo_str_contains(h, needle)` | Substring check |
| `mojo_str_slice(s, start, stop)` | Allocate substring copy |
| `mojo_str_from_char(c)` | Allocate 1-char string |
| `mojo_str_repeat(s, n)` | Allocate n-times repeated string |
| `mojo_str_to_int(s)` | `atoll` wrapper |
| `mojo_str_to_float(s)` | `atof` wrapper |
| `mojo_str_print()` | Print without newline |

### MojoDict
Open-addressing hash map with `char *` keys and `int64_t` value slots.

| Function | Description |
|---|---|
| `mojo_dict_new()` | Allocate empty dict |
| `mojo_dict_set_int/double/str()` | Insert or update |
| `mojo_dict_get_int/double/str()` | Lookup (0/NULL if missing) |
| `mojo_dict_contains()` | Key membership test |
| `mojo_dict_len()` | Number of entries |
| `mojo_dict_iter_new/next/key/val_*/free()` | Forward iterator (no address-of) |
| `mojo_dict_print()` | Debug print |

### MojoSet
Open-addressing hash set over `int64_t` or `char *` values.

| Function | Description |
|---|---|
| `mojo_set_new()` | Allocate empty set |
| `mojo_set_add_int/str()` | Insert element |
| `mojo_set_contains_int/str()` | Membership test |
| `mojo_set_len()` | Number of elements |
| `mojo_set_iter_new/next/val_int/val_str/free()` | Forward iterator |
| `mojo_set_print()` | Debug print |

---

### Infrastructure

- All variable declarations hoisted before `bb_2:` (GIMPLE requirement)
- **Loop body frequency annotations** — every loop body basic block label carries a `/* count(guessed_local(N)) */` comment where `N = 10 ** nesting_depth`; covers `while`, `for range`, `for list/str/dict/set`, and struct iterator loops; nested loops naturally get higher counts (10, 100, …)
- 3-address lowering: nested expressions create `_tN` temporaries
- `_Bool` for all comparison/logical results; `_coerce()` for type mismatches
- Cast expressions always emitted to a temp (`_tN = (T)val`) before use as call argument or return value — GIMPLE forbids inline casts in those positions
- Type mapping: Int/Int8-64/UInt/UInt8-64/Float16/32/64/Bool/String/None/List/Dict/Set/Str → C types
- Forward declarations for all functions (enables mutual recursion) — include `const` qualifiers when param has `read`/`ref` convention to match definition
- C-keyword name mangling (`double` → `mojo_double`, etc.)
- `#include <stdint.h>`, `#include <stdlib.h>`, `#include <math.h>`, `#include <stdio.h>`, `#include <setjmp.h>`, `#include "mojo_runtime.h"`
- `static int __mojo_floordiv(a, b)` helper emitted in every file
- `_RUNTIME_FUNCS` table seeds `func_return_types` for known runtime call return-type inference
- **Pointer-at helpers** — `static T * _mojo_at_T(T *p, int64_t n) { return p + n; }` emitted in preamble for each elem type used; pointer arithmetic (`p+n`) and subscript (`p[i]`) are invalid in `__GIMPLE`, so all pointer offset/index operations call these helpers
- **Struct allocator helpers** — `StructName * __GIMPLE _alloc_StructName(void) { ... malloc(sizeof(StructName)) ... }` emitted in preamble for each struct constructed; `sizeof(T)` inside `__GIMPLE` requires `T` to appear in the function signature; delegating allocation to a dedicated `__GIMPLE` function whose return type is `StructName *` satisfies this constraint
- Two-phase generation: Phase 2a generates all function bodies (populating `_ptr_helpers_needed` and `_struct_allocs_needed`); Phase 2b assembles final output with helpers injected before the forward declarations
- Struct field type table (`struct_field_types`) populated from `StructDef` nodes in `gen_module()`
- `fe_reader.py`: `raise` value is now optional (bare `raise` parses correctly)

---

### Architecture

- `gimple_codegen.py` is a hand-written consumer of the AST from `mojo_compiler.py`
- `mojo_compiler.py` is generated by `compiler_gen.py` + spec `.md` files — never edited directly
- All variable declarations hoisted before first `bb_2:` label (GIMPLE requirement)
- Temps `_tN` declared at function top, assigned inline — valid non-SSA GIMPLE
- Loop stack tracks `(continue_bb, break_bb)` — for `for` loops, `continue_bb = bb_post` (runs increment)
- `_Bool` is the result type for all comparisons; cross-type assignments use `_coerce()`
- Negating a `_Bool` requires an intermediate `int` cast before comparing to `0`
- C-keyword conflicts resolved by prepending `mojo_` to the function name
- Runtime `contains_*` functions return `int`; codegen emits `int _ti = ...; _Bool t = _ti != 0;`
- Struct methods emitted as `StructName_methodName(StructName *self, ...)` with `__GIMPLE` annotation
- Exception helpers (`mojo_try_push/pop/raise`) live in the runtime to keep jmp_buf out of GIMPLE
- Dict/set iterators use opaque `MojoDictIter *`/`MojoSetIter *` structs returned by `iter_new`; `iter_key` returns `const char *` and must be assigned to a temp before casting to `char *`

---

### Non-obvious GIMPLE constraints

- Comparison results must be `_Bool`, not `int`
- `!` is not a valid GIMPLE operator — `not x` lowers to `x == 0`
- `&&` and `||` work in GIMPLE assignment context (confirmed)
- `_Bool == int(0)` is rejected — must cast to matching type first
- C cast syntax `(type)` not valid in comparison operand position or call argument position or return; valid only in assignment RHS
- Entry block must be `bb_2`; counter must start at 3 for subsequent blocks
- Function call result type in assignment must exactly match the function's declared return type
- Arithmetic between `int` and `int64_t` rejected — explicit casts required; `TypeLattice.join` determines the promotion type and both sides are cast before the op
- Global variable arithmetic (e.g., `_mojo_exc_top + 1`) must load to local first
- `(type) f(args)` (cast-of-call-result) in assignment RHS is invalid — must split into `tmp = f(args); var = (type) tmp;`
- `sizeof(TYPE)` inside a `__GIMPLE` function body is only valid when `TYPE` appears in the function's parameter or return type signature; workaround: emit a dedicated `_alloc_T(void) → T *` helper function so `sizeof(T)` is legal in its body

---

### Testing

```bash
make check-gimple          # build runtime + run all 142 tests
python test_gimple.py      # same, with verbose output on failure

# Manual inspection
python -c "
from gimple_codegen import compile_to_gimple
print(compile_to_gimple('''
def add(a: Int, b: Int) -> Int:
    return a + b
'''))
"

# Compile and dump lowered GIMPLE tree
/opt/local/bin/gcc-mp-15 -fgimple -O1 -fdump-tree-ssa-gimple -I runtime -c /tmp/test.c
```

---

## Completed Implementation Roadmap

### Priority 1 — Complete: Module System with Parameter Types

**Status**: ✅ All 142 GIMPLE tests + 7 execution tests + import tests passing

**Implemented**:
- ✅ Extended GNU-EXTENSIONS.md with detailed parameter type extraction specification
- ✅ Enhanced module_loader.py to extract function parameters from .mojo files
- ✅ Updated gimple_codegen.py to generate extern declarations with parameter types
- ✅ Type mapping: Mojo types → C types (Int→int, Float64→double, Bool→_Bool, etc.)
- ✅ Symbol table pre-pass collects function signatures with parameters
- ✅ Generated code includes `extern int func_name (int param1, double param2);` instead of `extern int func_name (void);`

**Key Achievement**: Module imports now carry full type information, enabling correct function calling from imported modules.

**Deferred**:
- Struct method mangling for imported types
- Generic type parameters and instantiation

---

### Priority 2 — Complete: Spec-Driven Module Loader Generation

**Status**: ✅ module_spec_gen.py generates module_loader.py from specification

**Implemented**:
- ✅ Created module_spec_gen.py to auto-generate module_loader.py from GNU-EXTENSIONS.md
- ✅ Extracts module path resolution rules from specification
- ✅ Extracts parameter extraction logic and type mappings (18 type entries)
- ✅ Generated code passes all tests (142 gimple + 7 execution + import tests)
- ✅ Enables fully spec-driven module system implementation
- ✅ `python module_spec_gen.py --output module_loader.py` produces working code

**Key Achievement**: Module system defined declaratively in specs; implementation generated automatically. Changes to module behavior require only spec updates, not code edits.

---

### Priority 4 — Complete: GIMPLE Specification Suite

**Status**: ✅ All 7 specifications complete (700+ lines total)

**Implemented**:
- ✅ gimple-type-system.md — Type lattice with TypeLattice.join() algorithm, rank systems, type inference rules
- ✅ gimple-runtime.md — Complete container/exception/string/memory APIs (~140 functions documented)
- ✅ gimple-exceptions.md — Try/except/finally lowering, exception context stack management
- ✅ gimple-closures.md — Capture analysis algorithm, closure lifting, environment struct generation
- ✅ gimple-iterators.md — Range/container/struct iteration protocols, for-loop lowering patterns
- ✅ gimple-memory.md — Pointer operations, UnsafePointer methods, pointer dereferencing helpers
- ✅ gimple-generics.md — Monomorphization strategy, generic function/struct specialization

**Key Achievement**: All gimple_codegen.py lowering rules now formally documented. Behavior is explicit, reviewable, and ready for code generation.

---

### Priority 3 — Complete: Spec-Driven GIMPLE Dispatch

**Status**: ✅ `gimple_codegen.py` fully driven by `generated_dispatch.py`; no duplicate hardcoded tables

**Implemented**:
- ✅ `GNU-EXTENSIONS.md` extended with machine-readable `_BIN_OPS`/`_CMP_OPS` Python code blocks
- ✅ `gimple_spec_gen.py` extracts `_BIN_OPS`/`_CMP_OPS` from `GNU-EXTENSIONS.md`
- ✅ `gimple_spec_gen.py` extracts `_SIGNED`/`_UNSIGNED`/`_FLOAT` rank tables from `gimple-type-system.md`
- ✅ `gimple_spec_gen.py` emits `_STMT_DISPATCH` (21 entries) and `_EXPR_DISPATCH` (19 entries)
- ✅ `gimple_codegen.py` imports all five tables from `generated_dispatch.py`; hardcoded copies removed
- ✅ `gen_stmt()` replaced with 4-line dict dispatch; 21 `_gen_stmt_*` handler methods extracted
- ✅ `lower_expr()` replaced with 4-line dict dispatch; 10 `_lower_*` handler methods extracted
- ✅ `run.py` regenerates both `mojo_compiler.py` and `generated_dispatch.py` in one step

**Key Achievement**: Adding a new statement or expression form requires only adding a handler method and one dispatch table entry in `gimple_spec_gen.py`, then running `python run.py`.

---

### Priority 5 — Complete: DispatchSolver for Dynamic Dispatch Resolution

**Status**: ✅ Complete three-phase solution with promotions analysis. 158+ tests passing, 0 failures.

#### Phase A: Dispatch Pattern Detection

**Implemented**:
- ✅ Build complete call graph from all functions and struct methods
- ✅ Detect dynamic dispatch patterns: `getattr(self, f'method_{type}', None)` and dict subscript lookups
- ✅ Infer possible callees by matching method name prefixes
- ✅ Track struct method mapping for quick lookup
- ✅ Identify monomorphic (single-caller) functions
- ✅ 4 comprehensive tests covering all detection scenarios

**Key Achievement**: Whole-program analysis identifies which functions can be compiled vs which use dynamic features.

#### Phase B: Dispatch Table Planning

**Implemented**:
- ✅ Plan vtable structures for each unique set of callees
- ✅ Two dispatch strategies: FUNC_POINTER (struct fields) and ARRAY_INDEX (arrays)
- ✅ Generate C typedef declarations for vtables
- ✅ Generate C initialization code with method pointers
- ✅ Generate dispatch call patterns for both strategies
- ✅ Infer C signatures from function return types
- ✅ 7 comprehensive tests including full C code generation

**Key Achievement**: Transforms Python dispatch patterns into static C virtual method tables that GIMPLE can compile.

#### Phase C: GimpleGen Integration

**Implemented**:
- ✅ Instantiate DispatchSolver after type analysis in `gen_module()`
- ✅ Run whole-program analysis on complete closure
- ✅ Emit dispatch table typedefs after struct definitions
- ✅ Emit dispatch table initializations before function bodies
- ✅ Maintain proper code ordering: typedefs → inits → function bodies
- ✅ 5 integration tests verifying correct emission and ordering

**Key Achievement**: Dispatch tables seamlessly integrated into generated GIMPLE code pipeline.

#### Phase C+: Typed Function Pointers (Recently Completed)

**Implemented**:
- ✅ Extract parameter type information from all function definitions
- ✅ Generate typed function pointers instead of `void *` placeholders
- ✅ Infer struct type from function name (e.g., `Interpreter_execute_X` → `Interpreter *`)
- ✅ Default parameters without annotations to `int`
- ✅ Eliminated ~35 "incompatible pointer type" compilation errors
- ✅ Reduced stage2 errors from ~40 to 23

**Example**:
```c
// Before: Generic void pointers
int (*execute_Module)(void *self, void *node);

// After: Typed function pointers
int (*execute_Module)(Interpreter *self, int node);
```

**Key Achievement**: Function pointers now match actual signatures, eliminating type mismatch errors.

#### Promotions Analysis: def→fn and Type Promotion

**Implemented** (Passes 4-5):
- ✅ `FunctionCompilability` analyzer identifies functions that can be promoted from Python to C
- ✅ Checks for complete type annotations (all parameters + return type)
- ✅ Verifies body contains only C-compatible operations
- ✅ Handles struct methods with implicit `self` typing
- ✅ Recursively walks expression trees to detect dynamic patterns (getattr, etc.)
- ✅ `TypePromotionSolver` propagates types across call graph
- ✅ Promotes mixed types to compatible common forms
- ✅ 7 comprehensive promotion tests covering all scenarios

**Public API** (methods on `DispatchSolver`):
- `get_compilable_functions()` — set of def→fn promotable functions
- `is_function_compilable(func_name)` — query single function compilability
- `get_compilability_report()` — detailed analysis with reasons for failures
- `get_promoted_types()` — all types promoted across closure

**Key Achievement**: Identifies which functions can be compiled to C and what types should be promoted for cross-closure compatibility.

#### Testing and Regression Analysis

**All tests pass**:
- ✅ 4 Phase A (pattern detection) tests
- ✅ 7 Phase B (table planning) tests
- ✅ 5 Phase C (code generation) tests
- ✅ 4 DispatchSolver integration tests
- ✅ 7 Promotion analysis tests (def→fn and type promotion)
- ✅ test_dispatch_myinterpreter.py (realistic Interpreter pattern)

**Total**: 158+ tests pass, 0 failures. No regressions to existing functionality.

#### Files

- `gimple_codegen.py` — DispatchSolver, DispatchPattern, DispatchTable, FunctionCompilability, TypePromotionSolver classes (~500 lines)
- `test_dispatch_solver.py` — Phase A unit tests
- `test_dispatch_phase_b.py` — Phase B unit tests
- `test_dispatch_phase_c.py` — Phase C integration tests
- `test_dispatch_promotions.py` — Promotion analysis tests
- `test_dispatch_myinterpreter.py` — Realistic pattern analysis
- `PHASE_A_IMPLEMENTATION.md` — Detailed Phase A documentation
- `PHASE_B_IMPLEMENTATION.md` — Detailed Phase B documentation
- `PHASE_C_IMPLEMENTATION.md` — Detailed Phase C documentation

**Key Achievement**: Complete end-to-end solution for transforming dynamic Python dispatch patterns to static C virtual method tables, enabling GIMPLE bootstrap compilation.

