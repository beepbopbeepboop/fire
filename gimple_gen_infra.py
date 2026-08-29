"""GimpleGen infrastructure: emit/temps/coercion/const-eval/strings/comprehensions.

Function-extraction architecture: former GimpleGen methods as
module-level functions taking `gen` first; delegates remain on
the class; cross-module references are qualified.
"""
from __future__ import annotations

import os
import re

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
)
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc

def _exc_type_id(gen, name: str) -> int:
    """The tag for an exception class name: a hash of the name, not a
    first-seen-order counter. Stdlib compilation runs many GimpleGen
    instances (parallel process pool, one per module) and a plain
    incrementing counter would assign a different id to the same name
    depending on which process visits it first — same logical program,
    different generated C, which defeats the CAS content-cache (every
    build looks like new content, forcing a full stdlib rebuild every
    time instead of a cache hit)."""
    if name not in gen._exc_type_ids:
        gen._exc_type_ids[name] = (gimple_ctypes.zlib.crc32(name.encode()) & 0x7fffffff) or 1
    return gen._exc_type_ids[name]


def _is_exc_class_name(gen, name: str) -> bool:
    """Whether `name` is confidently an exception *class*, not a local
    variable — a user-defined struct (naturally exception-shaped or not;
    struct_field_types has no notion of inheritance) or a known builtin."""
    return name in gen._KNOWN_EXCEPTION_NAMES or name in gen.struct_field_types


def _reset_func(gen, body: list = None, params: list = None):
    gen.bb_counter   = 2
    gen.temp_counter = 0
    gen.decls:       list[str]         = []
    gen.body_lines:  list[str]         = []
    gen.var_types:   dict[str, str]    = {}
    # `{mut}`-capture-spec preloaded pointer temps (see _gen_lifted_
    # closure) -- reset per function so a stale entry from a
    # previously-compiled closure can never leak into an unrelated
    # function's body.
    gen._gimple_mut_ptr: dict[str, str] = {}
    gen._struct_field_owners.clear()
    # ENCLOSING function's own locals that some nested closure captures
    # BY REFERENCE (name -> pointee ctype) -- see _seed_mut_captured_
    # local_types's docstring for why these are "boxed" (heap-
    # allocated, the local itself declared as a POINTER) rather than
    # plain stack locals whose address is taken: `-fgimple` rejects a
    # stack local's address being taken anywhere in the function if
    # that same local is also the target of a cast-assignment or the
    # direct operand of a `return` statement elsewhere (confirmed via
    # a hand-reduced repro -- "non-register as LHS of unary operation"
    # / "invalid operand in return statement"), which real stdlib code
    # doing exactly that (std/memory/span.mojo's `Span.count`, hit
    # during this fix's own stdlib-dylib regression check) triggers
    # immediately. Boxing sidesteps the restriction entirely: the
    # local is a plain, never-address-taken pointer variable from
    # first declaration, so ordinary GIMPLE rules apply to IT, and
    # only its (separately allocated) pointee is ever accessed
    # in-place.
    gen._boxed_mut_locals: dict[str, str] = {}
    gen.loop_stack:  list[tuple[str,str]] = []
    gen.exc_depth    = 0
    # Set True by _gen_stmt_TryStmt / the with-__exit__ path in
    # _gen_stmt_WithStmt whenever THIS function's own body (not a
    # nested closure's — those get their own _reset_func/flag) emits a
    # real `setjmp(...)`. Consulted by _gen_struct_method /
    # _gen_lifted_closure when emitting their C signature: a
    # `__GIMPLE`-tagged function's body bypasses gcc's normal
    # frontend gimplification pass, which is what marks a
    # setjmp-containing function's CFG with the special "returns-
    # twice" abnormal-edge handling real setjmp/longjmp semantics
    # require -- confirmed via a hand-reduced, Mojo-independent C
    # repro that `longjmp` into a `__GIMPLE`-tagged function's
    # `setjmp` frame reads back all-zero and segfaults. See
    # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
    # "Segfault root-caused" section. gen_func (free functions) has
    # always deliberately been non-`__GIMPLE` (LENIENT) already, so
    # this flag only matters for the two `__GIMPLE`-tagged code
    # paths.
    gen._func_used_setjmp: bool = False
    gen.func_ret_type: str             = ''
    gen._last_was_terminal: bool       = False
    # Computed once, reused for both the _elem_types and _dict_val_types
    # seeds just below -- see _locally_bound_names' own docstring.
    _reset_locally_bound = gen._locally_bound_names(body, params)
    # Container / layout state.
    # Seeded from self._global_elem_types (populated once by gen_module's
    # Phase 1.7 pre-scan, never reset) rather than starting empty -- a
    # module-level global container's element type means the same thing
    # in every function, so it must survive this per-function reset the
    # same way _field_elem_types already does for struct fields. Without
    # this seed, EVERY read of a global list/dict inside any function
    # (not just _toplevel) silently defaulted to int64_t, even though
    # Phase 1.7 had already correctly inferred the real type moments
    # earlier — a genuine, silent wrong-value bug, not a compile
    # failure. See bugs/hard/CODEGEN_reset_func_wipes_global_container_
    # type_inference.md.
    #
    # Names LOCALLY bound anywhere in this function's own body (per
    # _locally_bound_names, real Python scoping: any assignment target
    # anywhere in the function makes that name local for the WHOLE
    # function) are excluded from the seed entirely -- confirmed via a
    # real segfault otherwise: a local `path_separators = [42, 43]`
    # shadowing the global `path_separators: list[str]` inherited the
    # seeded char* element type for its OWN static return-type
    # inference (which runs as an early syntactic pre-pass, before any
    # of the function's own assignments are actually processed, so it
    # has no notion of "this name gets reassigned partway through" —
    # only "is there currently an entry for this bare name"). The
    # existing per-assignment write sites (e.g. _gen_stmt_AssignStmt)
    # DO correctly overwrite _elem_types once the body is actually
    # generated statement-by-statement, but a static pre-pass reading
    # the table before that point would otherwise see the wrong,
    # global-seeded entry for a name Python itself treats as local
    # for this entire function.
    gen._elem_types:      dict[str, str]   = {
        k: v for k, v in gen._global_elem_types.items()
        if k not in _reset_locally_bound
    }  # container var → element C type
    gen._nested_elem_types: dict[str, str] = {}
    gen._span_mut_params: dict[str, bool]  = {}  # param/var name → literal Span/StringSlice mut=True/False
    # NOTE: _field_elem_types is intentionally NOT reset here — it stores
    # per-struct metadata that must persist across function boundaries
    # (set during __init__ field assignments, read at any later field
    # access site).  Initialized once in __init__.
    # Actual type of int64_t-boxed pointers, keyed by temp/var name. MUST reset
    # per function: temp names (_tN) recycle, so a stale entry from one function
    # would mis-type a same-named temp in the next (e.g. an open() file handle
    # read as a leftover MojoSet*, emitting MojoSet_read).
    gen._actual_types:    dict[str, str]   = {}
    # Flow-sensitive `isinstance()` narrowing. Inside the then-branch of
    # `if isinstance(E, SomeStruct):` (and `and`-chains of such tests),
    # every read of E is known to be a `SomeStruct *` — the guard the
    # source already wrote. Key: "i:<name>" for an IdentExpr E, or
    # "m:<obj>.<member>" for a MemberExpr E with an IdentExpr base. Value:
    # (ctype, c_value). _lower_IdentExpr / _lower_MemberExpr consult this
    # before their generic type-erased handling; _gen_stmt_IfStmt sets and
    # restores it around each guarded body. Reset per function like every
    # other per-body table here.
    gen._narrowed_exprs:  dict             = {}
    # Function PARAM name -> the bare struct name its Mojo annotation
    # names, when that annotation's base is a known struct (e.g.
    # `downgrade: ArcPointer[Self.T]` → 'ArcPointer'). The ABI can box
    # such a param to a generic scalar/pointer (`int64_t`/`int64_t *`)
    # that loses the struct identity entirely, so _lower_MemberExpr
    # consults this map to recover the real struct-pointer type to cast
    # to before a `->member` access. Reset per function: param names
    # recycle and struct identity must never leak across functions.
    gen._param_struct_types: dict[str, str] = {}
    # MojoBoundMethod* var/temp name -> the bound method's real return
    # type, so a later call through the value (_lower_bound_method_call)
    # narrows the result correctly instead of always assuming int64_t.
    # Reset per function for the same reason _actual_types is: temp
    # names (_tN) recycle across functions. See _lower_bound_method_value.
    gen._bound_method_ret_types: dict[str, str] = {}
    # Builtin-container method bound as a first-class VALUE (`append =
    # l.append`, the classic accumulator-aliasing idiom) — key: the C
    # name of the temp/var holding the boxed value; value: (receiver
    # ctype, receiver hidden-local C name, method name). A later call
    # through the stored value (_lower_named_call / _gen_stmt_ExprStmt's
    # statement-level twin) lowers as a DIRECT container-method call on
    # the recorded hidden receiver local, reusing _lower_list_method/
    # _lower_dict_method/_lower_set_method verbatim — so per-call-site
    # int/str element dispatch behaves exactly like the direct
    # `l.append(x)` spelling. The receiver is captured into its own
    # void* hidden local at the reference site, so rebinding the source
    # variable afterwards can't redirect an already-taken bound method.
    # Reset per function for the same reason _bound_method_ret_types is:
    # temp names (_tN) recycle across functions. See
    # _lower_builtin_method_value.
    gen._builtin_method_values: dict[str, tuple] = {}
    # Pre-seed known global dicts with their value types so .get() uses the right function.
    # Also seeded from self._global_dict_val_types (Phase 1.7, never
    # reset) for the same reason _elem_types is seeded from
    # _global_elem_types just above — same shadowing exclusion too.
    gen._dict_val_types:  dict[str, str]   = {
        '_BIN_OPS': 'char *', '_GD_BIN_OPS': 'char *',
        **{k: v for k, v in gen._global_dict_val_types.items()
           if k not in _reset_locally_bound},
    }  # dict var → value C type
    gen._struct_layout:   dict[str, str]   = {}  # var_name → STACK|HEAP
    gen._layout_hint:  str             = gimple_solvers.LayoutSolver.HEAP  # for struct constructors
    gen.current_func_name: str         = ''
    gen._loop_depth:   int             = 0   # nesting depth for freq annotations
    # Closure state (set when generating a lifted inner function)
    gen._captures:   dict[str, str]    = {}  # captured var → ctype
    gen._env_param:  str               = ''  # name of env pointer ('_env')
    # Active env pointers for this outer function (inner_name → env_var)
    gen._closure_envs: dict[str, str]  = {}
    # Original inner function name for recursive call detection (set in _gen_lifted_closure)
    gen._inner_func_name: str          = ''
    # C keyword renaming: Python name → C name (for vars that clash with C keywords)
    gen._c_names:    dict[str, str]    = {}
    # Names currently bound by an `except <ExcType> as <name>:` clause in
    # this function (see _emit_except_handler, which adds/removes as it
    # enters/leaves each handler body — mirrors the had_c_name/
    # restore_c_name save-restore convention right next to it so nested/
    # shadowed except-as bindings and sequential try/except blocks in the
    # same function behave correctly). A caught exception object is
    # lowered as a bare `char *` message string (see _gen_stmt_RaiseStmt/
    # _emit_except_handler), not a real struct — so ordinary MemberExpr
    # field dispatch (which keys off `ot`, the C type) can never resolve
    # it. This set lets a MemberExpr's write/read lowering recognize
    # "this receiver is genuinely an except-as-bound exception object"
    # SYNTACTICALLY (the identifier's name, not its `char *` C type) and
    # route it through the dynamic-attribute dispatch machinery, without
    # broadening the type-keyed dispatch condition to match `char *` in
    # general (which is used pervasively for ordinary strings — see
    # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
    # "Residual gap: caught exception objects" section for why that
    # broader fix was rejected as too risky).
    gen._except_as_names: set          = set()
    # Names declared `global` inside this function — reads/writes route to module struct
    gen._func_declared_globals: set    = set()
    # True only while generating a module's own _toplevel()/_{module}_toplevel()
    # body (see _gen_toplevel) — distinguishes genuine module-scope statements
    # (whose assignments must persist to that module's globals struct) from a
    # real Python function's body (current_func_name is ALSO non-empty there,
    # e.g. '_cas_toplevel', so current_func_name alone can't tell them apart).
    gen._in_toplevel_gen: bool          = False


def _record_sys_path_inserts(gen, source: str, base_dir: str = None) -> None:
    """Statically scan `source` for literal sys.path.insert(N, "...") calls
    and remember each target directory in self._extra_search_paths (highest
    priority in _compile_imported_module). A relative literal is resolved
    against `base_dir` (the file the source came from) — matching how the
    interpreter's actual sys.path.insert call at run time would resolve a
    relative path against the process CWD at that point, approximated here
    at compile time by the importing file's own directory.

    Deliberately `.findall()`, not `for m in PATTERN.finditer(source):
    m.group(1)` — that shape (a `.finditer()` loop over a *named*
    compile-time pattern, called from inside a class method with `self`
    in scope) hits an unrelated, still-unfixed self-hosting codegen gap
    in _gen_for_regex_iter/_gen_for_iter: gcc rejected the self-hosted
    gimple_codegen.py's own compiled output with a parse error even for
    a trivial empty loop body and even substituting an already-proven
    pattern (_TOKEN_RE) — so the break isn't specific to this pattern or
    this body, only to that (method-scope regex-finditer-loop) combination.
    `.findall()` returns a plain list of the captured strings directly
    and goes through ordinary list iteration instead, sidestepping the
    gap entirely; `.group(n)` with an argument isn't self-host-supported
    either way (see _gen_for_regex_iter's docstring), so `.findall()`
    loses nothing here — this pattern only has the one capture group."""
    for p in gimple_codegen._SYS_PATH_INSERT_RE.findall(source):
        if base_dir and not gimple_ctypes.os.path.isabs(p):
            p = gimple_ctypes.os.path.join(base_dir, p)
        if p not in gen._extra_search_paths:
            gen._extra_search_paths.append(p)
    # The os.path.dirname(__file__) shape: `__file__` at compile time IS
    # `base_dir`'s file, so os.path.dirname(__file__) == base_dir itself;
    # a trailing relative literal (e.g. "..") joins onto that. No literal
    # at all (bare `os.path.dirname(__file__)`) means base_dir unchanged.
    if base_dir:
        for rel in gimple_codegen._SYS_PATH_INSERT_DIRNAME_RE.findall(source):
            p = gimple_ctypes.os.path.normpath(gimple_ctypes.os.path.join(base_dir, rel)) if rel else base_dir
            if p not in gen._extra_search_paths:
                gen._extra_search_paths.append(p)


def _compile_link_inline_cpp_unit(gen, cpp_code: str):
    """Compile a transitively-imported module's own self-contained
    `generated_cpp` (a plain, non-generic top-level generator/async
    function's C++20 coroutine translation unit -- see
    `_compile_imported_module`'s call site, link mode's `_link_inline_
    modules` fallback) to a CAS-cached object with g++, and return its
    path (or None on any failure -- link-mode's own convention: never
    let a companion-object build failure abort the whole compile, the
    caller already checks for None).

    Mirrors driver.py's `_build_client_cpp_object` (the root module's
    OWN companion .cpp) and monomorphize.instantiate's identical per-
    instantiation cpp build (an elaborated generic's own coroutine
    unit) -- same "compile this self-contained generated_cpp text to
    an object" operation, a third call site for it rather than a
    fourth independent reimplementation (CLAUDE.md: consolidate, don't
    duplicate) -- kept as its own small method (not literally imported
    from driver.py) only because driver.py imports FROM gimple_codegen.
    py already (compile_linked), so the reverse import would be
    circular; the CAS key scheme, flags, and g++ invocation are
    deliberately identical to driver.py's version so the two draw from
    (and populate) the exact same CAS entries for byte-identical cpp
    text."""
    try:
        import cas
        import subprocess
        import tempfile
        from build_config import find_gxx
    except Exception as e:
        gimple_ctypes._debug_note('cannot compile link-mode inline-module cpp unit '
                    '(import failure)', e)
        return None
    try:
        gxx = find_gxx()
        runtime_dir = gimple_ctypes.os.path.join(gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(__file__)), 'runtime')
        cpp_flags = ('-std=c++20', '-fPIC', f'-I{runtime_dir}')
        key = cas.module_key(cpp_code, [], gxx, cpp_flags)

        def _build_fn():
            wd = tempfile.mkdtemp(prefix='mojo_linkmod_cpp_')
            cf = gimple_ctypes.os.path.join(wd, 'link_inline_module.cpp')
            of = gimple_ctypes.os.path.join(wd, 'link_inline_module.o')
            with open(cf, 'w') as f:
                f.write(cpp_code)
            subprocess.run([gxx, *cpp_flags, '-c', '-o', of, cf], check=True,
                           capture_output=True)
            with open(of, 'rb') as f:
                return f.read()

        obj, _hit = cas.get_or_build(key, '.o', _build_fn)
        return obj
    except Exception as e:
        gimple_ctypes._debug_note('failed to compile link-mode inline-module cpp unit', e)
        return None


def _emit_stdlib_import_externs(gen, stmts) -> None:
    """Scan from-import stmts and emit extern declarations for concrete
    functions found via load_module (text-only extraction — no dylib builds,
    no recursion). Populates _link_import_decl_list and registers types so
    call sites lower correctly. Safe to call for any module; no-ops if a
    symbol is already registered."""
    seen = set(gen.func_return_types.keys()) | set(gen.imported_symbols.keys())

    # Determine the package prefix for resolving relative imports (e.g.
    # `._swisstable` → `std.collections._swisstable` when compiling
    # `std/collections/dict.mojo`).
    _pkg_prefix = ''
    if gen._current_filename:
        from module_loader import STDLIB_PATH
        # Avoid runtime 'import os' — the compiled binary can't resolve
        # Python's os module.  Use string ops instead of os.path.relpath.
        _fn = gen._current_filename
        _sp = STDLIB_PATH
        # Normalize trailing separators
        if _fn.endswith('/') or _fn.endswith('\\'):
            _fn = _fn[:-1]
        if _sp.endswith('/') or _sp.endswith('\\'):
            _sp = _sp[:-1]
        if _fn.startswith(_sp + '/') or _fn.startswith(_sp + '\\'):
            rel = _fn[len(_sp)+1:]
            parts = rel.replace('\\', '/').split('/')
            if len(parts) > 1:
                _pkg_prefix = '.'.join(parts[:-1]) + '.'

    # Names that conflict with GCC built-ins or C stdlib declarations — skip
    # emitting externs for these even if load_module finds them.
    _C_BUILTINS = frozenset({
        'abort', 'atof', 'atoi', 'atol', 'atoll', 'exit', '_exit',
        'fclose', 'fopen', 'fread', 'fwrite', 'fseek', 'ftell', 'fflush',
        'fma', 'fmaf', 'pow', 'powf', 'sqrt', 'sqrtf',
        'sin', 'sinf', 'cos', 'cosf', 'tan', 'tanf',
        'exp', 'expf', 'log', 'logf', 'log2', 'log2f', 'log10', 'log10f',
        'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf',
        'abs', 'fabs', 'fabsf', 'fmod', 'fmodf',
        'trunc', 'nan',
        'malloc', 'free', 'realloc', 'calloc',
        'pclose', 'popen', 'dlclose', 'dlopen', 'dlsym', 'dlerror',
        'printf', 'fprintf', 'sprintf', 'snprintf', 'scanf', 'sscanf',
        'strlen', 'strcpy', 'strncpy', 'strcmp', 'strncmp',
        'strcat', 'strncat', 'strstr', 'strchr', 'strrchr',
        'memcpy', 'memmove', 'memset', 'memcmp',
        'stat', 'lstat', 'fstat', 'open', 'close', 'read', 'write',
        'max', 'min', 'chr', 'ord',
        'fdopen', 'fileno', 'tmpfile', 'tmpnam',
        'getenv', 'setenv', 'unsetenv', 'putenv',
        'isatty', 'getuid', 'getpid', 'getppid',
        # Linux-specific libc wrappers that collide with GCC declarations
        'get_errno', 'set_errno', '_getpw_linux', '_lstat_linux_x86_64',
        '_stat_linux_x86_64', '_fstat_linux_x86_64',
    })

    def _resolve_relative(mod, pkg_prefix):
        """Resolve relative import: count leading dots, go up that many levels."""
        if not mod.startswith('.'):
            return mod
        dots = len(mod) - len(mod.lstrip('.'))
        rest = mod.lstrip('.')
        parts = pkg_prefix.rstrip('.').split('.')
        # dots=1 → current package (no level up), dots=2 → parent, etc.
        up = dots - 1
        if up > 0:
            parts = parts[:-up] if up < len(parts) else []
        base = '.'.join(parts)
        return (base + '.' + rest) if (base and rest) else (base or rest)

    for stmt in stmts:
        if not isinstance(stmt, gimple_ctypes.FromImportStmt):
            continue
        mod = stmt.module
        # Resolve relative imports: '._foo' → 'std.pkg._foo', '.._foo' → 'std.parent._foo'
        if mod.startswith('.'):
            mod = _resolve_relative(mod, _pkg_prefix)
        try:
            exports = gimple_ctypes.load_module(mod)
        except Exception as e:
            gimple_ctypes._debug_note(f'load_module({mod!r}) failed; skipping import', e)
            continue
        if not exports:
            continue
        for name, alias in stmt.names:
            sym = alias if alias else name
            # Record this function's home module (SB-1 fix, _func_qualifier)
            # UNCONDITIONALLY — deliberately BEFORE the `sym in seen`
            # early-exit below. `seen` (and func_return_types, which
            # seeds it) is SHARED across every nested temp_gen a
            # do_imports=True build spins up (_compile_imported_module:
            # `temp_gen.func_return_types = self.func_return_types`), so
            # by the time a SECOND module's own FromImportStmt scan for
            # the SAME bare name runs, `sym in seen` is already true
            # (some earlier module already registered it) and an early
            # `continue` here would skip this registration entirely —
            # exactly the bug that made _own_imported_func_home stay
            # empty for beta_wrapper.mojo's own compile in the repro
            # below, silently leaving its call site to fall through to
            # the shared, first-registered-wins _imported_func_home
            # fallback (alpha_module's qualifier) instead of its own
            # correct one. This registration is independent of `exports`/
            # `info`/`sig` (needs only `mod` + `sym`) and setdefault-safe,
            # so computing it before the early-exit is always correct.
            # Resolved via module_loader's OWN resolve_module_path (the
            # exact resolution `load_module(mod)` below just used to find
            # this module's exports) rather than self._parsed_import/
            # imports' process-global Resolver singleton: that
            # singleton's search path is mutated by whichever test/build
            # last called imports.reset_resolver(path=...) and is NOT
            # necessarily scoped to this compile, so resolving through it
            # here was observed to silently return no path (test order-
            # dependent — a prior test's reset_resolver(path=[some other
            # tempdir]) left the global resolver unable to find a
            # runtime/-relative sibling module like 'corolike'),
            # producing an unqualified qualifier that disagreed with the
            # defining module's own (correctly qualified) compile and
            # broke the link. module_loader's resolve_module_path has no
            # such global mutable state — it's a pure function of
            # STDLIB_PATH/TEST_PATH.
            import module_loader as _mlmod
            _imp_path = _mlmod._module_loader.resolve_module_path(mod)
            if _imp_path and gimple_ctypes.os.path.exists(_imp_path):
                _qual = _mlmod.module_name_for_path(_imp_path)
                if _qual:
                    # _own_imported_func_home (per-instance, see its own
                    # comment): THIS module's own FromImportStmt is
                    # authoritative for this bare name within this
                    # module's own body — must win over any OTHER
                    # module's claim on the same bare name in the shared
                    # _imported_func_home fallback.
                    gen._note_own_func_home(sym, _qual)
            if sym in seen or sym in _C_BUILTINS or (
                    sym in gen._LIBC_DECLARED
                    and sym not in gen._NEEDS_SELF_EXTERN):
                continue
            info = exports.get(name)
            if not info:
                continue
            sig = info.get('signature')
            if not sig:
                continue
            ret = info.get('c_return_type', 'int64_t')
            c_params = info.get('c_parameters') or []
            ptypes = [' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp
                      for cp in c_params]
            # A name in _NEEDS_SELF_EXTERN has ONE true C prototype, pinned in
            # _LIBC_SIGS. The export-derived signature (module_loader maps the
            # exporting Mojo wrapper's Int64-level types to int64_t text) can
            # disagree with that pin — e.g. std.sys._libc's `def dup(oldfd:
            # c_int)` exports `int64_t dup (int64_t oldfd)`, while every bare-
            # call site records the pinned `extern int dup (int);` into
            # _external_protos via _ensure_libc_self_extern — leaving TWO
            # conflicting declarations of the same libc symbol in one TU (hard
            # gcc "conflicting types for 'dup'/'pipe'" in the stdlib dylib's
            # std_io_io/std_os_process units). Pin the recorded + emitted
            # signature to the same libc truth so every declaration path for
            # these names agrees.
            if sym in gen._NEEDS_SELF_EXTERN:
                _pin = gen._LIBC_SIGS.get(sym)
                if _pin:
                    ret = _pin[0]
                    ptypes = list(_pin[1])
                    sig = f"{ret} {name} ({', '.join(ptypes)})"
            gen.func_return_types[sym] = ret
            gen.func_param_types[sym] = ptypes
            gen.imported_symbols[sym] = {
                'module': mod, 'original_name': name,
                'c_return_type': ret, 'signature': sig,
            }
            # When imported with an alias, replace the original name in the sig
            # so the extern matches the alias name used at call sites.
            if alias and name != alias:
                sig = gimple_ctypes.re.sub(r'\b' + gimple_ctypes.re.escape(name) + r'\b', alias, sig, count=1)
            # Overload-mangle the imported function's name in the extern so it
            # matches the (mangled) call sites and the defining module's symbol.
            # Only for genuinely mangled functions — reserved renames (pipe →
            # mojo_pipe) are handled by other decl paths and must not change here.
            if gen._func_mangleable(sym):
                _csym = gen._func_csym(sym)
                if _csym != sym:
                    sig = gimple_ctypes.re.sub(r'\b' + gimple_ctypes.re.escape(sym) + r'\b', _csym, sig, count=1)
            # Guard the extern with #ifndef so the pre-defined stubs (which use
            # the same guard macro _MOJO_STUB_<NAME>) don't produce a second
            # conflicting declaration. If the extern is emitted here, the stub
            # will see the macro already defined and skip itself.
            guard = gimple_ctypes._stub_guard_name(sym)
            decl = f'#ifndef {guard}\n#define {guard}\nextern {sig};\n#endif'
            gen._link_import_decl_list.append(decl)
            seen.add(sym)


def _emit_imported_global_accessors(gen, stmts) -> None:
    """Bare `from X import <module_scope_var>` — BUG-2026-009. See
    `_imported_global_accessors`'s own docstring and module_loader.py's
    'kind': 'global_var' export entries (module_loader._VAR_GLOBAL_RE)
    for the full picture; this is the consuming half.

    Resolution mirrors gen_module's own "Process imports" sibling
    handling (module_loader.load_module for stdlib/test modules,
    falling back to `_local_sibling_module_exports` for a local project
    sibling file — the exact shape `mojo dylib`'s per-module-
    independent compile needs, since a local sibling like box.3d/
    game's `engine_world.mojo` is never in module_loader's tracked
    stdlib/test set). Safe to call unconditionally (like
    `_emit_stdlib_import_externs`, right next to which this runs): a
    module with no `global_var`-kind import is an untouched no-op.
    """
    for stmt in stmts:
        if not isinstance(stmt, gimple_ctypes.FromImportStmt):
            continue
        mod = stmt.module
        try:
            exports = gimple_ctypes.load_module(mod)
            qual = None
            import module_loader as _mlmod
            _imp_path = _mlmod._module_loader.resolve_module_path(mod)
            if _imp_path and gimple_ctypes.os.path.exists(_imp_path):
                qual = _mlmod.module_name_for_path(_imp_path)
        except Exception:
            exports, qual = gen._local_sibling_module_exports(mod)
        if (not exports or not qual):
            # Self-host bootstrap: `from gimple_codegen import _C_RESERVED_
            # FUNCS` names a sibling `.py` compiler module that neither
            # module_loader (stdlib/test only) nor imports.resolve_source
            # (.mojo only) can resolve. Scan it directly for its
            # frozenset/set module globals so a re-exported set doesn't fall
            # to the codegen "undeclared -> (int64_t)0" NULL-set crash.
            # Scoped to global_var consumption below — no fn/struct/overload
            # signature is taken from this path.
            import module_loader as _mlmod2
            _sd = gimple_ctypes.os.path.dirname(
                gimple_ctypes.os.path.abspath(_mlmod2.__file__))
            _cand = gimple_ctypes.os.path.join(_sd, mod.split('.')[-1] + '.py')
            if gimple_ctypes.os.path.isfile(_cand):
                exports = _mlmod2._module_loader.load_module_from_path(_cand)
                qual = _mlmod2.module_name_for_path(_cand)
        if not exports or not qual:
            continue
        for name, alias in stmt.names:
            info = exports.get(name)
            if not info or info.get('kind') != 'global_var':
                continue
            sym = alias if alias else name
            if sym in gen._imported_global_accessors:
                continue
            ctype = info.get('c_return_type', 'int64_t')
            # A re-exported global (`from gimple_codegen import _C_RESERVED_
            # FUNCS`, itself `from gimple_ctypes import ...`) is accessed
            # through the accessor its TRUE defining module emits — use the
            # home path the scanner recorded, not the module named in this
            # `from` statement.
            _home_qual = qual
            _hp = info.get('home_module_path')
            if _hp:
                import module_loader as _mlmod_g
                _home_qual = _mlmod_g.module_name_for_path(_hp) or qual
            accessor_csym = (f'{gimple_ctypes._c_field_name(_home_qual)}__mojo_global_get_'
                              f'{gimple_ctypes._c_field_name(name)}')
            gen._imported_global_accessors[sym] = (ctype, accessor_csym)
            guard = gimple_ctypes._stub_guard_name(accessor_csym)
            decl = (f'#ifndef {guard}\n#define {guard}\n'
                    f'extern {ctype} {accessor_csym} (void);\n#endif')
            gen._link_import_decl_list.append(decl)


def _new_bb(gen) -> str:
    gen.bb_counter += 1
    return f"bb_{gen.bb_counter}"


def _emit(gen, line: str):
    gen.body_lines.append(line)
    # Track whether this is a terminal statement (can't have code after it)
    stripped = line.strip()
    if stripped.startswith('return ') or stripped.startswith('goto ') or stripped == 'return;':
        gen._last_was_terminal = True
    else:
        gen._last_was_terminal = False


def _type_of(gen, name: str) -> str:
    boxed = getattr(gen, '_boxed_mut_locals', None)
    if boxed and name in boxed and name not in gen._captures:
        # See _seed_mut_captured_local_types: `var_types[name]` holds
        # the POINTER ctype (what the real C declaration needs), but
        # ordinary scalar type-inference (e.g. `count + 1`) must see
        # the pointee type instead, exactly like the async mutable-
        # capture mechanism's own `declared` dict does for the same
        # reason (see _gen_cpp_async_unit's docstring).
        return boxed[name]
    return gen.var_types.get(name, 'int64_t')


def _elem_of(gen, name: str) -> str:
    """Element type for a container variable."""
    # First, check if this is an int64_t-stored pointer with tracked element type
    if name in gen._elem_types:
        return gen._elem_types[name]
    # If no tracked element type, return default
    return 'int64_t'


def _dict_val_of(gen, name: str) -> str:
    """Value C type for a dict variable."""
    return gen._dict_val_types.get(name, 'int64_t')


def _scalar_arg_is_addressable_local(gen, aval) -> bool:
    """BUG-2026-016's discriminator for _emit_call's scalar->pointer
    coercion: True iff `aval` is a bare identifier that is positively
    known to be a declared LOCAL (or parameter/temp -- anything with a C
    declaration in this function body, which `var_types` tracks for
    exactly those) and is NOT tracked as an opaque pointer handle.

    The conservative exclusions are load-bearing:
      * `_actual_types` -- set precisely when codegen knows an
        int64_t-typed name really holds a struct/container pointer;
        such handles must keep the legacy by-value pass-through.
      * `_global_var_types` -- globals are excluded entirely: an
        int64_t global is the one place "holds a real FFI pointer"
        is common (the legacy branch's own cited case), and aliasing
        writes into a caller's global on behalf of an out-param was
        never the old behavior.
    Everything else reaching the coercion branch with a pointer-typed
    parameter is a genuine value argument -- today silently reinterpreted
    as an address (a near-NULL store -> segfault), per BUG-2026-016."""
    if not isinstance(aval, str):
        return False
    if aval in gen._actual_types or aval in gen._global_var_types:
        return False
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', aval) is None:
        return False
    # Codegen temps are excluded on purpose: a temp is where an arbitrary
    # EXPRESSION's value landed (a call result, a folded constant -- e.g.
    # std/collections/list.mojo's `__iter__` passing a null UnsafePointer
    # for `src` lowered to `_t10 = 0`, which must keep reaching the
    # callee AS NULL, not as the address of the dead temp). Only a name
    # that came straight from SOURCE -- a declared local/parameter the
    # user explicitly wrote as the out-param argument -- gets aliased.
    if re.fullmatch(r'_t\d+', aval) is not None:
        return False
    return aval in gen.var_types


def _emit_call(gen, ret_type: str, result_var: str, fname: str, arg_pairs: list) -> None:
    """Emit a function call with GIMPLE-valid argument coercions.

    arg_pairs: list of (ctype, varname) for each argument.
    For each argument, if the declared parameter type differs from the
    passed type, emit an intermediate temp with the correct cast.
    """
    # Rename certain C library functions to mojo_* wrappers with void* params
    fname = gen._CALL_RENAMES.get(fname, fname)
    sig = gen._KNOWN_SIGS.get(fname)
    if sig:
        param_types = sig[1]
    elif fname in gen._LIBC_SIGS:
        # Raw libc symbol (e.g. pclose): the canonical C signature wins over
        # func_param_types, which a same-named Mojo wrapper may have polluted.
        param_types = gen._LIBC_SIGS[fname][1]
    else:
        # Fall back to a same-file overloaded struct method/constructor's
        # own precomputed signature (Pass 2b-bis) for a call to a sibling
        # overload whose real definition hasn't been emitted yet — see
        # _mangled_signature_ctypes's own comment.
        param_types = gen.func_param_types.get(fname)
        mangled_sig = gen._mangled_signature_ctypes.get(fname)
        # A `*args`-taking method's func_param_types entry starts life
        # ending in the packing sentinel '...' (registered when its body
        # is generated) but gets overwritten with the concrete real
        # signature (e.g. [..., 'MojoList *']) right after, so forward
        # declarations can match exactly (see the "Store per-overload
        # param types" comment near where mangled/param_ctypes_only is
        # built). Every OTHER call site compiled afterwards then sees the
        # concrete signature and silently skips packing, casting the
        # first loose vararg straight to MojoList* instead — found via a
        # real crash: `self._is_kw("as")` (Parser__is_kw, mojo_compiler.py)
        # reinterpreted the "as" string's raw pointer bits as a MojoList*
        # and segfaulted deep in mojo_list_contains_str. The sentinel form
        # survives untouched in _mangled_signature_ctypes (Pass 2b-bis
        # registers it for every method, not just overloaded ones), so
        # prefer it here whenever func_param_types's own copy lost it.
        if mangled_sig and mangled_sig[-1] == '...' and (
                not param_types or param_types[-1] != '...'):
            param_types = mangled_sig
        if param_types is None:
            param_types = mangled_sig or []


    # If function takes *args, pack variadic args into a MojoList*
    # '...' = free function varargs (pack all args)
    # [type, '...'] = method varargs (keep leading non-varargs args, pack rest)
    if param_types and param_types[-1] == '...':
        # Find how many leading args to keep (everything before the '...')
        n_fixed = len(param_types) - 1
        fixed_pairs = arg_pairs[:n_fixed]
        varargs = arg_pairs[n_fixed:]
        lst = gen._new_val('MojoList *', "mojo_list_new ()")
        for atype, aval in varargs:
            aval = gen._coerce_to_type(atype, 'int64_t', aval)
            gen._emit(f"  mojo_list_append_int ({lst}, {aval});")
        arg_pairs = fixed_pairs + [('MojoList *', lst)]
        param_types = list(param_types[:-1]) + ['MojoList *']

    coerced_args = []
    for i, (atype, aval) in enumerate(arg_pairs):
        ptype = param_types[i] if i < len(param_types) else atype
        # Check if int64_t actually contains a pointer (stored in _actual_types or _global_var_types)
        actual_atype = atype
        if atype == 'int64_t':
            if aval in gen._actual_types:
                actual_atype = gen._actual_types[aval]
            # Also check if it's a global variable that should be cast
            elif aval in gen._global_var_types:
                actual_atype = gen._global_var_types[aval]

        # Only pre-load non-slit globals like _BIN_OPS; slits are already char*.
        if aval in ('_BIN_OPS', '_GD_BIN_OPS'):
            temp = gen._new_val(atype, f'{aval}')
            aval = temp
        elif aval.startswith('_slit_'):
            # Pointer form (char *): direct load, no cast needed.
            temp = gen._new_val('char *', f'{aval}')
            aval = temp
        elif aval.startswith('"') and aval.endswith('"'):
            # Raw C string literal in GIMPLE call — convert to _slit_ variable
            slit_name = gen._str_literal_to_slit(aval)
            temp = gen._new_val('char *', f'{slit_name}')
            aval = temp
        if ptype == atype or ptype == '...':
            # Skip coercion only if C types match exactly
            coerced_args.append(aval)
        elif ptype == actual_atype and atype != ptype:
            # Semantic types match but C types differ (e.g., int64_t → MojoList *)
            # Still need to cast the underlying C type
            ip3 = gen._new_temp('int64_t')
            pp = gen._new_temp(ptype)
            aval_local = gen._ensure_local('int64_t', aval)
            gen._emit(f'  {ip3} = {aval_local};')
            gen._emit(f'  {pp} = ({ptype}){ip3};')
            coerced_args.append(pp)
        elif ptype == 'void *' and actual_atype in ('int', 'int64_t', '_Bool'):
            ip = gen._new_temp('int64_t')
            vp = gen._new_temp('void *')
            if actual_atype == 'int64_t':
                # GIMPLE: can't cast a global int64_t to int64_t (redundant cast fails)
                # Just load the value into a local temp directly
                aval_local = gen._ensure_local('int64_t', aval)
                gen._emit(f'  {ip} = {aval_local};')
            else:
                gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {vp} = (void *){ip};')
            coerced_args.append(vp)
        elif ptype == 'void *' and actual_atype.endswith(' *'):
            vp = gen._new_val('void *', f'(void *){aval}')
            coerced_args.append(vp)
        elif ptype == 'int64_t' and (actual_atype in ('int', '_Bool', 'char *', 'void *') or actual_atype.endswith(' *')):
            ct = gen._new_temp('int64_t')
            if atype == 'char *':
                aval_local = gen._ensure_local('char *', aval)
                ip2 = gen._new_val('void *', f'(void *){aval_local}')
                gen._emit(f'  {ct} = (int64_t){ip2};')
            elif atype == 'void *':
                aval_local = gen._ensure_local('void *', aval)
                gen._emit(f'  {ct} = (int64_t){aval_local};')
            elif atype.endswith(' *'):
                # Any struct pointer → void * → int64_t
                aval_local = gen._ensure_local(atype, aval)
                vp = gen._new_val('void *', f'(void *){aval_local}')
                gen._emit(f'  {ct} = (int64_t){vp};')
            else:
                gen._emit(f'  {ct} = (int64_t){aval};')
            coerced_args.append(ct)
        elif ptype == 'char *' and atype in ('int', 'int64_t', 'char'):
            # A raw single char whose DECLARED type was widened to
            # int64_t (joining another assignment site in the same
            # function — e.g. `qch = stmt[i]` in mojo_compiler.py's own
            # `_process_nested_tstrings`) still has its real type
            # tracked in _actual_types (actual_atype, resolved just
            # above) even though the bare `atype` check below can't see
            # it. Checking only `atype == 'char'` missed that case
            # entirely and fell to the `else` branch's raw void*
            # pointer-reinterpretation of the char's numeric byte value
            # — passing e.g. `(char *)0x22` (a garbage address built
            # from `"`'s ASCII code) to `_find_tstring_closing_quote`'s
            # `quote_ch: str` parameter, which then could never actually
            # match a real quote character, so `close` always came back
            # -1 and the caller silently fell through to its "no t/f-
            # string found" fallback. Confirmed via a from-scratch
            # instrumented stage1.ci build: `_find_tstring_closing_
            # quote_7a972f (stmt, i, _t42)`'s `_t42` was exactly this
            # `(char *)(void *)qch` cast, not a real 1-char string.
            if atype == 'char' or actual_atype == 'char':
                # `aval` itself is still C-declared as whatever `atype`
                # says (int64_t when widened) even though it's really a
                # char — cast it to a real `char` lvalue first so the
                # mojo_char_to_str call below isn't passing an int64_t
                # variable where GIMPLE expects an exact `char` match.
                cv = aval if atype == 'char' else gen._new_val('char', f'(char){aval}')
                sv = gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
                coerced_args.append(sv)
            else:
                vp = gen._new_temp('void *')
                cp = gen._new_temp('char *')
                if atype in ('int',):
                    ip = gen._new_val('int64_t', f'(int64_t){aval}')
                    gen._emit(f'  {vp} = (void *){ip};')
                else:
                    gen._emit(f'  {vp} = (void *){aval};')
                gen._emit(f'  {cp} = (char *){vp};')
                coerced_args.append(cp)
        elif ptype.endswith(' *') and (actual_atype in ('int', 'int64_t') or atype == 'int64_t'):
            # Parameter expects a pointer; the lowered argument is a plain
            # scalar-typed value. TWO unrelated situations reach this one
            # branch, and they need OPPOSITE handling (BUG-2026-016,
            # box.3d/game):
            #
            # (1) The argument names a real, declared local/temp of THIS
            #     function holding a genuine VALUE (e.g.
            #     `hopper_get_input(h, hin_id, hin_count)` where
            #     `hin_id: UInt64 = 0`): the old code reinterpreted the
            #     value's bits as a pointer (`(uint64_t *)_t2` from the
            #     value 0 -> NULL) and the callee's first store through it
            #     segfaulted. Auto-materialize the argument's ADDRESS
            #     instead (the bug report's option (a)): pass `&hin_id`
            #     so the callee's writes through the out-param land in
            #     the caller's own variable -- true aliasing/write-back,
            #     which is exactly what an out-parameter call means. A
            #     non-lvalue argument (call result temp, expression)
            #     gets the same treatment harmlessly: its temp is
            #     addressable memory, so the callee writes into a
            #     discarded temporary instead of crashing ("an
            #     addressable temporary", per the same report).
            # (2) The argument is an OPAQUE HANDLE boxed in an int64_t
            #     that genuinely must be passed through by value -- the
            #     convention this branch was written for (its comment
            #     cites globals). Those keep today's cast-through
            #     behavior unchanged: handles tracked by _actual_types,
            #     anything living in a global (_global_var_types -- the
            #     cited case, and the one place "int64_t holding a real
            #     FFI pointer" is common), any name we can't positively
            #     identify as a declared local, AND every parameter whose
            #     C type isn't pointer-to-numeric-scalar. That last
            #     exclusion is load-bearing: `char *` parameters are
            #     overwhelmingly STRING parameters in this dialect, and an
            #     int64_t-typed local holding a string handle passed to
            #     one must keep the by-value handle pass-through
            #     (confirmed via make check-selfhost: auto-addressing
            #     those regressed mojo.py's own self-compilation with
            #     dozens of GIMPLE errors). Pointer-to-numeric-scalar
            #     (`*UInt64` -> 'uint64_t *', `*Int64` -> 'int64_t *',
            #     ...) is exactly the raw-pointer OUT-parameter spelling
            #     this dialect's FFI/helper surface uses (_mojo_type's
            #     own `*T` mapping), and the only shape BUG-2026-016
            #     reported.
            if (gen._scalar_arg_is_addressable_local(aval)
                    and gimple_ctypes._elem_type(ptype) in gimple_ctypes._PTR_OUT_PARAM_SCALAR_ELEMS
                    and aval in getattr(gen, '_scalar_annotated_locals', ())):
                _ap = gen._new_val(f'{atype} *', f'&{aval}')
                pp = gen._new_temp(ptype)
                gen._emit(f'  {pp} = ({ptype}){_ap};')
                coerced_args.append(pp)
            else:
                # If parameter expects pointer and we have int/int64_t, cast through void*
                # This handles cases where int64_t is an opaque pointer (e.g., from globals)
                ip3 = gen._new_temp('int64_t')
                pp = gen._new_temp(ptype)
                if actual_atype == 'int64_t' or atype == 'int64_t':
                    # GIMPLE: can't redundantly cast int64_t to int64_t when source is global
                    aval_local = gen._ensure_local('int64_t', aval)
                    gen._emit(f'  {ip3} = {aval_local};')
                else:
                    gen._emit(f'  {ip3} = (int64_t){aval};')
                gen._emit(f'  {pp} = ({ptype}){ip3};')
                coerced_args.append(pp)
        elif ptype == 'int64_t' and atype.endswith(' *'):
            # pointer passed where int64_t expected — cast via int64_t
            ip = gen._new_val('int64_t', f'(int64_t){aval}')
            coerced_args.append(ip)
        elif ptype == 'int' and atype in ('int64_t', '_Bool'):
            ct = gen._new_val('int', f'(int){aval}')
            coerced_args.append(ct)
        elif ptype == 'int' and atype.endswith(' *'):
            # char*/pointer passed where int expected — convert via int64_t
            ip = gen._new_temp('int64_t')
            it = gen._new_temp('int')
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {it} = (int){ip};')
            coerced_args.append(it)
        elif ptype.endswith(' *') and atype == 'int':
            # int passed where pointer expected — convert via int64_t
            ip = gen._new_temp('int64_t')
            pp = gen._new_temp(ptype)
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {pp} = ({ptype}){ip};')
            coerced_args.append(pp)
        elif ptype == 'char *' and atype == 'void *':
            # void* to char* conversion
            cp = gen._new_val('char *', f'(char *){aval}')
            coerced_args.append(cp)
        elif ptype == 'void *' and atype == 'char *':
            # char* to void* conversion
            vp = gen._new_val('void *', f'(void *){aval}')
            coerced_args.append(vp)
        elif ptype.endswith(' *') and atype == 'char *':
            # char* passed where other pointer type expected
            ip = gen._new_temp('int64_t')
            pp = gen._new_temp(ptype)
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {pp} = ({ptype}){ip};')
            coerced_args.append(pp)
        elif ptype == 'ModuleLoader *' and atype in ('int', 'int64_t'):
            # Handle ModuleLoader* type coercions
            ip = gen._new_temp('int64_t')
            pp = gen._new_temp('ModuleLoader *')
            gen._emit(f'  {ip} = (int64_t){aval};')
            gen._emit(f'  {pp} = (ModuleLoader *){ip};')
            coerced_args.append(pp)
        elif ptype.endswith(' *') and atype.endswith(' *') and ptype != atype:
            # Two different pointer types (e.g. MojoList * where MojoDict * is
            # declared, or a struct ptr vs Span *): cast via a temp rather than
            # forwarding an un-typed mismatched pointer (review finding #5).
            pp = gen._new_val(ptype, f'({ptype}){aval}')
            coerced_args.append(pp)
        elif ptype and ptype != atype:
            ct = gen._new_temp(ptype)
            gen._safe_coerce_emit(atype, ptype, aval, ct)
            coerced_args.append(ct)
        else:
            coerced_args.append(aval)
    args_str = ', '.join(coerced_args)
    # For imported functions with known C signatures, use the declared return type
    # to avoid "invalid conversion in gimple call" when the caller guessed wrong.
    # Priority: _LIBC_DECLARED _KNOWN_SIGS (C stdlib) > imported_symbols > func_return_types.
    # _KNOWN_SIGS for C stdlib must win because a Mojo fn can shadow a C name (e.g. atan2).
    # But _KNOWN_SIGS may contain stale struct-method entries; only trust it for _LIBC_DECLARED.
    imported_ret = None
    in_libc_known = fname in gen._LIBC_DECLARED and fname in gen._KNOWN_SIGS
    # A C library symbol's real signature is authoritative; a same-named Mojo
    # wrapper (e.g. `def dlopen(...) -> _CPointer` → int64_t) must not override
    # the caller's C return type. Otherwise the void*-returning libc dlopen gets
    # assigned into an int64_t call temp (int-from-pointer error).
    is_libc = fname in gen._LIBC_DECLARED
    if in_libc_known:
        sig_ret = gen._KNOWN_SIGS[fname][0]
        if sig_ret != ret_type:
            imported_ret = sig_ret
    if not imported_ret and not is_libc:
        imported_ret = (gen.imported_symbols.get(fname) or {}).get('c_return_type')
    # Also check func_return_types (Mojo function return types) for same mismatch,
    # but skip if fname is a known C stdlib function (to avoid Mojo shadow overriding).
    if not imported_ret and not in_libc_known and not is_libc and fname in gen.func_return_types:
        fn_ret = gen.func_return_types[fname]
        # Never coerce a used value through a 'void' call temp (would emit an
        # illegal `void t; t = f();`). A 'void' entry here is a shadow — e.g. a
        # Mojo wrapper that shares a name with a value-returning libc symbol
        # reached via external_call — so the caller's explicit ret_type wins.
        if fn_ret != ret_type and fn_ret != 'void':
            imported_ret = fn_ret
    if result_var and imported_ret and imported_ret != ret_type:
        call_tmp = gen._new_temp(imported_ret)
        gen._emit(f'  {call_tmp} = {fname} ({args_str});')
        gen._safe_coerce_emit(imported_ret, ret_type, call_tmp, result_var)
    elif result_var:
        gen._emit(f'  {result_var} = {fname} ({args_str});')
    else:
        gen._emit(f'  {fname} ({args_str});')


def _declared_int_ctype(gen, val: str) -> str | None:
    """The C type a value was *declared* with, when `val` names a plain
    variable/parameter/global (not a temp, literal, or expression).

    This deliberately consults the declaration tables (var_types /
    _global_var_types) rather than the value's *semantic* type. A
    scalar-newtype parameter like `mask: UInt8` is physically declared
    `int64_t` at the ABI level (see `_param_ctype`/`_resolve_type` and the
    ABI-widened `func_param_types` the signature is built from) even
    though the codegen's `_actual_types` records its semantic type as
    `uint8_t`. Any copy of that value into a `uint8_t`-typed local must be
    cast explicitly: GIMPLE rejects the implicit `int64_t` -> `uint8_t`
    narrowing ("non-trivial conversion in 'parm_decl'",
    std/builtin/dtype.mojo `_match(self, mask: UInt8)`), and likewise
    rejects the reverse direction — see `_SCALAR_INT_TYPES`'s comment.

    Returns None when `val` isn't a resolvable plain variable, or its
    declared type isn't a scalar integer (pointers/containers/structs keep
    their existing handling)."""
    if not val or not (val[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'):
        return None
    declared = gen.var_types.get(val)
    if declared is not None:
        return declared if declared in gimple_ctypes._SCALAR_INT_TYPES else None
    declared = gen._global_var_types.get(val)
    if declared is not None:
        # Globals are declared at C level in the module struct; a boxed
        # container global is stored as int64_t regardless of its Mojo
        # type, so the real declared storage type is authoritative for
        # deciding whether a cast is needed.
        real = gen._global_c_decl_types.get(val, declared)
        return real if real in gimple_ctypes._SCALAR_INT_TYPES else None
    return None


def _ensure_local(gen, ctype: str, val: str) -> str:
    """If val is a global variable (not a local temp or constant), load it into
    a local temp first.  GIMPLE requires all cast/unary operands to be registers."""
    is_numeric_literal = bool(val.lstrip('-').replace('.', '', 1).isdigit())
    is_local = (val.startswith('_t') or val.startswith('"') or val.startswith("'")
                or is_numeric_literal)
    if is_local:
        # A bare integer/float literal's own GIMPLE type defaults to
        # 'int' (no '.') or 'double' (has a '.'), regardless of what
        # ctype the CALLER actually needs it typed as — a caller that
        # assigns this return value directly into a temp DECLARED as a
        # different scalar type (e.g. `int64_t _t = <this>;`) hits a
        # real GIMPLE "non-trivial conversion in 'integer_cst'" error,
        # since (unlike ordinary C) GIMPLE requires the RHS of a plain
        # assignment to already have the exact declared type, no
        # implicit int-widening. Confirmed via `Lib/importlib/
        # _bootstrap.py`'s with-statement `__exit__` dummy-None-arg
        # plumbing (_gen_stmt_WithStmt's `_extra_args = [('int64_t',
        # '0')] * n`, reaching `_emit_call`'s `_ensure_local('int64_t',
        # '0')`, then a caller emitting `{temp} = {this_return};`
        # verbatim with no cast of its own — see bugs/CODEGEN_
        # with_stmt_exit_dummy_arg_literal_int64_cast.md). Only cast
        # when the literal's own default type doesn't already match
        # ctype — a plain 'int' literal assigned into an 'int'-typed
        # temp needs no cast (and GIMPLE rejects a cast whose source
        # and destination types are identical as a redundant no-op).
        if is_numeric_literal:
            _native = 'double' if '.' in val else 'int'
            if ctype != _native:
                return f'({ctype}){val}'
        return val
    # Copying a wider-declared scalar into a narrower integer temp is an
    # implicit conversion GIMPLE rejects (e.g. an int64_t ABI parameter
    # copied into a uint8_t temp) — cast explicitly. `_declared_int_ctype`
    # only fires for a genuine *declared-type* mismatch; same-type copies
    # keep the existing bare load.
    declared = gen._declared_int_ctype(val)
    if declared is not None and declared != ctype and ctype in gimple_ctypes._SCALAR_INT_TYPES:
        t = gen._new_temp(ctype)
        gen._emit(f'  {t} = ({ctype}){val};')
        return t
    t = gen._new_val(ctype, f'{val}')
    return t


def _char_to_cstr(gen, typ: str, val: str) -> tuple[str, str]:
    """Convert a char-type value to char * for string operations.
    Returns (new_type, new_val) — if typ is 'char', calls mojo_char_to_str.
    If typ is 'int64_t' and actual type isn't a pointer, also converts.
    Otherwise casts through (char *)(int64_t) for boxed pointers."""
    if typ == 'char':
        return 'char *', gen._call_expr('char *', 'mojo_char_to_str', [('char', val)])
    if typ in ('int', 'int64_t'):
        actual = gen._actual_types.get(val)
        if actual == 'char':
            cv = gen._new_val('char', f'(char){val}')
            return 'char *', gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
        if actual is not None and actual.endswith(' *'):
            # A KNOWN-boxed pointer (a char*/MojoDict*/... value that was
            # type-erased through an int64_t slot elsewhere in this
            # codegen's dynamic-typing convention, tracked explicitly in
            # _actual_types — e.g. `name = node.name` from the A5
            # getattr, where `name` really is a string pointer that was
            # never re-typed as char*) — round-trip the bit pattern back
            # instead of stringifying it. The OLD check (any int64_t with
            # no pointer record → char) truncated such a local to a
            # single byte, so `name in self.var_types` looked up the low
            # byte of the pointer as the key and ALWAYS missed.
            ip = gen._new_val('int64_t', f'(int64_t){val}')
            return 'char *', gen._new_val('char *', f'(char *){ip}')
        # No tracked boxed-pointer origin: this is a genuine numeric Int
        # dict key (e.g. `Dict[Int, V]`'s `d[k] = v` / `k in d` / `d[k]`)
        # — convert it to its decimal string, the same way
        # _lower_dict_literal already does for literal `{intkey: v}`
        # pairs (see its own comment: "Int key 0 -> '0' instead of
        # C-casting the int to char* which produces NULL for 0"). Every
        # OTHER dict-key site (subscript get/set/augmented-assign/`in`/
        # comprehension) used to skip that conversion and just
        # bit-reinterpret the int as a pointer — NULL for 0 (an
        # immediate SIGSEGV the instant the runtime strdup()s/strcmp()s
        # it), a wild unmapped read for any other small int. The
        # previous default here (assume boxed pointer whenever
        # _actual_types has no entry) was backwards: an untracked
        # int64_t is overwhelmingly a real Int, not a pointer — every
        # genuinely-boxed-pointer case in this codegen explicitly
        # registers itself in _actual_types (see the call sites above).
        # Found via box.3d/game/lib/recipes.mojo's
        # `var _fuel_burn_times: Dict[Int, Int] = {}` — `init_recipes()`
        # crashed with `strdup(NULL)` inside `_dict_set_raw_seq` on the
        # very first `_fuel_burn_times[item_id] = ...` (item_id was a
        # genuine, tracked-nowhere `Int` value of 0).
        return 'char *', gen._new_val('char *', f'mojo_str_from_int({val})')
    if typ != 'char *':
        return 'char *', gen._new_val('char *', f'(char *){val}')
    return typ, val


def _resolve_type(gen, ann: str | None) -> str:
    # Map a C-keyword struct name (`auto`) to its renamed form so a bare
    # `auto` annotation resolves to the struct registered under `_kw_auto`.
    if isinstance(ann, str):
        ann = gen._c_kw_struct_renames.get(ann, ann)
    if ann in gen.struct_field_types:
        return f"{ann} *"
    # _mojo_type is a stateless module-level function with no access to
    # struct_field_types, so a pointer-to-a-known-struct annotation like
    # `UnsafePointer[MoveOnly_Int, MutExternalOrigin]` would otherwise
    # fall through _mojo_type's UnsafePointer branch to its int64_t
    # default, even though the element type IS a real, known struct here.
    if isinstance(ann, str) and '[' in ann:
        base, rest = ann.split('[', 1)
        base = base.strip()
        if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
            elem_ann = gimple_ctypes._split_top_level_commas(rest.rstrip(']').strip())[0].strip()
            elem_ann = gen._c_kw_struct_renames.get(elem_ann, elem_ann)
            # Scalar newtypes (Int, UInt8, Bool, ...) ARE real `struct
            # X(...)` definitions in the stdlib and so CAN end up
            # registered in struct_field_types, but the codegen
            # deliberately erases them to raw C scalars everywhere via
            # _TYPE_MAP — that convention must win here, or e.g.
            # alloc[UInt8]'s return type gets wrongly boxed as "UInt8 *"
            # instead of the correct "uint8_t *".
            if elem_ann in gen.struct_field_types and elem_ann not in gimple_ctypes._TYPE_MAP:
                return f"{elem_ann} *"
    # Same gap as above, for Mojo's OTHER raw-pointer spelling: `*T`
    # (`fn f(p: *SomeStruct)`), parsed by mojo_compiler.py as the literal
    # text "*" + T. `_mojo_type` (module-level, no struct_field_types
    # access) now resolves `*Int8`/`*Int64`/... via its own exact-
    # _TYPE_MAP-key check, but a struct element type needs this
    # instance's struct_field_types the same way the UnsafePointer[...]
    # branch above does — otherwise `*SomeStruct` falls through
    # _mojo_type's fallback to the generic int64_t default, same class
    # of bug as the UnsafePointer[MoveOnly_Int, ...] case this docstring
    # already describes.
    if (isinstance(ann, str) and len(ann) > 1 and ann[0] == '*' and ann[1] != '*'):
        elem_ann = gen._c_kw_struct_renames.get(ann[1:].strip(), ann[1:].strip())
        if elem_ann in gen.struct_field_types and elem_ann not in gimple_ctypes._TYPE_MAP:
            return f"{elem_ann} *"
    return gimple_ctypes._mojo_type(ann)


def _infer_param_types(_g, func: gimple_ctypes.FunctionDef,
                       owner_struct: str | None = None) -> dict[str, str]:
    """Infer parameter types from member accesses and function calls in function body.

    If a parameter is accessed with .field, infer it's a struct with that field.
    If a parameter is passed to a known function, infer type from that function.

    `owner_struct`: the StructDef whose method `func` is, when it is one —
    needed ONLY so the decision step below can resolve `self.<member>` AugAssign
    sinks against `_g.struct_field_types`; pure signal collection inside
    analyze_param_usage never touches it (see its Phase 3 memoization note).
    """
    inferred = {}

    # Map builtin/common functions to their first parameter type
    # `len` deliberately excluded: passing a param to `len()` means it's
    # a SIZED CONTAINER (str/list/dict/set/tuple — no single correct C
    # type to default to), not that the param's own type IS `int` —
    # that's len()'s RETURN type, not its argument's type. This entry
    # used to wrongly infer 'int' for any unannotated parameter whose
    # ONLY usage signal was `len(param)` (no subscript/iteration to
    # otherwise identify it as MojoList*/char*), producing a compiled
    # function whose parameter was declared `int` while every real
    # caller passed a genuine pointer (str/list) argument — "passing
    # argument 1 of '<fn>' makes integer from pointer without a cast".
    # Found via Doc/includes/ndiff.py's `def main(args): ... if
    # len(args) != 2: ...` (no subscript/for-loop over `args`
    # anywhere in the function, so `len(args)` was the only signal,
    # and this entry silently won).
    BUILTIN_PARAM_TYPES = {
        'open': 'char *',
        'mojo_open_file': 'char *',
        'print': 'char *',
        'str': 'int',
    }

    # Methods that exist ONLY on Python str (never on list/dict/set), so a
    # `param.method(...)` call using one of these unambiguously identifies
    # `param` as a string even when it's also subscripted/sliced elsewhere
    # in the same function (e.g. `src[i]`, `src[a:b]`) — which otherwise
    # looks identical to list/sequence indexing to this analysis. Without
    # this, any unannotated closure parameter that is both subscripted
    # AND string-only-method-called (a very common shape for hand-rolled
    # char-by-char scanners, e.g. mojo_compiler.py's own
    # `replace_multiline_strings(src)`) was inferred as `MojoList *`
    # instead of `char *`. That produced a compiled function whose `src`
    # parameter was declared as a MojoList* while the caller actually
    # passed a raw `char *` — every `src[i]` then lowered to
    # `mojo_list_get_int(src, i)`, which dereferences the char* as if it
    # were a MojoList struct pointer and reads garbage/crashes
    # (EXC_BAD_ACCESS) on real input. Found via `stage2/mojo --dump`
    # segfaulting in `mojo_list_get_int` called from
    # `py_tokenize_replace_multiline_strings`, with the faulting address
    # literally spelling out the first bytes of the source file's text —
    # proof `src`'s raw string bytes were being read as a pointer.
    STRING_ONLY_METHODS = {
        'find', 'rfind', 'startswith', 'endswith', 'strip', 'lstrip',
        'rstrip', 'split', 'rsplit', 'splitlines', 'replace', 'lower',
        'upper', 'format', 'isalnum', 'isdigit', 'isspace', 'isupper',
        'islower', 'isalpha', 'zfill', 'capitalize', 'title', 'join',
        'partition', 'rpartition', 'swapcase', 'expandtabs', 'casefold',
    }

    # Methods that exist ONLY on Python dict (never on list/set), so a
    # `param.method(...)` call using one of these unambiguously identifies
    # the param as a dict — same reasoning as STRING_ONLY_METHODS above.
    # Found via Tools/unicode/gencodec.py's `marshalmap(name, map,
    # marshalfile)`: the param's ONLY use is `for e,(u,c) in map.items():`,
    # and the bare member-access struct inference below matched the single
    # registered struct that happens to have an `items` FIELD — WithStmt,
    # an unrelated internal AST node (`WithStmt.items: list`) — typing the
    # param `WithStmt *`. Every real dict argument then flowed through a
    # wrong-struct signature, `.items()` fell to opaque runtime dispatch,
    # and the pair loop ran zero times (mojo_unsupported_iter).
    DICT_ONLY_METHODS = {'items', 'keys', 'values', 'setdefault'}

    # Method names shared across the builtin containers. When one of these
    # is CALLED on the param, it is method-dispatch evidence, NOT evidence
    # of a struct whose FIELD happens to share the name — excluded from the
    # accessed-field struct match below for exactly the WithStmt.items
    # reason documented at DICT_ONLY_METHODS.
    BUILTIN_CONTAINER_METHODS = {
        'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'sort',
        'reverse', 'copy', 'index', 'count', 'keys', 'values', 'items',
        'get', 'update', 'setdefault', 'add', 'discard',
    }

    def analyze_param_usage(nodes: list, param_name: str):
        """Analyze how a parameter is used in a list of statements."""
        accessed_fields = set()
        # Members CALLED as methods on the param (`param.items(...)`) —
        # method dispatch, distinct from bare field reads. Consulted to
        # keep builtin-container method names out of the struct-field
        # match (see BUILTIN_CONTAINER_METHODS above).
        called_methods: set = set()
        function_calls = []  # List of (function_name, arg_index)
        is_subscripted = False  # Track if parameter is used with [...]
        is_string_method = False  # Track if param.<str-only-method>(...) is called
        is_dict_method = False  # Track if param.<dict-only-method>(...) is called
        is_iterated = False  # Track if parameter is used as for-loop iterable
        # Track if a single-character subscript of the param (`param[i]`,
        # directly or via a local it was assigned to, e.g. `c = param[i]`)
        # is ever compared against a string literal (`c == '"'`) — a
        # single char of a real Python list would be some non-string
        # element, never legitimately `==`-compared to a quote-character
        # string literal, so this is as unambiguous a "param is a string"
        # signal as a str-only method call, just one indirection removed.
        # Found chasing gimple_codegen's `_lower_slice`/`_decode_str_
        # literal_text` quote-corruption bug back to its real source:
        # mojo_compiler.py's own `_strip_string_prefix_and_quotes(raw)`
        # does `prefix, rest = raw[:n], raw[n:]` (rest is a SLICE of the
        # param, one step removed) then `first = rest[0]; ... if first ==
        # '"' or first == "'": ...` (first is a subscript of THAT, two
        # steps removed) — no str-only method call anywhere, so `raw`
        # (only ever subscripted/sliced, directly or transitively) got
        # inferred as MojoList*, and the caller's real char* argument got
        # force-cast to a MojoList* pointer, corrupting every
        # self-hosted string literal whose own content happens to
        # start/end with a quote. Needs to trace through that whole
        # subscript-of-a-slice-of-the-param chain, not just a single hop.
        is_char_compared = False
        # Every local known to hold a value sliced/subscripted (directly
        # or transitively) FROM the param — `derived_from_param` answers
        # "does this trace back to the param at all", `single_char_vars`
        # (a subset) answers "and is this specific derivation a single
        # CHARACTER (non-slice subscript), not another substring".
        derived_from_param: set = {param_name}
        single_char_vars: set = set()
        # Dict-vs-list disambiguation signals for the param's own
        # subscripts. This runtime has exactly two subscriptable
        # containers — MojoList (int64_t indices) and MojoDict (char*
        # keys) — so a subscript whose KEY is provably a string is
        # impossible for a real list and identifies the param as a dict
        # (Lib/test/support/__init__.py's
        # `set_sanitizer_env_var(env, option)`: `env[name] += f':{option}'`
        # with `name` iterating a tuple of string literals was inferred
        # MojoList*, and the store emitted mojo_list_set_int with a char*
        # key/value — hard -Wint-conversion errors). Any OTHER subscript
        # key (int literal, arithmetic, unknown identifier) or any slice
        # keeps the historical sequence interpretation.
        is_str_key_subscripted = False
        is_nondict_key_subscripted = False
        str_vars: set = set()
        # `self.<member> += <param-derived value>` sinks (root ident name,
        # member name). An augmented assignment whose RHS involves the param
        # is real Python string/list CONCATENATION-INTO evidence, but the
        # scan itself can't tell a str sink from a list sink — only the
        # decision step can, by resolving the member's declared ctypes
        # against struct_field_types (populated from the class's own
        # `self.<member> = <init>` assignments by gen_module's
        # _collect_self_assigns pass). Collected here as pure names; judged
        # there.
        aug_member_targets: set = set()

        def _expr_mentions_param(e):
            """Does expression `e` involve `param_name` directly (a bare
            identifier read, or a subscript/slice OF one)? Deliberately
            shallower than a full walk: concatenation sinks take simple
            values (`self._val += data`, `... += data[0:n]`), and every
            extra shape widened here would widen what counts as "param
            flows into this sink" without adding real certainty."""
            if isinstance(e, gimple_ctypes.IdentExpr):
                return e.name == param_name
            if isinstance(e, gimple_ctypes.SliceExpr):
                return (_expr_mentions_param(e.obj)
                        or (e.start is not None and _expr_mentions_param(e.start))
                        or (e.stop is not None and _expr_mentions_param(e.stop)))
            if isinstance(e, gimple_ctypes.SubscriptExpr):
                return (_expr_mentions_param(e.obj)
                        or _expr_mentions_param(e.index))
            if isinstance(e, gimple_ctypes.BinaryOp):
                return (_expr_mentions_param(e.left)
                        or _expr_mentions_param(e.right))
            if isinstance(e, gimple_ctypes.UnaryOp):
                return _expr_mentions_param(e.operand)
            return False

        def _expr_is_stringish(e):
            if isinstance(e, gimple_ctypes.StringLiteral):
                return True
            if isinstance(e, gimple_ctypes.TstringLiteral):
                return True
            if isinstance(e, gimple_ctypes.IdentExpr) and e.name in str_vars:
                return True
            return False

        def _is_single_char_literal(e):
            return isinstance(e, gimple_ctypes.StringLiteral) and len(e.value) <= 3  # quotes + <=1 char

        def scan_expr(expr):
            """Recursively scan an expression."""
            nonlocal is_subscripted, is_string_method, is_char_compared, is_iterated
            nonlocal is_str_key_subscripted, is_nondict_key_subscripted
            nonlocal is_dict_method
            if isinstance(expr, gimple_ctypes.Comprehension):
                # A list/set/dict/generator comprehension embedded inside
                # an expression (`sum(x**2 for x in values)`,
                # `[f(v) for v in values]` used as a call argument, ...)
                # has a structurally different shape (`.generators[i].
                # iterable`/`.element`/`.conditions`, not simple nested
                # expression fields) that this dispatch never recursed
                # into at all -- `values` being the comprehension's own
                # iterable was silently invisible to this whole
                # analysis, so a parameter used ONLY this way (no plain
                # `for x in values:` statement, no direct subscript)
                # got no type signal and defaulted to int64_t while
                # every real caller passed a genuine MojoList* — found
                # via Tools/lockbench/lockbench.py's `jains_fairness
                # (values)`, whose only two uses of `values` are
                # `sum(values)`/`len(values)` (no signal either, same
                # class of gap `len()` was already excluded from) and
                # `sum(x**2 for x in values)` (this exact shape).
                for gen in expr.generators:
                    if isinstance(gen.iterable, gimple_ctypes.IdentExpr) and gen.iterable.name == param_name:
                        is_iterated = True
                    scan_expr(gen.iterable)
                    for cond in (gen.conditions or []):
                        scan_expr(cond)
                if expr.key is not None:
                    scan_expr(expr.key)
                scan_expr(expr.element)
            elif isinstance(expr, gimple_ctypes.SubscriptExpr):
                # Check if the base (after unwrapping nested subscripts) is the parameter
                base = expr.obj
                while isinstance(base, gimple_ctypes.SubscriptExpr):
                    base = base.obj
                if isinstance(base, gimple_ctypes.IdentExpr) and base.name == param_name:
                    is_subscripted = True
                    if _expr_is_stringish(expr.index):
                        is_str_key_subscripted = True
                    else:
                        is_nondict_key_subscripted = True
                scan_expr(expr.obj)
                scan_expr(expr.index)
            elif isinstance(expr, gimple_ctypes.SliceExpr):
                # Slicing a param means it is an indexable sequence, same as subscript.
                if isinstance(expr.obj, gimple_ctypes.IdentExpr) and expr.obj.name == param_name:
                    is_subscripted = True
                    is_nondict_key_subscripted = True
                scan_expr(expr.obj)
                if expr.start is not None: scan_expr(expr.start)
                if expr.stop is not None: scan_expr(expr.stop)
            elif isinstance(expr, gimple_ctypes.MemberExpr):
                if isinstance(expr.obj, gimple_ctypes.IdentExpr) and expr.obj.name == param_name:
                    accessed_fields.add(expr.member)
                scan_expr(expr.obj)
            elif isinstance(expr, gimple_ctypes.BinaryOp):
                if expr.op == '==':
                    for a, b in ((expr.left, expr.right), (expr.right, expr.left)):
                        is_direct = (isinstance(a, gimple_ctypes.SubscriptExpr)
                                     and not isinstance(a.index, gimple_ctypes.SliceExpr)
                                     and isinstance(a.obj, gimple_ctypes.IdentExpr)
                                     and a.obj.name in derived_from_param)
                        is_indirect = isinstance(a, gimple_ctypes.IdentExpr) and a.name in single_char_vars
                        if (is_direct or is_indirect) and _is_single_char_literal(b):
                            is_char_compared = True
                if expr.op == '+':
                    # `param + <string literal>` / `<string literal> +
                    # param` (directly, or through a local already known
                    # to hold a string) — real Python str concatenation,
                    # which only type-checks when BOTH operands are
                    # strings, so the param is one. Unambiguous even when
                    # the param is ALSO subscripted elsewhere (a list
                    # element + str would be a TypeError in real Python).
                    # Found via Lib/ctypes/macholib/dyld.py's `_inject`
                    # generator: `yield path[:-len('.dylib')] + suffix +
                    # '.dylib'` — `suffix` had no other string signal (no
                    # str-only method call, no subscript) and defaulted
                    # to int64_t, so the coroutine body's co_yield hit
                    # "invalid conversion from 'int64_t' to 'char*'".
                    for _a, _b in ((expr.left, expr.right), (expr.right, expr.left)):
                        _a_param = (isinstance(_a, gimple_ctypes.IdentExpr)
                                    and _a.name == param_name)
                        if not _a_param:
                            continue
                        if _expr_is_stringish(_b):
                            is_string_method = True
                        elif (isinstance(_b, gimple_ctypes.IdentExpr)
                                and _b.name != param_name
                                and _b.name in str_vars):
                            is_string_method = True
                scan_expr(expr.left)
                scan_expr(expr.right)
            elif isinstance(expr, gimple_ctypes.CompareChain):
                for o in expr.operands: scan_expr(o)
            elif isinstance(expr, gimple_ctypes.UnaryOp):
                scan_expr(expr.operand)
            elif isinstance(expr, gimple_ctypes.CallExpr):
                # Track which functions this parameter is passed to
                if isinstance(expr.func, gimple_ctypes.IdentExpr):
                    func_name = expr.func.name
                    for i, arg in enumerate(expr.args):
                        if isinstance(arg, gimple_ctypes.IdentExpr) and arg.name == param_name:
                            function_calls.append((func_name, i))
                elif isinstance(expr.func, gimple_ctypes.MemberExpr):
                    # Method-call evidence is recognized through a SLICE or
                    # SUBSCRIPT of the param too (`s[:-1].split(",")`,
                    # ftplib.py's mlsd): Python str methods return strs, so
                    # calling one on any slice/subscript chain rooted at the
                    # param proves the root is a string exactly as strongly
                    # as a direct call — previously only the DIRECT
                    # `param.method(...)` shape was recognized, so a param
                    # whose only string evidence was indirect fell through
                    # to the subscript/slice default below and got inferred
                    # MojoList*.
                    _meth_recv = expr.func.obj
                    while isinstance(_meth_recv, (gimple_ctypes.SubscriptExpr,
                                                  gimple_ctypes.SliceExpr)):
                        _meth_recv = _meth_recv.obj
                    # param.<str-only-method>(...) — see STRING_ONLY_METHODS
                    # comment above: unambiguous evidence param is a string,
                    # even if it's also subscripted elsewhere.
                    if (isinstance(expr.func.obj, gimple_ctypes.IdentExpr)
                            and expr.func.obj.name == param_name
                            and expr.func.member in STRING_ONLY_METHODS):
                        is_string_method = True
                    # <slice/subscript-of-param>.<str-only-method>(...) —
                    # the indirect twin just above.
                    if (_meth_recv is not expr.func.obj
                            and isinstance(_meth_recv, gimple_ctypes.IdentExpr)
                            and _meth_recv.name == param_name
                            and expr.func.member in STRING_ONLY_METHODS):
                        is_string_method = True
                    # param.<dict-only-method>(...) — same unambiguous
                    # "param is a dict" evidence (see DICT_ONLY_METHODS).
                    if (isinstance(expr.func.obj, gimple_ctypes.IdentExpr)
                            and expr.func.obj.name == param_name):
                        if expr.func.member in DICT_ONLY_METHODS:
                            is_dict_method = True
                        if expr.func.member in BUILTIN_CONTAINER_METHODS:
                            called_methods.add(expr.func.member)
                    # Handle re.sub(pattern, fn, src) → src (index 2) is char*
                    if (isinstance(expr.func.obj, gimple_ctypes.IdentExpr)
                            and expr.func.obj.name == 're'
                            and expr.func.member == 'sub'
                            and len(expr.args) >= 3):
                        if isinstance(expr.args[2], gimple_ctypes.IdentExpr) and expr.args[2].name == param_name:
                            function_calls.append(('__re_sub_src', 2))
                    # os.path.*(param, ...) — basename/splitext/expanduser/
                    # abspath/dirname/exists/join all take char* path
                    # arguments (see the os.path.* block in lower_expr).
                    # Not tracked before: a MemberExpr call func (anything
                    # but the re.sub special case above) was silently
                    # ignored here, so a parameter *only* ever used as
                    # os.path.basename(param) got no type hint at all and
                    # defaulted to int64_t. Real bug found via
                    # build_executable(input_file, ...) in mojo.py, where
                    # input_file is used via
                    # os.path.basename(os.path.splitext(input_file)) —
                    # the parameter held a real char* pointer throughout,
                    # just declared with the wrong C type, so print(x)
                    # showed a raw address instead of the string.
                    elif (isinstance(expr.func.obj, gimple_ctypes.MemberExpr)
                            and isinstance(expr.func.obj.obj, gimple_ctypes.IdentExpr)
                            and expr.func.obj.obj.name == 'os'
                            and expr.func.obj.member == 'path'
                            and expr.func.member in (
                                'basename', 'splitext', 'expanduser',
                                'abspath', 'dirname', 'exists', 'join')):
                        for i, arg in enumerate(expr.args):
                            if isinstance(arg, gimple_ctypes.IdentExpr) and arg.name == param_name:
                                function_calls.append(('__os_path_arg', i))
                scan_expr(expr.func)
                for arg in expr.args:
                    scan_expr(arg)

        def scan_nodes(node_list):
            """Recursively scan a list of statements."""
            nonlocal is_iterated
            def _track_derivation(target, value):
                """`x = <subscript/slice of something already known to
                derive from param>` — propagate that knowledge to `x` too,
                so a chain like `rest = raw[n:]` then `first = rest[0]`
                (two hops from the param) is still recognized. Single-index
                subscripts additionally join single_char_vars (a single
                CHARACTER, eligible for the `== '"'`-style check);  slices
                only join derived_from_param (still a string/substring,
                not a lone char)."""
                if not isinstance(target, gimple_ctypes.IdentExpr):
                    return
                if (isinstance(value, gimple_ctypes.SubscriptExpr)
                        and not isinstance(value.index, gimple_ctypes.SliceExpr)
                        and isinstance(value.obj, gimple_ctypes.IdentExpr)
                        and value.obj.name in derived_from_param):
                    single_char_vars.add(target.name)
                    derived_from_param.add(target.name)
                elif (isinstance(value, gimple_ctypes.SliceExpr)
                        and isinstance(value.obj, gimple_ctypes.IdentExpr)
                        and value.obj.name in derived_from_param):
                    derived_from_param.add(target.name)
            for node in node_list:
                if isinstance(node, gimple_ctypes.AssignStmt):
                    if isinstance(node.target, gimple_ctypes.TupleExpr) and isinstance(node.value, gimple_ctypes.TupleExpr):
                        # `prefix, rest = raw[:n], raw[n:]` — pair up each
                        # target/value slot, same as mojo_compiler.py's own
                        # `_strip_string_prefix_and_quotes`.
                        for t_el, v_el in zip(node.target.elements, node.value.elements):
                            _track_derivation(t_el, v_el)
                    else:
                        _track_derivation(node.target, node.value)
                    if (isinstance(node.target, gimple_ctypes.IdentExpr)
                            and isinstance(node.value, gimple_ctypes.StringLiteral)):
                        str_vars.add(node.target.name)
                    scan_expr(node.target)
                    scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.ExprStmt):
                    scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.ReturnStmt):
                    if node.value:
                        scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.IfStmt):
                    scan_expr(node.condition)
                    scan_nodes(node.then_body)
                    if node.else_body:
                        scan_nodes(node.else_body)
                    for _, elif_body in node.elifs:
                        scan_nodes(elif_body)
                elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
                    if isinstance(node, gimple_ctypes.WhileStmt):
                        scan_expr(node.condition)
                    if isinstance(node, gimple_ctypes.ForStmt):
                        # Detect `for x in <param>:` — evidence param is a list
                        it = node.iterable
                        if isinstance(it, gimple_ctypes.IdentExpr) and it.name == param_name:
                            is_iterated = True
                        # `for name in ('A', 'B', ...):` — every element of
                        # an all-string-literal tuple/list/set literal is a
                        # string, so the loop target is a string variable (a
                        # dict-key source for `param[name]` subscripts).
                        if (isinstance(it, (gimple_ctypes.TupleExpr,
                                            gimple_ctypes.ListExpr,
                                            gimple_ctypes.SetExpr))
                                and it.elements
                                and all(isinstance(el, gimple_ctypes.StringLiteral)
                                        for el in it.elements)):
                            tgt = node.target
                            if isinstance(tgt, gimple_ctypes.IdentExpr):
                                str_vars.add(tgt.name)
                            elif isinstance(tgt, str):
                                str_vars.add(tgt)
                        scan_expr(node.iterable)
                    scan_nodes(node.body)
                    if node.else_body:
                        scan_nodes(node.else_body)
                elif isinstance(node, gimple_ctypes.AugAssignStmt):
                    scan_expr(node.target)
                    scan_expr(node.value)
                    # `self.<member> += <param-derived>` — record the sink
                    # member for the decision step (see aug_member_targets'
                    # declaration above). Found via Tools/gdb/libpython.py's
                    # TruncatedStringIO.write(self, data): both of data's
                    # non-len uses are `self._val += data` /
                    # `self._val += data[0:n]`, and __init__ declares
                    # `self._val = ''` — so struct_field_types knows the sink
                    # is char* and real Python semantics (str += <list> is a
                    # TypeError) make the param one too. Without this signal,
                    # the slice alone typed data MojoList*, the body lowered
                    # len()/slice as list ops against a char* self->_val, and
                    # the += emitted raw `char * + MojoList *` pointer
                    # addition — gcc -fgimple "internal compiler error: in
                    # build2, at tree.cc" (bugs/
                    # COMPILE_FAIL_Tools_gdb_libpython.md).
                    if isinstance(node.target, gimple_ctypes.MemberExpr) \
                            and _expr_mentions_param(node.value):
                        _aug_root = node.target.obj
                        while isinstance(_aug_root, gimple_ctypes.MemberExpr):
                            _aug_root = _aug_root.obj
                        if isinstance(_aug_root, gimple_ctypes.IdentExpr):
                            aug_member_targets.add((_aug_root.name,
                                                    node.target.member))
                elif isinstance(node, gimple_ctypes.MultiAssignStmt):
                    for t in node.targets:
                        scan_expr(t)
                    scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.VarDecl):
                    if node.value:
                        scan_expr(node.value)
                elif isinstance(node, gimple_ctypes.WithStmt):
                    # Scan the context expressions (e.g., open(input_file))
                    for item in node.items:
                        scan_expr(item.expr)
                    scan_nodes(node.body)
                elif isinstance(node, gimple_ctypes.TryStmt):
                    scan_nodes(node.body)
                    for handler in node.handlers:
                        if handler.exc_type:
                            scan_expr(handler.exc_type)
                        scan_nodes(handler.body)
                    if node.else_body:
                        scan_nodes(node.else_body)
                    if node.finally_body:
                        scan_nodes(node.finally_body)

        scan_nodes(nodes)
        return (accessed_fields, function_calls, is_subscripted, is_string_method,
                is_iterated, is_char_compared, is_str_key_subscripted,
                is_nondict_key_subscripted, called_methods, is_dict_method,
                aug_member_targets)

    # For each parameter without a type annotation, infer from usage
    for pname, ptype in func.params:
        if ptype is None:
            # Phase 3 (bugs/hard/PERF_nested_module_compile_walk_ast_
            # quadratic_rescan.md): `analyze_param_usage` is an
            # expensive recursive body scan and a PURE function of
            # (func.body, pname) — no `self.*` state read anywhere in
            # scan_nodes/scan_expr (confirmed by inspection) — so its
            # raw usage-signal result is memoized here, keyed by
            # id(func)+pname, shared tree-wide via
            # `self._param_usage_scan_cache` exactly like
            # `_field_scan_var_cache` (Phase 2). Only the SIGNALS are
            # cached, not the final inferred type below, which also
            # depends on `self.struct_field_types` (grows monotonically
            # during compilation — the same time-dependent-filter trap
            # Phase 2 already had to work around) and must therefore
            # still be recomputed fresh on every call.
            _pu_key = (id(func), pname)
            _pu_cached = _g._param_usage_scan_cache.get(_pu_key)
            if _pu_cached is not None:
                (fields_accessed, function_calls, is_subscripted, is_string_method,
                 is_iterated, is_char_compared, is_str_key_subscripted,
                 is_nondict_key_subscripted, called_methods, is_dict_method,
                 aug_member_targets) = _pu_cached
            else:
                (fields_accessed, function_calls, is_subscripted, is_string_method,
                 is_iterated, is_char_compared, is_str_key_subscripted,
                 is_nondict_key_subscripted, called_methods, is_dict_method,
                 aug_member_targets
                 ) = analyze_param_usage(func.body, pname)
                _g._param_usage_scan_cache[_pu_key] = (
                    fields_accessed, function_calls, is_subscripted, is_string_method,
                    is_iterated, is_char_compared, is_str_key_subscripted,
                    is_nondict_key_subscripted, called_methods, is_dict_method,
                    aug_member_targets)

            # If passed to isinstance() as first arg, it's polymorphic → keep as int64_t
            is_polymorphic = any(
                fn == 'isinstance' and ai == 0
                for fn, ai in function_calls
            )
            if is_polymorphic:
                continue  # leave as int64_t (default for unannotated)

            # If parameter is subscripted OR iterated (for x in param:), it's
            # indexable (list/dict/etc.) — UNLESS it's also called with a
            # str-only method (STRING_ONLY_METHODS above), in which case
            # indexing is char-by-char string scanning and the real type is
            # char*, not MojoList*. Check subscript/iteration FIRST to
            # override generic function-call inference like len() either way.
            if is_subscripted or is_iterated:
                if is_str_key_subscripted and not is_nondict_key_subscripted:
                    # Every provable subscript key is a string (a string
                    # literal, f-string, or a local bound to one) and there
                    # is no int-keyed subscript/slice anywhere — impossible
                    # for a real list under this runtime's int64_t-index
                    # lists, so the param is a dict. See the signals'
                    # declaration above for the motivating repro.
                    inferred[pname] = 'MojoDict *'
                else:
                    # `self.<member> += <param>` evidence: every such sink
                    # member whose declared ctype is resolvable must be char*
                    # (and at least one sink must exist) — a genuine list
                    # operand on a str sink would be a TypeError in real
                    # Python. Requires owner_struct to resolve `self`;
                    # unresolvable sinks make this signal silent (no flip),
                    # never wrong. Motivating repro in aug_member_targets's
                    # declaration above.
                    _aug_into_str = (
                        bool(aug_member_targets) and owner_struct is not None
                        and all(
                            _root == 'self'
                            and _g.struct_field_types.get(owner_struct, {}).get(_member) == 'char *'
                            for _root, _member in aug_member_targets))
                    inferred[pname] = 'char *' if (is_string_method or is_char_compared
                                                   or _aug_into_str) else 'MojoList *'

            # If not subscripted, try to infer from function calls
            elif function_calls:
                for func_name, arg_index in function_calls:
                    # re.sub src argument (index 2) is always char*
                    if func_name == '__re_sub_src':
                        inferred[pname] = 'char *'
                        break
                    # os.path.*(param) — see the MemberExpr scan above
                    if func_name == '__os_path_arg':
                        inferred[pname] = 'char *'
                        break
                    # Infer from known function signatures
                    sig = _g._KNOWN_SIGS.get(func_name)
                    if sig is not None and arg_index < len(sig[1]):
                        inferred[pname] = sig[1][arg_index]
                        break
                    # For first argument (index 0) of known functions, use known types
                    if arg_index == 0 and func_name in BUILTIN_PARAM_TYPES:
                        inferred[pname] = BUILTIN_PARAM_TYPES[func_name]
                        break
                    # map(fn, iterable) — the iterable is arg index 1 (not 0,
                    # unlike list()/sorted()/len() above), and it must come out
                    # pointer-shaped (MojoList *) so it round-trips through
                    # mojo_map's `void *` iterable parameter/return instead of
                    # defaulting to int64_t, which produces a real GCC
                    # -Wint-conversion error at the mojo_map call site (passing
                    # an int64_t where mojo_map expects void*) — see
                    # bugs/CODEGEN_map_over_untyped_param_arg.md.
                    if func_name == 'map' and arg_index == 1:
                        inferred[pname] = 'MojoList *'
                        break

            # If no type inferred from functions, try from struct member accesses
            # Only infer struct type if exactly one struct matches (avoid ambiguity)
            if pname not in inferred and fields_accessed:
                # A member CALLED as a builtin-container method on the param
                # (`map.items()`) is method dispatch, not field evidence —
                # without this exclusion the single registered struct with a
                # same-named FIELD won (WithStmt.items → `WithStmt *` for
                # gencodec.py's marshalmap/python_mapdef_code `map` params).
                struct_evidence = fields_accessed - (
                    called_methods & BUILTIN_CONTAINER_METHODS)
                matches = [
                    sname for sname, sfields in _g.struct_field_types.items()
                    if struct_evidence
                    and all(f in sfields for f in struct_evidence)
                ]
                if len(matches) == 1:
                    inferred[pname] = f"{matches[0]} *"
            # A dict-only method call with no better signal: the param is a
            # dict (see DICT_ONLY_METHODS above).
            if pname not in inferred and is_dict_method:
                inferred[pname] = 'MojoDict *'

            # Last resort: string-only evidence (a str-only method call or
            # string concatenation, with no field access suggesting a
            # struct) — see the BinaryOp '+' scan above for the motivating
            # dyld.py `suffix` shape.
            if pname not in inferred and is_string_method and not fields_accessed:
                inferred[pname] = 'char *'

    return inferred


def _declare_var(gen, name: str, ctype: str, elem: str | None = None, force: bool = False):
    """Register a C-level declaration for Python local `name`.

    Default (force=False): first-decl-wins — if `name` was already
    declared (e.g. the SAME loop-variable name reused across two
    separate sibling `for` loops with different element types), this
    is a deliberate no-op; later reads keep coercing to the FIRST
    declared type. Load-bearing; do not change.

    force=True is for the one case that needs the OPPOSITE behavior:
    a `for` loop whose target name self-shadows its own iterable
    (`for tail in tail:`) — by the time `_declare_var(var, elem)` runs
    for the loop target, `var` is already registered (as the
    iterable's own type) from BEFORE the loop even started, so the
    default no-op guard would leave the stale type/declaration in
    place. force=True mints a genuinely fresh, non-colliding C
    identifier for `name`, records the rename in `self._c_names` (so
    `_lower_IdentExpr`'s `_c_names.get(name, name)` picks it up for
    every subsequent read/write of `name` in the loop body), and
    overrides `self.var_types[name]`/`self._elem_types[name]` to the
    new, correct type — never touching the OLD declaration (still
    valid C, just no longer reachable under `name`).
    """
    if force and name in gen.var_types:
        gen.temp_counter += 1
        import re as _re
        safe = _re.sub(r'[^a-zA-Z0-9_]', '_', name.strip('`'))
        if safe and safe[0].isdigit():
            safe = '_' + safe
        c_name = f"_shadow{gen.temp_counter}_{safe}"
        gen._c_names[name] = c_name
        gen.decls.append(f"  {ctype} {c_name};")
        gen.var_types[name] = ctype
        if elem is not None:
            gen._elem_types[name] = elem
        else:
            gen._elem_types.pop(name, None)
        return
    if name not in gen.var_types:
        # Strip backtick-quoted Mojo identifiers (e.g. `6bit` → _6bit)
        if name.startswith('`') and name.endswith('`') and len(name) > 2:
            inner = name[1:-1]
            if inner and inner[0].isdigit():
                inner = '_' + inner
            import re as _re
            c_name = _re.sub(r'[^a-zA-Z0-9_]', '_', inner)
            gen._c_names[name] = c_name
            gen.decls.append(f"  {ctype} {c_name};")
            gen.var_types[name] = ctype
            if elem is not None:
                gen._elem_types[name] = elem
            return
        # Rename C keywords, macro names, and C library functions to avoid conflicts
        if name in gimple_ctypes._C_PARAM_EXTRA_KEYWORDS or name in gimple_ctypes._C_MACRO_NAMES:
            c_name = f"_kw_{name}"
        elif name in gimple_ctypes._C_KEYWORDS:
            c_name = f"_{name}"
        elif name in gimple_ctypes._C_RESERVED_FUNCS:
            # Local variable shadows a C library function; rename to avoid
            # "invalid call to non-function" when the function is called later
            c_name = f"_var_{name}"
        elif (name in gen.imported_symbols
              and gen.imported_symbols[name].get('return_type', 'int64_t') != 'unknown'):
            # Local variable shadows an imported *function* (not a module import) —
            # rename the local so the extern decl and local variable don't conflict.
            # Module imports have return_type='unknown'; functions default to 'int64_t'.
            c_name = f"_local_{name}"
        else:
            c_name = name
        if c_name != name:
            gen._c_names[name] = c_name
        gen.decls.append(f"  {ctype} {c_name};")
        gen.var_types[name] = ctype
    if elem is not None:
        gen._elem_types[name] = elem


def _write_dest(gen, name: str) -> str:
    """Return the C lvalue for a write to variable `name`.
    Inside a closure, captured variables must be written through the env pointer."""
    if name in gen._captures and gen._env_param:
        mut_ptr = getattr(gen, '_gimple_mut_ptr', None)
        if mut_ptr and name in mut_ptr:
            # `{mut}`-capture-spec (ClosureInfo.mut_names): the env
            # field is a POINTER to the real outer local, preloaded
            # into `mut_ptr[name]` once at closure entry (see
            # _gen_lifted_closure) -- dereference it so the write
            # lands on the outer local itself, not a private copy.
            return f'*{mut_ptr[name]}'
        return f'{gen._env_param}->{gimple_ctypes._c_field_name(name)}'
    if name in gen._boxed_mut_locals:
        # This function's OWN local is heap-boxed (a pointer variable,
        # `{ctype} * name`) because some nested closure captures it BY
        # REFERENCE -- see _seed_mut_captured_local_types's docstring.
        # Dereference the pointer directly (no need to preload: unlike
        # `_gimple_mut_ptr` above, this name IS already a plain,
        # directly-named local pointer, not behind a struct
        # component_ref, so `*name` is already valid GIMPLE).
        return f'*{gen._cname(name)}'
    # A `global x` declaration inside a nested function, OR a plain
    # top-level statement genuinely AT module scope (no `global` needed
    # there — see _gen_stmt_AssignStmt's identical `_in_toplevel_gen`
    # check, which this mirrors): both need the write routed to the
    # module globals struct field, not a bare (never-declared) local.
    # Missing the `_in_toplevel_gen` half of this meant ANY top-level
    # augmented assignment to a global (`X += (4,)`, no enclosing
    # function at all — real Python code, e.g. the stdlib's own
    # _compat_pickle.py: `PYTHON2_EXCEPTIONS += ("WindowsError",)`)
    # emitted a write to an undeclared bare local ("PYTHON2_EXCEPTIONS
    # undeclared (first use in this function)") instead of the global —
    # a hard compile failure, not just a silently-dropped update.
    if (name in gen._global_var_types
            and (gen._in_toplevel_gen
                 or name in getattr(gen, '_func_declared_globals', ())
                 # BUG-2026-018 (box.3d/game test_framework): a write to a
                 # bare name that is THIS module's own global, from a
                 # function that never declared `global name`, must still
                 # land on the globals struct — the interpreter mutates the
                 # module binding through its dynamic scope chain (8/8 in
                 # test_field_access.mojo), while the compiled side used to
                 # declare a fresh LOCAL here and drop every increment
                 # (`_passed = _passed + 1` in check() wrote a dead temp;
                 # every suite printed 0/0). This mirrors the IdentExpr
                 # READ path's exact condition (un-shadowed + owned by this
                 # module or unowned), keeping reads and writes on the SAME
                 # storage — before this, the read half of `_passed + 1`
                # already resolved to the global while the write went to a
                # local.
                 or (not gen._in_toplevel_gen
                     and name not in gen.var_types
                     and getattr(gen, '_global_to_module', {}).get(name) in (
                         None, gen.module_name or "root")))):
        # `global x` declared in this function — write to the module
        # globals struct, mirroring the AssignStmt write path's routing
        # (otherwise AugAssign `x += 1` on a global emitted a LOCAL
        # write, leaving the global unchanged: "counter undeclared").
        #
        # Always target THIS module's own struct (self._current_module_
        # ctx), never `_global_to_module.get(name)` — that map is a
        # SHARED, whole-transitive-tree, name-keyed "first module to
        # claim this bare name wins" map (see gen_module's Phase 1.7 /
        # "Module-level globals" passes and bugs/hard/CODEGEN_module_
        # globals_cross_contamination_via_imported_stmts.md), so when
        # two genuinely DIFFERENT modules each declare their own
        # same-named top-level global (e.g. every file's own `HERE =
        # ...`), it can point at whichever module happened to be
        # scanned FIRST — not necessarily this one. But a `global name`
        # statement (or a bare top-level statement) unambiguously means
        # "THIS function's/THIS statement's own enclosing module's
        # global" under real Python scoping, regardless of what any
        # OTHER module also happens to call itself — and Mechanism 1's
        # fix (that same doc) already guarantees this module's own
        # struct genuinely has a field for `name` whenever this branch
        # fires, since its globals-struct scan is scoped to this
        # module's own statements only. Mirrors _gen_stmt_AssignStmt's
        # and _gen_stmt_MultiAssignStmt's own `_in_toplevel_gen`
        # branches, which already use this exact same direct-current-
        # module routing for the identical reason.
        safe_module = gimple_ctypes._c_field_name(gen._current_module_ctx or "root")
        return f"_{safe_module}_globals.{gimple_ctypes._c_field_name(name)}"
    return gen._cname(name)


def _seed_mut_captured_local_types(gen, func_name: str):
    """For every local of `func_name` that some nested closure captures
    BY REFERENCE (ClosureInfo.mut_names), declare it as a heap-boxed
    POINTER (`self._boxed_mut_locals[name] = pointee_ctype`) instead of
    an ordinary scalar, and register the pointer-typed declaration now,
    before that local's own VarDecl statement is compiled (`_declare_
    var` is a no-op for a name already in `var_types` -- the same
    "declared by an earlier pass" mechanism `_inferred_var_types`
    already relies on, see `_enclosing_scope_with_locals`'s docstring).

    Boxing (not just taking `&local` of an ordinary stack scalar, this
    method's first design) is required, not a style choice: `-fgimple`
    rejects a stack local's address being taken ANYWHERE in the
    function if that same local is also cast-assigned or directly
    `return`ed elsewhere in the SAME function -- confirmed via a
    hand-reduced repro ("non-register as LHS of unary operation" /
    "invalid operand in return statement") after this by-reference-
    capture feature's own stdlib-dylib regression check hit it for
    real on `std/memory/span.mojo`'s `Span.count` (`var count = 0`,
    later `return count` in the SAME function that also captures
    `count` by reference into a nested `do_count` closure -- exactly
    this shape). A never-address-taken pointer local sidesteps the
    restriction entirely: ordinary GIMPLE rules apply to the pointer
    variable itself, and only its separately-allocated pointee is
    dereferenced.

    `_gen_stmt_VarDecl`/`_lower_IdentExpr`/`_write_dest`/`_type_of`
    each consult `self._boxed_mut_locals` to malloc the box at
    declaration time and route every later read/write through a
    dereference instead of a bare identifier."""
    for ci in getattr(gen, '_all_closures', {}).get(func_name, {}).values():
        cap_types = dict(ci.captures)
        for mn in ci.mut_names:
            if mn in cap_types and mn not in gen.var_types:
                ctype = cap_types[mn]
                gen._boxed_mut_locals[mn] = ctype
                # _declare_var (not a bare var_types assignment): must
                # actually EMIT the C declaration here too, since this
                # runs before the local's own VarDecl statement is
                # compiled -- `_declare_var` is a no-op (by design) for
                # a name already in `var_types`, so if we only set the
                # dict entry without also declaring it, nothing would
                # ever emit the real C declaration at all (a real
                # "'name' undeclared" gcc error, hit and fixed during
                # this feature's own verification).
                gen._declare_var(mn, f"{ctype} *")


def _emit_mut_local_box_allocs(gen):
    """Allocate the heap box for every heap-boxed mutable local (see
    _seed_mut_captured_local_types) ONCE, in the function's prologue.

    History: the box used to be allocated by _gen_stmt_VarDecl at the
    local's `var x = ...` statement, which silently assumed the first
    binding of any `{mut}`-captured local is always a Mojo-style VarDecl.
    Real Python source (the compiler's other first-class input -- e.g.
    Tools/cases_generator/analyzer.py's `nonlocal next_opcode` closure,
    whose first binding is a PLAIN `next_opcode = 1` AssignStmt) never
    goes through _gen_stmt_VarDecl at all, so the box was never
    allocated while every read/write still dereferenced the pointer --
    a write through an uninitialized pointer local (observed as a NULL
    or garbage-address segfault mid-function). Allocating unconditionally
    here also fixes two latent identity hazards of the per-statement
    scheme: a VarDecl re-executed by its enclosing loop re-malloc'd a
    fresh box each iteration (the nested closure's env kept pointing at
    the stale one, so nonlocal updates after rebinding silently split
    into two cells), and a first binding lexically inside one branch but
    executed via another path left the box unallocated on that path.
    Prologue allocation gives the box exactly-once, call-scoped
    semantics -- matching Python's own per-call cell model. Must run
    AFTER _seed_mut_captured_local_types (which emitted the `{ctype} *
    name` declarations) and BEFORE any body statement; both plain-
    function and struct-method generation call it immediately after
    seeding for exactly that reason. The malloc/cast two-step mirrors
    the env-struct allocator's pattern (`-fgimple` rejects a direct
    `name = ({ctype} *) malloc (...)` single statement, and needs a
    literal byte count rather than `sizeof(scalar)` -- see
    _SCALAR_CTYPE_SIZE's docstring)."""
    for mn in sorted(gen._boxed_mut_locals):
        ctype = gen._boxed_mut_locals[mn]
        cname = gen._cname(mn)
        vp = gen._new_val('void *', f"malloc ({gimple_codegen._SCALAR_CTYPE_SIZE.get(ctype, 8)})")
        gen._emit(f"  {cname} = ({ctype} *) {vp};")


def _new_jbp_temp(gen) -> str:
    gen.temp_counter += 1
    name = f"_jbp{gen.temp_counter}"
    gen.decls.append(f"  jmp_buf *{name};")
    return name


def _closure_info_for_ident(gen, name: str):
    """Resolve a bare identifier reference to the ClosureInfo of the
    nested function it names, or None if `name` is not a closure in
    scope. Checks the current function's own registered closures (a
    closure referenced from its own enclosing body — e.g. `return add`
    inside `make_adder`) and, while compiling a lifted closure or
    lambda body, the ENCLOSING function's closures too (a sibling
    nested function referenced as a value — the same scoping
    `_lower_call`'s `_lower_outer_closure_call` already gets via
    `_lambda_outer_closures`)."""
    _cur = getattr(gen, '_all_closures', {}).get(gen.current_func_name, {})
    ci = _cur.get(name)
    if ci is not None:
        return ci
    return getattr(gen, '_lambda_outer_closures', {}).get(name)


def _collect_return_types(gen, stmts: list, acc: list):
    """Collect return-expression C types from all ReturnStmt nodes."""
    for node in stmts:
        if isinstance(node, gimple_ctypes.ReturnStmt):
            acc.append('void' if node.value is None else gen._quick_type(node.value))
        elif isinstance(node, gimple_ctypes.IfStmt):
            gen._collect_return_types(node.then_body, acc)
            for _, eb in node.elifs:
                gen._collect_return_types(eb, acc)
            if node.else_body:
                gen._collect_return_types(node.else_body, acc)
        elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
            gen._collect_return_types(node.body, acc)
        elif isinstance(node, gimple_ctypes.TryStmt):
            gen._collect_return_types(node.body, acc)
            for h in node.handlers:
                gen._collect_return_types(h.body, acc)
            if node.else_body:
                gen._collect_return_types(node.else_body, acc)
            if node.finally_body:
                gen._collect_return_types(node.finally_body, acc)
        elif isinstance(node, gimple_ctypes.WithStmt):
            gen._collect_return_types(node.body, acc)


def _coerce_to_type(gen, src_type: str, dst_type: str, value: str) -> str:
    """
    Generic type coercion routine: converts value from src_type to dst_type.
    Returns the properly cast value (may emit temp assignments as needed).

    Uses existing _safe_coerce_emit logic via temp variable assignment.
    Works for ANY type pair without function-name awareness.
    Scales to 1M functions - ONE routine, not 1M special cases.
    """
    if src_type == dst_type:
        return value

    # Use _safe_coerce_emit to handle the coercion via a temp
    result = gen._new_temp(dst_type)
    gen._safe_coerce_emit(src_type, dst_type, value, result)
    return result


def _infer_return_type(gen, body: list) -> str:
    """Infer return type by scanning body for ReturnStmt nodes."""
    acc: list[str] = []
    gen._collect_return_types(body, acc)
    return gimple_ctypes.TypeLattice.join_all(acc) if acc else 'void'

def _quick_container_elem(gen, node) -> str | None:
    """Syntactic container ELEMENT type of a value expression, or None when
    it can't be statically determined. Identifier elements resolve through
    the current function's local container-element map (var_types is empty
    during Pass 2c); call elements resolve through _return_elem_types so
    the fixpoint propagates callee elem types to their callers."""
    if isinstance(node, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr)):
        return gen._prepass_list_elem(node.elements)
    if isinstance(node, gimple_ctypes.Comprehension):
        # `[f(x) for _, x in it]` — element type is the mapped expression's
        # container-elem (or scalar-leaf) type.
        return gen._quick_container_elem(node.element)
    if isinstance(node, gimple_ctypes.TernaryExpr):
        a = gen._quick_container_elem(getattr(node, 'if_true', None) or getattr(node, 'body', None))
        b = gen._quick_container_elem(getattr(node, 'if_false', None) or getattr(node, 'orelse', None))
        if a and b:
            return gimple_ctypes.TypeLattice.join_all([a, b])
        return a or b
    if isinstance(node, gimple_ctypes.IdentExpr):
        return gen._prepass_local_elems.get(node.name)
    if isinstance(node, gimple_ctypes.CallExpr):
        key = gen._prepass_callee_key(node)
        if key is not None:
            e = gen._return_elem_types.get(key)
            if e is not None:
                return e
        # Known SCALAR-returning leaf helpers (exported by gimple_ctypes,
        # outside every closure's function set): their contribution to a
        # container literal is their scalar return type itself.
        callee = getattr(node.func, 'name', None) or (
            getattr(node.func, 'attr', None) if isinstance(node.func, gimple_ctypes.MemberExpr) else None)
        if callee in ('_mojo_type', '_c_escape', '_safe_name'):
            return 'char *'
    return None


def _prepass_list_elem(gen, elements) -> str:
    """Element type of a container literal for the pre-pass. Mirrors
    _infer_list_elem_type but resolves identifier elements through the
    local container-element map instead of var_types (empty during Pass
    2c) — e.g. `return ctype, cval` where cval was unpacked from an
    earlier char*-tuple call."""
    if not elements:
        return 'int64_t'
    types = []
    for e in elements:
        le = gen._quick_container_elem(e)
        types.append(le if le is not None else gen._quick_type(e))
    return gimple_ctypes.TypeLattice.join_all(types) if types else 'int64_t'


def _fstring_sub_exprs(gen, node) -> list:
    """Parse an f-string StringLiteral's `{expr}` interpolations into AST
    expression nodes, best-effort.

    F-string interpolation sub-expressions are raw source text kept
    inside the StringLiteral's own `.value` (only parsed lazily, at
    actual codegen time, by _lower_StringLiteral) — they are NOT real
    AST nodes reachable from the top-level parse tree. That made a call
    embedded directly inside an interpolation (e.g. f"{g('a','b')}",
    with no intermediate variable) invisible to _collect_calls and thus
    to Pass 1.3d's cross-call scalar contract below: only the
    `y = g(...)` shape, a genuine AssignStmt.value CallExpr, was ever
    observed. See bugs/CODEGEN_untyped_param_string_direct_fstring_call.md.
    Mirrors _lower_StringLiteral's own fresh-parse-from-text handling of
    these so both paths agree on what a call site looks like."""
    val, is_fstring = gen._decode_str_literal_text(node.value)
    if not is_fstring:
        return []
    out = []
    for kind, text, _spec, _conv in gen._parse_fstring_parts(val):
        if kind != 'expr':
            continue
        try:
            from mojo_compiler import Parser as _P, py_tokenize as _tok
            expr_node = _P(_tok(text))._parse_expr(0)
            expr_node = gimple_ctypes.ast_rewriter.rewrite_node(expr_node)
            out.append(expr_node)
        except Exception:
            pass  # same "can't be lowered" tolerance as _lower_StringLiteral
    return out


def _scan_container_elems(gen, body: list) -> tuple[dict, dict, dict]:
    """Best-effort static element-type map for local containers in a body.

    Returns (elem, nested, dict_val): var name -> element C type, (when the
    element is itself a list) var name -> the inner list's element C type,
    and var name -> dict value C type. Derived by replaying list-literal
    assignments, `.append(...)` calls, and `d[k] = v` subscript assignments.
    Used to build the cross-call element-type contract: a caller knows
    `bodies` is a list of double-lists; the callee param must inherit that
    so `bodies[i][j]` reads with the right getter instead of silently
    defaulting to int.

    Recurses into every nested compound statement, INCLUDING a nested
    `FunctionDef` (a closure) — it has its own `.body` list attribute, so
    the generic `for attr in (...)` walk below descends into it same as
    an `if`/`for`/`try` block. This matters: this whole pre-pass exists
    to run BEFORE any codegen for this function OR its closures, so a
    dict/list only ever written inside a nested closure (e.g.
    replace_multiline_strings's `repl()` doing `string_cache[ph] = ...`)
    still gets its value type recorded under the STABLE outer variable
    name, visible to a read anywhere else in the same function (inside
    or outside the closure) regardless of codegen ordering — unlike the
    reactive, codegen-time AssignStmt-lowering bookkeeping alone would
    be: that only records a dict/list's value type at its own
    assignment site, keyed by whatever C variable/temp is in scope
    *there* — for a variable captured into a nested closure, a read of
    it anywhere outside that closure uses a completely different C
    temp (see _lower_IdentExpr's captures branch), so a write recorded
    only reactively, from inside the closure, would never be visible to
    that outside read regardless of which one gets codegen'd first.
    Scanning for the write ahead of time and keying the result on the
    stable *Python* variable name sidesteps the whole ordering problem.
    """
    elem: dict[str, str] = {}
    nested: dict[str, str] = {}
    dict_val: dict[str, str] = {}

    def note_list_literal(v: str, lit: gimple_ctypes.ListExpr):
        _e = gen._infer_list_elem_type(lit.elements)
        # See _literal_elements_include_none's docstring (_lower_list_
        # literal's identical guard, which THIS pre-pass duplicates the
        # underlying inference of): don't seed an int64_t-joined list's
        # element type here either when the literal spells out a
        # `None` among its elements, or _list_repr_fn would still route
        # print(name)/repr(name) through mojo_repr_list_ints (no None-
        # sentinel check) via this pre-pass's seeded entry, even though
        # _lower_list_literal's own (later) codegen-time assignment
        # correctly left it unset.
        if not (_e == 'int64_t' and gen._literal_elements_include_none(lit.elements)):
            elem[v] = _e
        if lit.elements and isinstance(lit.elements[0], gimple_ctypes.ListExpr):
            elem[v] = 'MojoList *'
            nested[v] = gen._infer_list_elem_type(lit.elements[0].elements)

    def walk(stmts):
        for n in stmts:
            if isinstance(n, gimple_ctypes.AssignStmt) and isinstance(n.target, gimple_ctypes.IdentExpr):
                v, val = n.target.name, n.value
                if isinstance(val, gimple_ctypes.ListExpr):
                    note_list_literal(v, val)
                elif isinstance(val, gimple_ctypes.IdentExpr) and val.name in elem:
                    elem[v] = elem[val.name]
                    if val.name in nested:
                        nested[v] = nested[val.name]
            elif (isinstance(n, gimple_ctypes.AssignStmt) and isinstance(n.target, gimple_ctypes.SubscriptExpr)
                    and isinstance(n.target.obj, gimple_ctypes.IdentExpr)):
                v = n.target.obj.name
                vt = gen._quick_type(n.value)
                if vt and (vt in ('char *', 'double', 'MojoDict *', 'MojoList *', 'MojoSet *')
                           or vt.endswith(' *')):
                    dict_val.setdefault(v, vt)
            elif isinstance(n, gimple_ctypes.ExprStmt) and isinstance(n.value, gimple_ctypes.CallExpr):
                c = n.value
                if (isinstance(c.func, gimple_ctypes.MemberExpr) and c.func.member == 'append'
                        and isinstance(c.func.obj, gimple_ctypes.IdentExpr) and c.args):
                    v, a = c.func.obj.name, c.args[0]
                    if isinstance(a, gimple_ctypes.ListExpr):
                        elem[v] = 'MojoList *'
                        nested[v] = gen._infer_list_elem_type(a.elements)
                    elif isinstance(a, gimple_ctypes.IdentExpr) and elem.get(a.name) == 'MojoList *':
                        elem[v] = 'MojoList *'
                        if a.name in nested:
                            nested[v] = nested[a.name]
            # recurse into compound statements
            for attr in ('body', 'then_body', 'else_body', 'finally_body'):
                sub = getattr(n, attr, None)
                if isinstance(sub, list):
                    walk(sub)
            for _cond, eb in (getattr(n, 'elifs', None) or []):
                walk(eb)
            for h in (getattr(n, 'handlers', None) or []):
                hb = getattr(h, 'body', None)
                if isinstance(hb, list):
                    walk(hb)

    walk(body)
    return elem, nested, dict_val


def _list_repr_fn(gen, rav: str) -> str:
    """Choose the list-repr runtime helper for a `MojoList *` value.

    MojoList stores every element as a raw int64_t slot with no
    per-element type tag, and the generic codegen-emitted `_mojo_repr_list`
    reads each slot back via mojo_list_get_int. A list of doubles then
    mis-reprs (or, when a bit pattern happens to look like a plausible heap
    address, crashes inside `_mojo_generic_elem_repr` /
    `mojo_read_type_tag_safe`). When this codegen already knows the element
    type is double (self._elem_types, e.g. from a `[3.5, 2.5]` literal),
    route to the double-aware runtime helper instead. Unknown/mixed element
    types keep the generic repr — never regress the int/str/nested cases.

    Same reasoning applies to a genuinely homogeneous int64_t element
    list (e.g. `[a for a in range(n)]`, `[i for i, _ in pair_gen(n)]`):
    the generic `_mojo_repr_list` -> `_mojo_generic_elem_repr` pair
    treats any slot holding the raw value 0 as the `None` sentinel
    (load-bearing for genuinely dynamic/heterogeneous lists, where a
    boxed 0 really can mean a null), which silently misprints a real
    int element of 0 as `None` for a list statically known to hold
    only plain ints — found via a real repro (`[a for a, _ in
    pair_gen(4)]` where pair_gen yields (0, 0), (1, 10), ...: printed
    `[None, 1, 2, 3]` instead of `[0, 1, 2, 3]`). Route to
    mojo_repr_list_ints (mirrors mojo_repr_list_doubles's structure,
    no None-sentinel check) whenever the element type is known to be
    int64_t.
    """
    et = gen._elem_types.get(rav)
    if et == 'double':
        return 'mojo_repr_list_doubles'
    if et == 'int64_t':
        return 'mojo_repr_list_ints'
    return '_mojo_repr_list'


def _stringify_value(gen, et: str, ev: str) -> str:
    """Convert an already-lowered (type, value) pair into a `char *` per
    Python `str()` semantics. Shared by f-string interpolation and `%`
    string-formatting's `%s` conversion — both need "stringify this typed
    value" and previously only f-strings had it inline."""
    if et == 'char *':
        return ev
    # A boxed char* (a string pointer stored in an int64_t var, e.g. a
    # tuple-loop var read via get_str and boxed) — stringify as the string
    # it points to, not its decimal address. Without this, f-strings /
    # %s of such a value emitted `static char * <address> = "<address>"`.
    if et in ('int', 'int64_t') and gen._get_actual_type(et, ev) == 'char *':
        return gen._new_val('char *', f'(char *){ev}')
    if et == '_Bool':
        # Python str(True)/str(False) → "True"/"False", not the "1"/"0"
        # the int path below would produce.
        return gen._call_expr('char *', 'mojo_bool_to_str', [('int', ev)])
    if et in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
              'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
        nv = gen._to_int64(et, ev)
        return gen._call_expr('char *', 'mojo_str_from_int', [('int64_t', nv)])
    if et in ('double', 'float'):
        fv = ev if et == 'double' else gen._new_val('double', f'(double){ev}')
        return gen._call_expr('char *', 'mojo_repr_float', [('double', fv)])
    return gen._call_expr('char *', 'mojo_str', [(et, ev)])


def _apply_fstring_spec(gen, part_val: str, spec: str) -> str:
    """Apply a format-spec mini-language subset (fill/align/width and
    zero-padding, e.g. `{x:04d}`) to an already-stringified f-string
    value, mirroring myinterpreter._apply_fstring_format_spec so the
    compiled path and interpreter agree. Emits a runtime helper call.
    """
    # "0" prefix -> zero-pad right-aligned to the width
    fill = ' '
    align = None
    i = 0
    if len(spec) >= 2 and (spec[1] == '<' or spec[1] == '>' or spec[1] == '^'):
        fill = spec[0]
        align = spec[1]
        i = 2
    elif len(spec) >= 1 and (spec[0] == '<' or spec[0] == '>' or spec[0] == '^'):
        align = spec[0]
        i = 1
    elif len(spec) >= 1 and spec[0] == '0':
        fill = '0'
        align = '>'
        i = 1
    width_digits = ''
    while i < len(spec) and spec[i] >= '0' and spec[i] <= '9':
        width_digits += spec[i]
        i += 1
    if not width_digits:
        return part_val
    # Emit a runtime call that pads part_val to the width using the fill
    # char and alignment. Use a small inline approach: call mojo_str_rjust/
    # mojo_str_ljust/center if available, else fall back to a runtime
    # helper. Check for the runtime padding helpers:
    width = int(width_digits)
    if align == '<':
        return gen._call_expr('char *', 'mojo_str_ljust',
                               [('char *', part_val), ('int64_t', str(width)), ('char *', f'"{fill}"')])
    if align == '^':
        return gen._call_expr('char *', 'mojo_str_center',
                               [('char *', part_val), ('int64_t', str(width)), ('char *', f'"{fill}"')])
    # '>' (right-align) and '0' (zero-pad right) both rjust
    return gen._call_expr('char *', 'mojo_str_rjust',
                           [('char *', part_val), ('int64_t', str(width)), ('char *', f'"{fill}"')])


def _subst_in_value(gen, v, mapping: dict):
    if isinstance(v, list):
        return [gen._subst_in_value(x, mapping) for x in v]
    if isinstance(v, tuple):
        return tuple(gen._subst_in_value(x, mapping) for x in v)
    if gimple_ctypes.dataclasses.is_dataclass(v) and not isinstance(v, type):
        return gen._subst_idents(v, mapping)
    return v


def _is_known_field(gen, member: str) -> bool:
    """True if `member` is a field of at least one struct in
    struct_field_types — i.e. a boxed handle carrying it is (very likely)
    a real struct instance whose `.member` is a genuine field, not an
    identity/type-value access. Used by _lower_MemberExpr to decide
    whether a boxed scalar receiver should go through the runtime
    tag-dispatch field read (A5 part 2) instead of the `.value`/opaque
    identity shortcuts."""
    for _fm in gen.struct_field_types.values():
        if member in _fm:
            return True
    return False


def _known_field_type(gen, member: str) -> str | None:
    """The static C type of `member` when it is a field of structs in
    struct_field_types and ALL of them agree on that type; None if the
    member is unknown or its type varies across structs (e.g. `value`:
    int64_t in ReturnStmt/ExprStmt but char* in Token, double in
    FloatLiteral, _Bool in BoolLiteral). A boxed handle's field read can
    only be returned with a single static C type, so only fields with an
    unambiguous type are typed here; the rest keep the int64_t default."""
    _types = set()
    for _fm in gen.struct_field_types.values():
        if member in _fm:
            _types.add(_fm[member])
    if len(_types) == 1:
        return _types.pop()
    return None


def _try_lower_slice_region_eq(gen, slice_node, other_node, negate: bool):
    """`slice_node == other_node` (or `!=` if negate) where slice_node is
    a plain `s[a:b]` SliceExpr with no step - lowers to a direct
    mojo_cstr_region_eq call with no intermediate slice allocation, if
    the slice's source and the other operand are both plain `char *`.
    Returns None (do nothing, let the caller fall through to the generic
    lowering) if the shapes don't match closely enough to be safe."""
    ot, ov = gen.lower_expr(slice_node.obj)
    if ot != 'char *':
        return None
    oth_t, oth_v = gen.lower_expr(other_node)
    if oth_t != 'char *':
        return None
    if slice_node.start is not None:
        _st, sv = gen.lower_expr(slice_node.start)
        start_v = gen._to_int64(_st, sv)
    else:
        start_v = '0'
    if slice_node.stop is not None:
        _et, ev = gen.lower_expr(slice_node.stop)
        stop_v = gen._to_int64(_et, ev)
    else:
        stop_v = 'MOJO_SLICE_STOP_OMITTED'
    eq_t = gen._call_expr('int', 'mojo_cstr_region_eq',
                            [('char *', ov), ('int64_t', start_v), ('int64_t', stop_v), ('char *', oth_v)])
    t = gen._new_temp('_Bool')
    cmp = '== 0' if negate else '!= 0'
    gen._emit(f"  {t} = {eq_t} {cmp};")
    return '_Bool', t


def _sprintf_one(gen, c_spec: str, arg_val: str) -> str:
    """sprintf a single value through a heap buffer into `char *`, using
    a compile-time-known C format spec. Same malloc+sprintf shape
    print() already uses for its non-string/list/dict operands (see
    the print()-builtin lowering) -- factored out here since
    %-formatting needs it once per spec rather than once per call."""
    buf = gen._new_temp('char *')
    vp = gen._new_temp('void *')
    fmt_t = gen._new_val('char *', gen._intern_string(gimple_ctypes._c_escape(c_spec)))
    gen._emit(f'  {vp} = malloc (256);')
    gen._emit(f'  {buf} = (char *) {vp};')
    gen._emit(f'  sprintf ({buf}, {fmt_t}, {arg_val});')
    return buf


def _to_int64(gen, ctype: str, val: str) -> str:
    """Cast val to int64_t; emits to a temp so the result is always an lvalue."""
    if ctype == 'int64_t':
        # GIMPLE: can't redundantly cast global int64_t to int64_t; just load
        return gen._ensure_local('int64_t', val)
    t = gen._new_temp('int64_t')
    if ctype.endswith(' *'):
        # Pointer → int64_t requires void* intermediate in GIMPLE
        val_local = gen._ensure_local(ctype, val)
        vp = gen._new_val('void *', f"(void *){val_local}")
        gen._emit(f"  {t} = (int64_t){vp};")
    else:
        # Non-pointer, non-int64_t: load global then cast
        val_local = gen._ensure_local(ctype, val)
        gen._emit(f"  {t} = (int64_t){val_local};")
    return t


def _resolve_member_expr_type(gen, node) -> str | None:
    """Resolve the actual C type of a nested member expression like self.parent.
    Returns the C type (e.g. 'Scope*') or None if it can't be resolved."""
    if isinstance(node, gimple_ctypes.IdentExpr):
        # Base case: resolve identifier to its type
        if node.name in gen.var_types:
            return gen.var_types[node.name]
        # Check struct field types (class names)
        if node.name in gen.struct_field_types:
            return node.name + '*'
        return None
    elif isinstance(node, gimple_ctypes.MemberExpr):
        # Recursive case: resolve obj.member
        obj_type = gen._resolve_member_expr_type(node.obj)
        if obj_type:
            # Strip pointer if present
            base_type: str
            base_type = gimple_exprtypes._struct_name_of(obj_type)
            if base_type in gen.struct_field_types:
                field_map = gen.struct_field_types[base_type]
                if node.member in field_map:
                    return field_map[node.member]
        return None
    return None


def _elaborate_overload_call(gen, node: gimple_ctypes.CallExpr):
    """Resolve and elaborate an overloaded imported call (slice 4): lower the
    args, pick the matching overload by their C types, and emit the call to the
    signature-mangled concrete symbol."""
    g = node.func.name
    source = gen._imported_overloads.get(g)
    if not source:
        return None
    # Keyword-only calls (e.g. std.memory.memcpy(dest=.., src=.., count=..))
    # were previously invisible here: only node.args was lowered, so a
    # kwargs-only call always resolved with an EMPTY arg-type list, which
    # overload resolution below either fails to disambiguate or matches
    # against a wrong/empty-param candidate — either way, the argument
    # values themselves were silently dropped, emitting a call the real
    # signature can never accept (confirmed root cause of a spurious
    # `memcpy();` — zero args — that broke a cold-CAS-cache stdlib build
    # investigated 2026-07-15). Real call sites overwhelmingly write
    # kwargs in the callee's own declaration order, so appending them
    # after any positional args is the same best-effort convention used
    # elsewhere in this file (_lower_call's general kwarg padding).
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    for _kn, _kexpr in (getattr(node, 'kwargs', None) or []):
        arg_pairs.append(gen.lower_expr(_kexpr))
    try:
        module_src = open(source).read()
        import elaborate
        info = elaborate.Elaborator().elaborate_overload_call(
            module_src, g, [ct for ct, _ in arg_pairs])
    except Exception:
        gimple_ctypes._debug_note('overload elaboration failed')
        info = None
    if not info:
        return None
    return gen._emit_generic_instantiation(info, arg_pairs)


def _maybe_lower_mlir_op(gen, node: gimple_ctypes.CallExpr):
    """Lower a ``__mlir_op.\\`dialect.op\\`[attrs](args)`` call via mlir.py.

    The callee is either a ``MemberExpr`` on ``__mlir_op`` (no attr params) or
    a ``SubscriptExpr`` wrapping that member (the ``[...]`` attribute params).
    Returns ``(ctype, val)`` if handled, else ``None`` so normal dispatch runs.
    """
    func = node.func
    attr_members: list[str] = []
    named_attrs: dict[str, object] = {}   # param name → literal value (when an __mlir_attr)
    if isinstance(func, gimple_ctypes.SubscriptExpr):
        # Collect the op's [name=value] params. __mlir_attr literals feed both
        # index.cmp's predicate (flat list) and struct GEP's index= (by name).
        for _name, _val in (getattr(func, 'attrs', None) or []):
            if isinstance(_val, gimple_ctypes.MemberExpr) and isinstance(_val.obj, gimple_ctypes.IdentExpr) \
                    and _val.obj.name == '__mlir_attr':
                attr_members.append(_val.member)
                if _name:
                    kind, v = gimple_ctypes.mlir.parse_attr(_val.member)
                    if kind in ('int', 'simd'):
                        named_attrs[_name] = v
        func = func.obj
    if not (isinstance(func, gimple_ctypes.MemberExpr) and isinstance(func.obj, gimple_ctypes.IdentExpr)
            and func.obj.name == '__mlir_op'):
        return None

    arg_pairs = [gen.lower_expr(a) for a in node.args]

    # Memory / lvalue ops (load / store / offset) need typed, statement-aware
    # emission; mlir.py classifies, we emit with operand types + ptr helpers.
    mem = gimple_ctypes.mlir.mem_op_kind(func.member)
    if mem is not None:
        return gen._lower_mlir_mem(mem, arg_pairs)

    # Struct / aggregate GEP (extract / gep / aget): read the index= field of a
    # known struct. Falls through to the deferred stub when the layout or index
    # isn't statically resolvable.
    sk = gimple_ctypes.mlir.struct_op_kind(func.member)
    if sk is not None:
        res = gen._lower_mlir_struct(sk, named_attrs.get('index'), arg_pairs)
        if res is not None:
            return res
        op = gimple_ctypes.mlir.unwrap(func.member)
        t = gen._new_temp('int64_t')
        gen._emit(f"  {t} = (int64_t)0;  /* mlir __mlir_op.{op}: deferred: unresolved struct index/layout */")
        return 'int64_t', t

    arg_vals = [v for (_, v) in arg_pairs]
    res = gimple_ctypes.mlir.lower_op(func.member, arg_vals, attr_members)
    if res is None:
        # Operands already evaluated; yield 0 so surrounding code still compiles.
        # Distinguish "deferred by design" (GPU/coro/atomics/…) from "not met yet".
        op = gimple_ctypes.mlir.unwrap(func.member)
        reason = gimple_ctypes.mlir.deferral_reason(func.member)
        note = f"deferred: {reason}" if reason else "not modeled"
        t = gen._new_temp('int64_t')
        gen._emit(f"  {t} = (int64_t)0;  /* mlir __mlir_op.{op}: {note} */")
        return 'int64_t', t
    ctype, expr = res
    t = gen._new_val(ctype, f"{expr}")
    return ctype, t


def _compr_range_loop(gen, node, gen0, res, res_type):
    gen._declare_var(gen0.target, 'int64_t')
    args = gen0.iterable.args
    dynamic_step = False
    if len(args) == 1:
        # Explicitly-typed int64_t TEMPS, not bare '0'/'1' string
        # literals -- see the increment-temp comment further down for
        # the exact failure mode this class of bug produces. A bare
        # '0'/'1' defaults to C `int` under strict -fgimple (which has
        # no implicit int->int64_t widening across statements), so
        # `{target} = 0;` (target declared int64_t two lines above)
        # and the increment `{target} + 1` both produced "non-trivial
        # conversion in 'integer_cst'"/"type mismatch in binary
        # expression" for EVERY 1-arg/2-arg range()-based comprehension
        # (`[i * 4 for i in range(n)]`) -- not just the increment-temp
        # DECLARATION shape the prior fix (see below) addressed. Using
        # `self._new_val(...)` (a real pre-materialized temp, matching
        # this same function's own `one64 = self._new_val('int64_t',
        # "(int64_t)1")` pattern a few lines down) rather than simply
        # inlining the `(int64_t)` cast as a string is required too --
        # strict GIMPLE rejects a cast expression appearing directly as
        # an operand of a binary op ("expected expression before '('
        # token"); the cast must be its own prior assignment, with only
        # the resulting bare temp name used in the binary expression.
        # Found via Tools/cases_generator/cwriter.py's `CWriter.
        # __init__`: `self.indents = [i * 4 for i in range(indent + 1)]`.
        start_v = gen._new_val('int64_t', '(int64_t)0')
        step_v = gen._new_val('int64_t', '(int64_t)1')
        cond_op = '<'
        _stop_t, stop_v = gen.lower_expr(args[0])
        if _stop_t != 'int64_t':
            # Same reasoning as start_v below: a bare int-typed bound
            # compared against the int64_t-declared loop target gives
            # "mismatching comparison operand types" under strict
            # -fgimple (GCC does NOT apply usual arithmetic conversions
            # across a GIMPLE comparison statement) — test_deque.py's
            # `list(range(50, 150))` ctor lowering.
            stop_v = gen._new_val('int64_t', f"(int64_t){stop_v}")
    elif len(args) == 2:
        start_t, start_v = gen.lower_expr(args[0])
        _stop_t, stop_v  = gen.lower_expr(args[1])
        if _stop_t != 'int64_t':
            stop_v = gen._new_val('int64_t', f"(int64_t){stop_v}")
        # `start_v` (unlike `stop_v`, only ever used in a comparison,
        # which undergoes GIMPLE's usual arithmetic conversion) feeds a
        # DIRECT `{target} = {start_v};` assignment below into an
        # int64_t-declared target -- the exact same bare-literal-into-
        # int64_t shape the 1-arg branch's comment above documents
        # ("non-trivial conversion in 'integer_cst'"), but that fix was
        # only ever applied to the 1-arg branch's own hardcoded
        # `(int64_t)0`, not here. A literal/`int`-typed 2-arg start
        # (`range(0, len(cl))`) hit the identical GCC error this branch
        # was never covered for. Materialize as a real int64_t temp,
        # mirroring `one64`/the 1-arg branch's own `start_v` construction.
        if start_t != 'int64_t':
            start_v = gen._new_val('int64_t', f"(int64_t){start_v}")
        step_v = gen._new_val('int64_t', '(int64_t)1')
        cond_op = '<'
    elif len(args) == 3:
        start_t, start_v = gen.lower_expr(args[0])
        _stop_t, stop_v  = gen.lower_expr(args[1])
        if _stop_t != 'int64_t':
            stop_v = gen._new_val('int64_t', f"(int64_t){stop_v}")
        se = args[2]
        if isinstance(se, gimple_ctypes.IntLiteral) and se.value < 0:
            cond_op = '>'
        elif isinstance(se, gimple_ctypes.UnaryOp) and se.op == '-':
            cond_op = '>'
        elif isinstance(se, gimple_ctypes.IntLiteral):
            cond_op = '<'
        else:
            cond_op = '<'; dynamic_step = True
        step_t, step_v = gen.lower_expr(se)
        # Same bare-literal-into-int64_t gap as the 2-arg branch above,
        # for BOTH `start_v` (direct `{target} = {start_v};` assignment)
        # and `step_v` (direct `{target} + {step_v}` addition feeding
        # another int64_t-typed temp below, `st`) -- a 3-arg
        # `range(0, len(cl), 2)` (turtle.py's `TurtleScreenBase.
        # _pointlist`: `[(cl[i], -cl[i+1]) for i in range(0, len(cl),
        # 2)]`) hit both: "non-trivial conversion in 'integer_cst'" on
        # `i = 0;` and "type mismatch in binary expression" on the
        # increment. `dynamic_step`'s own comparisons (`{t_sp} = {step_v}
        # > 0;`) are fine uncast, same reasoning as `stop_v` above.
        if start_t != 'int64_t':
            start_v = gen._new_val('int64_t', f"(int64_t){start_v}")
        if step_t != 'int64_t':
            step_v = gen._new_val('int64_t', f"(int64_t){step_v}")
    else:
        return

    # Every emitted reference below must go through _cname: _declare_var
    # renames targets colliding with C reserved identifiers (`index` is a
    # POSIX function, so `_declare_var('index')` declares `_var_index` and
    # records the mapping in _c_names) — emitting the raw Python name made
    # the loop write an UNDECLARED `index` while body reads (which resolve
    # through _c_names) read the declared-but-never-assigned `_var_index`
    # (GCC: "lvalue required as left operand of assignment"; real repro:
    # Tools/scripts/summarize_stats.py's `{...: v for (index, v) in
    # enumerate(...)}` inside OpcodeStats.get_specialization_failure_kinds).
    tgt_c = gen._cname(gen0.target)
    gen._emit(f"  {tgt_c} = {start_v};")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    if dynamic_step:
        t_lt = gen._new_temp('_Bool'); t_gt = gen._new_temp('_Bool')
        t_sp = gen._new_temp('_Bool'); cond_t = gen._new_temp('_Bool')
        gen._emit(f"  {t_lt} = {tgt_c} < {stop_v};")
        gen._emit(f"  {t_gt} = {tgt_c} > {stop_v};")
        gen._emit(f"  {t_sp} = {step_v} > 0;")
        gen._emit(f"  {cond_t} = {t_sp} ? {t_lt} : {t_gt};")
    else:
        cond_t = gen._new_val('_Bool', f"{tgt_c} {cond_op} {stop_v}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    # `gen0.target` is declared int64_t (line above); this increment
    # temp must match exactly -- GIMPLE has no implicit int->int64_t
    # widening across statements, so declaring it 'int' (32-bit) here
    # produced "non-trivial conversion in 'var_decl'"/"type mismatch
    # in binary expression" on the very next line's `{gen0.target} =
    # {st};` for EVERY range-based comprehension (`[x for x in
    # range(...)]` and friends), not just some narrow edge case.
    # Found via pathlib/__init__.py's `tuple(self[i] for i in
    # range(*idx.indices(len(self))))`.
    st = gen._new_val('int64_t', f"{tgt_c} + {step_v}")
    gen._emit(f"  {tgt_c} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _compr_list_loop(gen, node, gen0, res, res_type, it_val):
    # Detect tuple unpacking target: "_, av" or "(_, av)"
    target_str = gen0.target.strip()
    inner_str = target_str[1:-1].strip() if (target_str.startswith('(') and target_str.endswith(')')) else target_str
    if ',' in inner_str:
        # Tuple target: each element of the outer list is a sub-list
        # (tuple). Mirrors _gen_for_list's identical, already-fixed
        # per-slot logic (see its own comment for the history): pick
        # the accessor PER SLOT via slot_types/_dict_items_val_elems/
        # _nested_elem_types instead of assuming every slot is a
        # string. The old code here read EVERY slot via
        # mojo_list_get_str unconditionally, which round-trips a
        # genuinely-numeric slot's bit pattern correctly (get_str then
        # cast back to int64_t is value-preserving) but then always
        # tagged the var `_actual_types[vn] = 'char *'` regardless —
        # so a later arithmetic use (e.g. `range(a, a + b) for a, b in
        # pairs` with pairs a list of int tuples) had `b` wrongly
        # treated as a pointer by `_lower_binary_tail`'s `_actual_
        # types.get(rv, ...)` lookup, producing "passing argument 2 of
        # 'mojo_range' makes integer from pointer without a cast".
        # Bracket-aware split (see _gen_for_list's identical fix): a naive
        # `inner_str.split(',')` tore a NESTED target like
        # `label, (value, den)` into the bogus fragments `(value` / `den)`
        # which were then declared and assigned VERBATIM as C identifiers
        # (`(value = _t10;` / `den) = _t11;`) — hard syntax errors at the
        # comprehension site (real: Tools/scripts/summarize_stats.py's
        # `[... for label, (value, den) in object_stats.items()]`).
        var_names = _split_top_level_comma(inner_str)
        is_dict_items = it_val in gen._dict_items_val_elems
        value_elem = gen._dict_items_val_elems.get(it_val) if is_dict_items else None
        slot_types = gen._tuple_slot_types.get(it_val)
        pair_elem = gen._nested_elem_types.get(it_val, 'int64_t')
        slot_elems = []
        for i, vn in enumerate(var_names):
            if is_dict_items:
                se = 'char *' if i == 0 else (value_elem or 'int64_t')
            elif slot_types is not None and i < len(slot_types):
                se = slot_types[i]
            else:
                se = pair_elem
            slot_elems.append(se)

        def _declare_target_name(vn, se):
            # A parenthesized slot is not itself a variable — recurse so
            # only its INNER names get declared, as boxed int64_t (the
            # assignment recursion below reads the slot as an opaque
            # boxed pair; mirrors _gen_for_list's identical convention).
            if vn.startswith('(') and vn.endswith(')'):
                for _nv in _split_top_level_comma(vn[1:-1].strip()):
                    _declare_target_name(_nv, 'int64_t')
            else:
                gen._declare_var(vn, se)

        for vn, se in zip(var_names, slot_elems):
            _declare_target_name(vn, se)
        len64 = gen._new_val('int64_t', f'mojo_list_len ({it_val})')
        idx64 = gen._new_val('int64_t', '(int64_t)0')
        bb_cond = gen._new_bb(); bb_body = gen._new_bb()
        bb_post = gen._new_bb(); bb_after = gen._new_bb()
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_cond)
        cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
        gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        gen._emit_label(bb_body)
        raw_elem = gen._new_val('int64_t', f"mojo_list_get_int ({it_val}, {idx64})")
        sub_list = gen._new_val('MojoList *', f"(MojoList *){raw_elem}")

        def _emit_slot_assign(ptr, vn, i, se):
            # Nested tuple target: the slot is an opaque boxed pair —
            # cast and recurse one level (deeper nesting recurses
            # identically), mirroring _gen_for_list. Checked BEFORE any
            # accessor dispatch so even a wrongly-str-typed slot can't
            # emit a parenthesized name verbatim.
            if vn.startswith('(') and vn.endswith(')'):
                raw_n = gen._new_val('int64_t', f"mojo_list_get_int ({ptr}, {i})")
                nested_ptr = gen._new_val('MojoList *', f"(MojoList *){raw_n}")
                nested_names = _split_top_level_comma(vn[1:-1].strip())
                for j, nn in enumerate(nested_names):
                    _emit_slot_assign(nested_ptr, nn, j, 'int64_t')
                return
            cv = gen._cname(vn)
            suf = gimple_ctypes.TypeLattice.list_suffix(se)
            vt = gen.var_types.get(vn, se)
            if suf == 'str':
                sub_str = gen._new_val('char *', f"mojo_list_get_str ({ptr}, {i})")
                if vt == 'char *':
                    gen._emit(f"  {cv} = {sub_str};")
                else:
                    sub_val = gen._new_val('int64_t', f"(int64_t){sub_str}")
                    gen._emit(f"  {cv} = {sub_val};")
                    gen._actual_types[vn] = 'char *'
            else:
                raw = gen._new_val('int64_t', f"mojo_list_get_int ({ptr}, {i})")
                if vt == 'int64_t':
                    gen._emit(f"  {cv} = {raw};")
                else:
                    gen._safe_coerce_emit('int64_t', vt, raw, cv)

        for i, vn in enumerate(var_names):
            _emit_slot_assign(sub_list, vn, i, slot_elems[i])
        gen._gen_compr_append(node, gen0, res, res_type, bb_post)
        gen._emit(f"  goto {bb_post};")
        gen._emit_label(bb_post)
        one64 = gen._new_val('int64_t', "(int64_t)1")
        st = gen._new_val('int64_t', f"{idx64} + {one64}")
        gen._emit(f"  {idx64} = {st};")
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_after)
        return
    elem = gen._elem_of(it_val)
    gen._declare_var(gen0.target, elem)
    len64 = gen._new_val('int64_t', f'mojo_list_len ({it_val})')
    idx64 = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    suf = gimple_ctypes.TypeLattice.list_suffix(elem)
    if suf == 'double':
        gen._emit(f"  {gen0.target} = mojo_list_get_double ({it_val}, {idx64});")
    elif suf == 'str':
        # mojo_list_get_str returns char*, handle type mismatch with target variable
        temp_str = gen._new_val('char *', f"mojo_list_get_str ({it_val}, {idx64})")
        target_type = gen._type_of(gen0.target)
        if target_type == 'char *':
            gen._emit(f"  {gen0.target} = {temp_str};")
        else:
            # Cast to int64_t if target is opaque
            int_ptr = gen._new_val('int64_t', f"(int64_t){temp_str}")
            gen._emit(f"  {gen0.target} = {int_ptr};")
    else:
        raw64 = gen._new_val('int64_t', f"mojo_list_get_int ({it_val}, {idx64})")
        # The loop variable may have been first declared elsewhere in this
        # function with a non-int64_t C type (e.g. `f` used as a string in
        # one branch and as a node handle in `for f in node.fields` later —
        # _declare_var is first-decl-wins). Assigning an int64_t element
        # straight into a `char *` variable is a hard "makes pointer from
        # integer" compile error; mirror _gen_for_list's identical
        # coercion. A node handle boxed into a char*-declared var is a
        # bit-pattern-preserving cast — the field-access lowering already
        # reads boxed handles through the runtime tag dispatch.
        target_type = gen._type_of(gen0.target)
        if target_type != 'int64_t':
            gen._safe_coerce_emit('int64_t', target_type, raw64, gen0.target)
        else:
            gen._emit(f"  {gen0.target} = (int64_t) {raw64};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one64 = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx64} + {one64}")
    gen._emit(f"  {idx64} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _compr_generator_loop(gen, node, gen0, res, res_type, it_val):
    """`list(<supported generator call>())` / any other comprehension
    consuming one — mirrors _compr_list_loop's/_gen_for_generator_iter's
    resume()/value() convention (see _gen_for_generator_iter's
    docstring) so a `for` loop and this comprehension-based consumer
    (which `list(...)`/`set(...)`/etc. all route through via
    _lower_ctor_from_iterable) get identical, non-duplicated semantics."""
    api = gen._generator_var_api.get(it_val)
    if api is None:
        gen._emit(f"  /* TODO: comprehension over MojoGenerator* with no known API (unreachable in Milestone B scope) */")
        return
    base, vct = api['base'], api['value_ctype']
    # `[... for a, b in <tuple-yielding generator>():]` — mirrors
    # _gen_for_generator_iter's identical tuple-target handling (see
    # its own comment), EXCEPT a comprehension's target string is NOT
    # guaranteed to be paren-wrapped for a bare (unparenthesized)
    # tuple target the way ForStmt.target always is:
    # `_parse_generator_target` (mojo_compiler.py) only wraps in
    # parens when the SOURCE itself wrote them (`for (a, b) in ...`);
    # `for a, b in ...` inside a comprehension parses to the literal
    # string "a, b" with no parens at all, unlike `_parse_unpack_
    # target`'s ForStmt path which always synthesizes the wrapping
    # parens regardless of source spelling. The old strict
    # startswith('(')/endswith(')') check here missed that bare form
    # entirely, silently falling through to the single-var branch
    # below and emitting a literal, invalid `e, _ = <tuple val>;`
    # comma-expression statement — which doesn't just fail to compile
    # cleanly itself, it desyncs the surrounding -fgimple parser badly
    # enough to cascade into dozens of unrelated "type defaults to
    # 'int'"/"conflicting types" errors on LATER, perfectly-formed
    # declarations (real repro: Lib/test/test_exception_group.py's
    # `[e for e, _ in leaf_generator(eg)]`). Mirrors `_compr_list_
    # loop`'s own already-correct both-forms detection (its "Detect
    # tuple unpacking target" comment) instead of reinventing a
    # narrower check.
    tuple_slot_ctypes = api.get('tuple_slot_ctypes')
    _target_str = gen0.target.strip()
    _inner_str = (_target_str[1:-1].strip()
                  if (_target_str.startswith('(') and _target_str.endswith(')'))
                  else _target_str)
    is_tuple_target = (',' in _inner_str and tuple_slot_ctypes is not None)
    if is_tuple_target:
        var_names = [v.strip() for v in _inner_str.split(',')]
    else:
        var_names = None
        gen._declare_var(gen0.target, vct)
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{base}_resume ({it_val})")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    val = gen._new_val(vct, f"{base}_value ({it_val})")
    if is_tuple_target:
        gen._emit_generator_tuple_unpack(var_names, tuple_slot_ctypes, val)
    else:
        # _cname, not the raw Python name: see _compr_range_loop's
        # reserved-identifier comment (`index` et al. are renamed by
        # _declare_var; body reads resolve through _c_names).
        gen._emit(f"  {gen._cname(gen0.target)} = {val};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  {base}_destroy ({it_val});")


def _compr_dict_loop(gen, node, gen0, res, res_type, it_val):
    gen._declare_var(gen0.target, 'char *')
    iter_t = gen._new_temp('MojoDictIter *')
    more_t = gen._new_temp('int')
    gen._emit(f"  {iter_t} = mojo_dict_iter_new ({it_val});")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    gen._emit(f"  {more_t} = mojo_dict_iter_next ({iter_t});")
    cond_t = gen._new_val('_Bool', f"{more_t} != 0")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    key_tmp = gen._new_val('const char *', f"mojo_dict_iter_key ({iter_t})")
    tgt = gen0.target
    vt = gen.var_types.get(tgt, 'char *')
    tgt_c = gen._cname(tgt)
    if vt in ('int64_t', 'int', 'int32_t'):
        vp = gen._new_val('void *', f'(void *){key_tmp}')
        box = gen._new_val('int64_t', f'(int64_t){vp}')
        gen._emit(f"  {tgt_c} = {box};")
    else:
        gen._emit(f"  {tgt_c} = (char *) {key_tmp};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  mojo_dict_iter_free ({iter_t});")


def _compr_set_loop(gen, node, gen0, res, res_type, it_val):
    gen._declare_var(gen0.target, 'int64_t')
    iter_t = gen._new_temp('MojoSetIter *')
    more_t = gen._new_temp('int')
    gen._emit(f"  {iter_t} = mojo_set_iter_new ({it_val});")
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    gen._emit(f"  {more_t} = mojo_set_iter_next ({iter_t});")
    cond_t = gen._new_val('_Bool', f"{more_t} != 0")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    gen._emit(f"  {gen._cname(gen0.target)} = mojo_set_iter_val_int ({iter_t});")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._emit(f"  mojo_set_iter_free ({iter_t});")


def _gen_print(gen, args: list, kwargs: list = None):
    # print(..., file=sys.stderr): kwargs used to be silently dropped
    # entirely (the file= expression was never even inspected), so every
    # print(..., file=sys.stderr) — the standard error-reporting idiom
    # throughout this codebase's own source — always printed to stdout
    # AND, once self-hosted, crashed evaluating `sys.stderr` generically
    # (mojo_obj_getattr's stub). Detected here by AST shape at compile
    # time; see _is_sys_stderr.
    print_fn = 'mojo_print'
    if kwargs:
        for kw_name, kw_val in kwargs:
            if kw_name == 'file' and gen._is_sys_stderr(kw_val):
                print_fn = 'mojo_print_stderr'

    # Inline string-literal call arguments (e.g. `mojo_print (" ")`) are not
    # valid in __GIMPLE — every literal must go through the _slit_ pool and
    # be loaded into a char* temp first (see _intern_string's docstring).
    # print()'s own separator/end/empty literals previously violated this
    # directly, which silently "worked" for top-level code (compiled as
    # plain C, where inline literals are fine) but corrupted the argument
    # at runtime for any struct method (always emitted as raw __GIMPLE) —
    # confirmed via a genuinely minimal repro (any struct method calling
    # print() with 2+ args segfaults; single-arg print was unaffected
    # since it skips the separator/uses only the pooled user string).
    def _emit_literal_print(escaped: str, print_fn: str):
        slit = gen._intern_string(escaped)
        t = gen._new_val('char *', slit)
        gen._emit(f'  {print_fn} ({t});')

    if not args:
        _emit_literal_print('', print_fn)
        return
    parts = [gen.lower_expr(a) for a in args]
    # A dict/list-get result stored in a plain local is boxed generically
    # as int64_t at the C level even when the real value is a string —
    # _lower_IdentExpr's plain-local-read path returns the *declared*
    # var_types entry, not the tracked real type (_actual_types), unlike
    # e.g. _lower_method_call's receiver resolution. Without re-resolving
    # here, print() on such a value picked the int format specifier and
    # printed the raw boxed pointer as a decimal address instead of the
    # string content. Found via py_tokenize's own multi-line-string cache
    # (`string_cache[placeholder]`, a MojoDict[str, str]) — `print()`ing
    # a restored docstring value printed its address, and any Token built
    # from it carried that same wrong value into `.value`.
    resolved_parts = []
    for atype, aval in parts:
        if atype in ('int', 'int64_t'):
            real = gen._get_actual_type(atype, aval)
            if real == 'char *':
                aval = gen._new_val('char *', f'(char *){aval}')
                atype = 'char *'
            elif real == 'MojoDict *':
                dp = gen._new_val('MojoDict *', f'(MojoDict *){aval}')
                rv = gen._call_expr('char *', '_mojo_repr_dict', [('MojoDict *', dp)])
                aval = rv
                atype = 'char *'
            elif real in ('MojoList *', 'MojoSet *'):
                lp = gen._new_val(real, f'({real}){aval}')
                if real == 'MojoList *':
                    fn = gen._list_repr_fn(aval)
                else:
                    fn = '_mojo_repr_set'
                rv = gen._call_expr('char *', fn, [(real, lp)])
                aval = rv
                atype = 'char *'
        resolved_parts.append((atype, aval))
    parts = resolved_parts
    for i, (atype, aval) in enumerate(parts):
        if atype == 'char *':
            gen._emit(f'  {print_fn} ({aval});')
        elif atype == 'MojoList *':
            # print(a_list) previously fell to the generic numeric
            # sprintf path below via printf_fmt('MojoList *'), printing
            # the raw boxed pointer as a decimal address — Python prints
            # a real `[elem, ...]` repr. Reuse the reflection-generated
            # list repr rather than a separate formatter.
            rv = gen._call_expr('char *', gen._list_repr_fn(aval), [('MojoList *', aval)])
            gen._emit(f'  {print_fn} ({rv});')
        elif atype == 'MojoDict *':
            rv = gen._call_expr('char *', '_mojo_repr_dict', [('MojoDict *', aval)])
            gen._emit(f'  {print_fn} ({rv});')
        else:
            t = gen._new_temp('char *')
            vp = gen._new_temp('void *')
            # The format string is itself an inline literal in a call
            # argument position — same __GIMPLE restriction as the
            # separator/newline literals above, so pool it too.
            fmt_slit = gen._intern_string(gimple_ctypes.TypeLattice.printf_fmt(atype))
            fmt_t = gen._new_val('char *', fmt_slit)
            gen._emit(f'  {vp} = malloc (256);')
            gen._emit(f'  {t} = (char *) {vp};')
            gen._emit(f'  sprintf ({t}, {fmt_t}, {aval});')
            gen._emit(f'  {print_fn} ({t});')
            gen._emit(f'  free ({t});')
        if i < len(parts) - 1:
            _emit_literal_print(' ', print_fn)
    _emit_literal_print('\\n', print_fn)


def _eval_const_int(gen, node) -> int | None:
    """Evaluate an expression as a compile-time integer, or return None."""
    if isinstance(node, gimple_ctypes.IntLiteral):  return node.value
    if isinstance(node, gimple_ctypes.BoolLiteral): return int(node.value)
    if isinstance(node, gimple_ctypes.UnaryOp) and node.op == '-':
        v = gen._eval_const_int(node.operand)
        return -v if v is not None else None
    if isinstance(node, gimple_ctypes.BinaryOp):
        l = gen._eval_const_int(node.left)
        r = gen._eval_const_int(node.right)
        if l is None or r is None: return None
        ops = {'+': l+r, '-': l-r, '*': l*r, '//': l//r if r else None,
               '%': l%r if r else None, '**': l**r,
               '==': int(l == r), '!=': int(l != r), '<': int(l < r),
               '<=': int(l <= r), '>': int(l > r), '>=': int(l >= r)}
        return ops.get(node.op)
    if isinstance(node, gimple_ctypes.CompareChain):
        # Same short-circuit chained-comparison semantics as
        # eval_CompareChain (myinterpreter.py) / _lower_compare_chain,
        # just over compile-time constants instead of runtime values.
        left = gen._eval_const_int(node.operands[0])
        if left is None: return None
        for op, operand in zip(node.ops, node.operands[1:]):
            right = gen._eval_const_int(operand)
            if right is None: return None
            link = gen._eval_const_compare_op(op, left, right)
            if link is None: return None
            if not link: return 0
            left = right
        return 1
    # comptime call to an imported function with constant args (slice 3):
    # run it at compile time as cached machine code via comptime.evaluate.
    if isinstance(node, gimple_ctypes.CallExpr) and isinstance(node.func, gimple_ctypes.IdentExpr):
        src_path = gen._imported_fn_sources.get(node.func.name)
        if src_path:
            argvals = [gen._eval_const_int(a) for a in node.args]
            if argvals and all(v is not None for v in argvals):
                try:
                    # importlib (NOT a bare `import` statement): gen_module's
                    # find_imports AST-walk collects every ImportStmt at any
                    # nesting depth and would inline elaborate.py/comptime.py
                    # into the self-host closure — compiler-core sources that
                    # were never GIMPLE-clean. import_module is invisible to
                    # that walk while resolving identically at runtime.
                    import importlib as _importlib
                    _elab = _importlib.import_module('elaborate')
                    _comptime = _importlib.import_module('comptime')
                    module_src = open(src_path).read()
                    fn_src = _elab.extract_fn_source(module_src, node.func.name)
                    if fn_src:
                        return int(_comptime.evaluate(fn_src, node.func.name, argvals))
                except Exception:
                    gimple_ctypes._debug_note('comptime evaluation failed', node.func.name)
    return None


def _eval_const_bool(gen, node) -> bool | None:
    """Evaluate an expression as a compile-time bool, or return None."""
    v = gen._eval_const(node)
    if isinstance(v, (bool, int)):
        return bool(v)
    # Fallback: _eval_const_int handles CallExpr (comptime function calls),
    # which _eval_const above does not.
    result = gen._eval_const_int(node)
    return bool(result) if isinstance(result, (bool, int)) else None
    return None

def _split_top_level_comma(s: str) -> list[str]:
    """Split s by top-level commas only (bracket-aware)."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(s):
        if c in '([': depth += 1
        elif c in ')]': depth -= 1
        elif c == ',' and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
    parts.append(s[start:].strip())
    return parts

def _dedup_variadic_externs(parts: list) -> str:
    """Join the preamble, dropping a variadic `extern T name (...);` import
    declaration when a CONCRETE prototype for the same function is also present
    (e.g. an elaborated instantiation forward-declares `get_defined_int (void)`
    while the import-decl pass emits `(...)`, which GCC reports as conflicting
    types). The concrete prototype wins.

    Deliberately plain string scanning (`.split`/`.find`/`.rfind`), NOT
    regex `.finditer()`/`.findall()` — this codegen has no lowering for
    either shape of for-loop (finditer needs a compile-time-known
    module-level pattern var; findall has no lowering at all, confirmed
    directly: `for w in pat.findall(s): ...` emits `mojo_unsupported_iter`
    even outside self-hosting), so a loop here over either would silently
    run zero times once this file compiles itself."""
    def _is_extern_decl(stmt: str) -> bool:
        # A genuine `extern ...;` declaration always has "extern" as the
        # first token of ONE of its (possibly preprocessor-guard-
        # prefixed) lines — checking the fragment for the bare
        # SUBSTRING "extern" is not enough: a `#line N "path/to/
        # test_external_call.mojo"` directive immediately followed by
        # an ordinary function CALL statement (e.g. `std_testing___
        # init___assert_false (_t5)`) also contains "extern" — as a
        # substring of "external" in the source filename — which wrongly
        # classified that CALL as a concrete prototype for
        # `std_testing___init___assert_false`, causing the REAL
        # variadic extern declarations for it to be dropped everywhere
        # ("implicit declaration of function" once compiled). Real
        # regression, found via compile_stdlib.py's
        # test/ffi/test_external_call.mojo.
        for line in stmt.split('\n'):
            line = line.strip()
            if line == 'extern' or line.startswith('extern ') or line.startswith('extern"'):
                return True
        return False

    concrete = set()
    for p in parts:
        for stmt in p.split(';'):
            if not _is_extern_decl(stmt):
                continue
            paren = stmt.find('(')
            if paren < 0:
                continue
            close = stmt.rfind(')')
            if close < paren:
                continue
            params = stmt[paren + 1:close].strip()
            head_toks = stmt[:paren].strip().split()
            if not head_toks:
                continue
            name = head_toks[-1].lstrip('*')
            if params not in ('...', ''):
                concrete.add(name)
    if not concrete:
        return '\n'.join(parts)
    kept = []
    for p in parts:
        drop = False
        for stmt in p.split(';'):
            if not _is_extern_decl(stmt):
                continue
            paren = stmt.find('(')
            if paren < 0:
                continue
            close = stmt.rfind(')')
            if close < paren:
                continue
            params = stmt[paren + 1:close].strip()
            if params != '...':
                continue
            head_toks = stmt[:paren].strip().split()
            if not head_toks:
                continue
            name = head_toks[-1].lstrip('*')
            if name in concrete:
                drop = True
                break
        if not drop:
            kept.append(p)
    return '\n'.join(kept)
