"""Module loader for stdlib imports.

Resolves and loads .mojo module files from the official stdlib.
Parses imported modules and makes symbols available to the codegen.
"""
import os
import ctypes
from pathlib import Path

# C keywords / gcc-reserved identifiers that cannot be used as parameter
# names in a generated extern (mirrors gimple_codegen._C_KEYWORDS +
# _C_PARAM_EXTRA_KEYWORDS). The scanner sanitizes param names against these.
_C_KEYWORDS = frozenset({
    'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do',
    'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if',
    'inline', 'int', 'long', 'register', 'restrict', 'return', 'short',
    'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union',
    'unsigned', 'void', 'volatile', 'while',
    '_Bool', '_Complex', '_Imaginary', '_Alignas', '_Alignof', '_Atomic',
    '_Generic', '_Noreturn', '_Static_assert', '_Thread_local',
    'nullptr', 'constexpr', 'thread_local', 'static_assert', 'typeof_unqual',
    'asm', '__asm__', 'typeof', '__typeof__',
})

HERE = os.path.dirname(os.path.abspath(__file__))


def _ml_as_str(e: object) -> str:
    """Re-tag a value the self-hosted backend erased to int64_t back to `str`.
    Identity on CPython; the char* bits are intact, only the static type was lost.
    Used at signature-string interpolation sites so an erased `c_return_type`
    prints its text, not its pointer address (determinism)."""
    return e


def _mkfn(sig):
    before_paren = sig.split('(')[0].strip()
    parts = before_paren.rsplit(None, 1)  # split on last whitespace token
    ret = 'void'
    if len(parts) > 1:
        ret = parts[0].strip()
    return {'c_return_type': ret, 'c_parameters': [], 'signature': sig,
            'return_type': ret, 'parameters': []}


_TESTING_EXPORTS = {
    'assert_equal':        _mkfn('void assert_equal (...)'),
    'assert_true':         _mkfn('void assert_true (...)'),
    'assert_false':        _mkfn('void assert_false (...)'),
    'assert_almost_equal': _mkfn('void assert_almost_equal (...)'),
    'assert_raises':       _mkfn('void assert_raises (...)'),
    'assert_not_equal':    _mkfn('void assert_not_equal (...)'),
}


# Reflection table layout (mirrors reflect.h). Defined at module scope — NOT
# nested inside read_reflection — so the self-host codegen emits their struct
# typedefs at top level (a class nested in a function is referenced but never
# declared in the generated C).
class _ReflectSym(ctypes.Structure):
    _fields_ = [('name', ctypes.c_char_p), ('signature', ctypes.c_char_p),
                ('addr', ctypes.c_void_p), ('kind', ctypes.c_int32)]


class _ReflectTable(ctypes.Structure):
    _fields_ = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
                ('n_syms', ctypes.c_uint32), ('reserved', ctypes.c_uint32),
                ('syms', ctypes.POINTER(_ReflectSym))]

def _find_stdlib_path():
    """Find stdlib path using multiple strategies.

    1. Check MOJO_STDLIB environment variable
    2. Look relative to this file (project root structure: ../mojo/3rdparty/...)
    3. Search upward from current directory
    4. Return path (will fail gracefully if not found at runtime)
    """
    # Strategy 1: Environment variable override
    if 'MOJO_STDLIB' in os.environ:
        path = os.environ['MOJO_STDLIB']
        if os.path.isdir(path):
            return path

    # Strategy 2: Hardcoded path to stdlib
    abs_path = '/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib'
    if os.path.isdir(abs_path):
        return abs_path

    # Strategy 3: Search upward from current working directory
    cwd = os.path.abspath(os.getcwd())
    for _ in range(10):  # Search up to 10 levels
        # Look for modular/... at current level
        candidate = os.path.join(cwd, 'modular', 'mojo', 'stdlib')
        if os.path.isdir(candidate):
            return candidate
        cwd = os.path.dirname(cwd)
        if cwd == '/':
            break

    # Fallback: return the computed path (runtime will handle missing stdlib gracefully)
    return abs_path

STDLIB_PATH = _find_stdlib_path()
TEST_PATH = os.path.join(HERE, 'runtime')  # For test modules


def module_name_for_path(path: str) -> str:
    """Path-relative module name so __init__.mojo files from different
    packages get unique symbol prefixes (std_os___init__ vs std___init__).
    Falls back to basename for modules outside STDLIB_PATH (e.g. test
    modules) — os.path.relpath would produce '../../../...' paths with dots
    that are invalid in C identifiers and cause GCC to reject the generated
    .c file.

    Single source of truth for "which module owns this file", shared by
    build_stdlib_dylib.py (compiling a module to its own .o) and
    gimple_codegen.py (resolving an imported struct's home module at a
    cross-module call site) — both MUST derive a struct's module-qualified
    C symbol from the exact same function applied to the exact same
    resolved file path, or the two sides can disagree (e.g. a naive
    dotted-import-string transform like 'std.os'.replace('.', '_') gives
    'std_os', but a struct physically defined in std/os/__init__.mojo needs
    'std_os___init__' to match what this function returns when compiling
    that file directly) — that divergence would turn "module qualification"
    into a NEW class of undefined-symbol linker error. See ABI.md's
    "Functions and methods" section and STDLIB-BUGS.md for the collision
    class this fixes."""
    rel = os.path.relpath(path, STDLIB_PATH)
    if rel.startswith('..'):
        return os.path.splitext(os.path.basename(path))[0].replace('-', '_')
    return os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')


class ModuleLoader:
    """Loads and caches Mojo modules from stdlib."""

    def __init__(self):
        self.loaded_modules = {}  # module_path -> parsed AST
        self.exported_symbols = {}  # (module, name) -> type_info
        self._path_cache = {}  # absolute file path -> exports (see load_module_from_path)

    def can_resolve_module_path(self, module_name: str) -> bool:
        """Non-raising predicate mirroring `resolve_module_path`'s own
        acceptance test (test-module-under-TEST_PATH, or `std`/`std.*`).
        Callers on the compiled backend must use this to GUARD a call to
        `resolve_module_path`/`load_module` rather than wrapping the call
        in try/except: this codegen's compiled `try`/`except` does not
        reliably catch a raised exception (a documented gap — see the
        `_is_py_sibling` pre-filter comments in gimple_gen_infra.py /
        gimple_gen_funcs.py), so a genuine non-stdlib Python import (e.g.
        `from dataclasses import dataclass`, real stdlib source this
        project's own `myinterpreter.py` uses) reached `resolve_module_
        path`'s `raise` UNCAUGHT and crashed the whole
        `MOJO_NO_SHIM=1 --dump` compile instead of just skipping that
        one import's externs."""
        parts = module_name.split('.')
        if len(parts) == 1 and not parts[0].startswith('std'):
            if os.path.exists(os.path.join(TEST_PATH, parts[0] + '.mojo')):
                return True
        return parts[0] == 'std'

    def resolve_module_path(self, module_name: str) -> str:
        """Convert module name to file path.

        std.memory → .../stdlib/std/memory/__init__.mojo
        std.memory.Pointer → .../stdlib/std/memory/__init__.mojo (same module)
        test_helper → .../runtime/test_helper.mojo (for testing)
        """
        parts = module_name.split('.')

        # Check for test modules first (simple names like 'test_helper')
        if len(parts) == 1 and not parts[0].startswith('std'):
            test_file = os.path.join(TEST_PATH, parts[0] + '.mojo')
            if os.path.exists(test_file):
                return test_file

        # Standard stdlib imports
        if parts[0] != 'std':
            raise ValueError(f"Only stdlib and test imports supported: {module_name}")

        # Build path: std/submodule/__init__.mojo
        path_parts = [STDLIB_PATH] + parts + ['__init__.mojo']
        path = os.path.join(*path_parts)

        # Fallback: try just the submodule file
        if not os.path.exists(path):
            alt_parts = [STDLIB_PATH] + parts[:-1] + [parts[-1] + '.mojo']
            alt_path = os.path.join(*alt_parts)
            if os.path.exists(alt_path):
                return alt_path

        return path

    def load_module(self, module_name: str) -> dict:
        """Load a module and extract exported symbols with full signatures.

        Returns dict mapping symbol names to their type info:
          {
            'symbol_name': {
              'return_type': 'int',
              'parameters': [('param_name', 'int'), ...],
              'signature': 'int symbol_name (int param_name, ...)'
            },
            ...
          }
        """
        if module_name in self.loaded_modules:
            return self.loaded_modules[module_name]

        # Hardcoded exports for modules whose signatures the simple parser cannot parse
        _HARDCODED = {
            'std.testing': _TESTING_EXPORTS,
            'std.testing.testing': _TESTING_EXPORTS,
            'testing': _TESTING_EXPORTS,
        }
        if module_name in _HARDCODED:
            self.loaded_modules[module_name] = _HARDCODED[module_name]
            return _HARDCODED[module_name]

        path = self.resolve_module_path(module_name)
        exports = self.load_module_from_path(path)
        self.loaded_modules[module_name] = exports
        return exports

    # Cache for load_module_from_path, keyed by absolute file path — separate
    # from `loaded_modules` (keyed by the STDLIB-resolved module NAME string,
    # which a local/sibling project module never has: resolve_module_path
    # raises "Only stdlib and test imports supported" for anything not under
    # STDLIB_PATH/TEST_PATH). Callers that already resolved an arbitrary
    # local .mojo file's path themselves (e.g. gimple_codegen.py's sibling-
    # import fallback for `mojo dylib`'s per-module standalone compiles,
    # which resolves local project modules via imports.resolve_source /
    # _resolve_test_relative_module instead of this class's stdlib-only
    # resolve_module_path) call this directly, keeping the exact same
    # signature-extraction logic `load_module` itself uses for stdlib/test
    # modules — one implementation, two entry points, per this project's
    # "consolidate, don't duplicate" convention. (self._path_cache is set
    # up in __init__.)
    def load_module_from_path(self, path: str) -> dict:
        """Extract exported fn/def signatures from an ARBITRARY .mojo file
        path (no STDLIB_PATH/TEST_PATH restriction — see docstring above).
        Same text-scan/`_mojo_type_to_c` logic `load_module` uses once it
        has resolved a stdlib/test module name to a path; factored out so
        both a name-based stdlib/test lookup and a path-based local-sibling
        lookup share one implementation."""
        if path in self._path_cache:
            return self._path_cache[path]

        if not path or not os.path.exists(path):
            self._path_cache[path] = {}
            return {}

        try:
            with open(path, 'r') as f:
                content = f.read()

            exports = {}

            # BUG-2026-023 (box.3d/game): the C-stdlib skip below exists to
            # keep THIS compiler's prelude headers (stdio's remove/rename,
            # math's nan/abs, ...) from conflicting with an unqualified
            # extern — a concern that only applies to STDLIB/TEST modules,
            # whose exported symbols the extern-emission pass emits under
            # their bare C names. A LOCAL PROJECT module (game mod code:
            # `def remove(t: Tuff, amount: Int) -> Int` in tuff.mojo) is
            # compiled with its symbols module-qualified AND
            # overload-suffix-mangled (`mod_tuff_tuff_remove_2ea17f`), so a
            # same-named C stdlib function can never collide — but skipping
            # it here silently DELETED the export, the importer's
            # FromImportStmt registration then marked the alias unresolved,
            # and every call site bound to a weak "unavailable in compiled
            # mode" stub that returned 0 instead of mutating (the exact
            # "remove/craft leave counts unchanged" signature of
            # BUG-2026-023). Apply the filter ONLY when scanning this
            # compiler's own stdlib/test trees.
            _apply_c_stdlib_skip = path.startswith(STDLIB_PATH + os.sep) or \
                path.startswith(TEST_PATH + os.sep)

            # C standard library function names that are already declared by
            # our prelude headers (stdint/stdlib/string/math/stdio). Returning
            # them from load_module would cause _emit_stdlib_import_externs to
            # emit a conflicting extern (e.g. int64_t nan(void) vs double
            # nan(const char *) from <math.h>).
            _C_STDLIB_SKIP = frozenset({
                'abort', 'exit', '_exit',
                'malloc', 'calloc', 'realloc', 'free',
                'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
                'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy',
                'strcat', 'strncat', 'strstr', 'strchr', 'strrchr',
                'strtok', 'strerror', 'strdup', 'strndup',
                'printf', 'fprintf', 'sprintf', 'snprintf',
                'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell',
                'fflush', 'fgets', 'fputs', 'feof', 'ferror', 'fileno',
                'stdin', 'stdout', 'stderr',
                'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2',
                'sinh', 'cosh', 'tanh',
                'sqrt', 'cbrt', 'pow', 'exp', 'log', 'log2', 'log10',
                'ceil', 'floor', 'round', 'trunc',
                'fabs', 'fmod', 'hypot',
                'nan', 'nanf',
                'rand', 'srand', 'abs',
                'getenv', 'setenv', 'unsetenv',
                'system', 'atexit',
                'remove', 'rename',
                'time', 'clock', 'difftime', 'mktime',
                'localtime', 'gmtime', 'asctime', 'ctime', 'strftime',
                'signal', 'raise',
                'dlopen', 'dlsym', 'dlclose', 'dlerror',
                'index', 'rindex',
                'isalpha', 'isdigit', 'isalnum', 'isspace',
                'isupper', 'islower', 'toupper', 'tolower',
            })

            def _scan_source(src_content):
                """Extract fn/def exports from Mojo source text into exports dict."""
                # Pre-pass: count how many times each bare name is DEFINED
                # (fn/def), including multi-line signatures. Names defined more
                # than once are overloaded; the single-signature model can't
                # represent them, so they are emitted as a variadic extern
                # `name(...)` which accepts any call arity (the codegen's
                # _resolve_overload handles real overloads for local functions;
                # this only affects imported externs). Without this, a
                # multi-line overload (e.g. std.math.iota's 3-param
                # UnsafePointer version) is invisible to the single-line scan,
                # leaving a wrong-arity extern that breaks its call sites.
                _overloaded: set = set()
                _name_counts: dict = {}
                for _l in src_content.split('\n'):
                    _l = _l.strip()
                    if _l.startswith('fn ') or _l.startswith('def '):
                        _n = _l[3:] if _l.startswith('fn ') else _l[4:]
                        _n = _n.split('[')[0].split('(')[0].strip()
                        if _n and (not _apply_c_stdlib_skip or _n not in _C_STDLIB_SKIP):
                            _name_counts[_n] = _name_counts.get(_n, 0) + 1
                _overloaded = {n for n, c in _name_counts.items() if c > 1}

                # NOTE: a function whose signature includes a struct type
                # defined in ANOTHER file (e.g. box.3d/game's real
                # `chest_total_count(c: Chest, item_id: UInt64)`) is a KNOWN,
                # separate, deeper gap this text-only scan does not attempt
                # to solve: this scan's blind int64_t default for `Chest`
                # disagrees with the struct's own defining module's real,
                # struct_field_types-aware C parameter type, so the overload-
                # suffix hash this scan computes for such a function can
                # differ from the hash its own compile actually used —
                # producing an honest undefined-symbol link/dlopen failure
                # for THAT function specifically, not the silent wrong-value
                # weak-stub binding this whole fix (see bugs/DYLIB_sibling_
                # import_calls_bind_to_weak_stubs.md) addresses for ordinary
                # (scalar-signature) functions. A local `struct Name` pre-
                # scan promoting such params to `Name *` was tried and
                # reverted: while it fixes the HASH, the extern declaration
                # text this scan emits into a DIFFERENT file's own
                # translation unit then references `Name` as a bare type
                # with no typedef/forward-declaration visible there (the
                # established convention for a genuinely cross-TU struct
                # reference this codebase already uses elsewhere — see
                # gimple_codegen.py's Span/StringSlice handling in
                # `_mojo_type_to_c` — is an opaque int64_t handle, not the
                # literal struct pointer type), which broke unrelated,
                # previously-working cross-module calls elsewhere in the
                # same file (confirmed: box.3d/game/lib/game_ffi.mojo
                # regressed from a clean build to "unknown type name
                # 'World'" compile errors). Solving this correctly needs the
                # real struct-materialization machinery (_find_imported_
                # struct / struct_field_types) this text scan deliberately
                # doesn't have — out of scope here; left as an honest
                # (link-time, not silent) failure for that narrower case.

                for line in src_content.split('\n'):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    # Match 'fn name(...) -> Type:' or 'fn name(...)'
                    if line.startswith('fn ') or line.startswith('def '):
                        # Remove 'fn ' or 'def '
                        is_fn = line.startswith('fn ')
                        sig = line[3:] if is_fn else line[4:]

                        # Extract function name and parameters
                        if '(' not in sig or ')' not in sig:
                            continue

                        paren_start = sig.index('(')
                        paren_end = sig.rindex(')')

                        name_part = sig[:paren_start].strip()
                        # Strip generic parameters first (e.g.,
                        # 'listdir[PathLike]' → 'listdir') before
                        # whitespace split, since generics contain no
                        # spaces and would become the last token.
                        _brk = name_part.find('[')
                        if _brk >= 0:
                            name = name_part[:_brk].strip().split()[-1]
                        else:
                            name = name_part.split()[-1] if name_part else ''
                        params_str = sig[paren_start + 1:paren_end].strip()

                        if not name or (_apply_c_stdlib_skip and name in _C_STDLIB_SKIP):
                            continue

                        # Extract return type
                        return_type = 'int'  # default
                        if '->' in sig:
                            after_arrow = sig.split('->')[-1].split(':')[0].strip()
                            return_type = after_arrow if after_arrow else 'int'

                        # Extract parameters as list of (name, type) tuples
                        _MOJO_PARAM_MODS = {'var', 'owned', 'inout', 'borrowed', 'mut',
                                            'ref', 'out', 'copy', 'read', 'write'}
                        parameters = []
                        if params_str:
                            for param in params_str.split(','):
                                param = param.strip()
                                if ':' in param:
                                    param_name, param_type = param.split(':', 1)
                                    # Strip Mojo mutability keywords from parameter name
                                    words = param_name.strip().split()
                                    words = [w for w in words if w not in _MOJO_PARAM_MODS]
                                    param_name = words[-1] if words else '_p'
                                    param_type = param_type.strip()
                                    parameters.append((param_name, param_type))

                        # Build C signature from extracted info
                        try:
                            c_return_type = _ml_as_str(self._mojo_type_to_c(return_type))
                        except Exception:
                            c_return_type = 'int64_t'
                        c_params = []
                        _star_idx = None
                        for idx_p, (pname, ptype) in enumerate(parameters):
                            if pname.startswith('*'):
                                _star_idx = idx_p
                                break
                        # Sanitize C-keyword param names (asm, sizeof, etc.) the
                        # same way gimple_codegen._safe_field does — the extern's
                        # param list must be valid C. Inlined (no nested closure)
                        # so the self-host compiler handles it.
                        def _safe_pn(pn):
                            if pn in _C_KEYWORDS:
                                return '_kw_' + pn
                            return pn
                        if _star_idx is not None:
                            # Fixed params come first, then the '...' packing
                            # sentinel ONLY when *args is the last parameter.
                            # If *args is followed by (keyword-only) params, the
                            # single-signature model can't represent them after
                            # '...' in C — drop the trailing params rather than
                            # emit an invalid `(..., x)`.
                            for (pname, ptype) in parameters[:_star_idx]:
                                if '=' in ptype:
                                    bare_type = ptype.split('=')[0].strip()
                                else:
                                    bare_type = ptype
                                try:
                                    c_type = self._mojo_type_to_c(bare_type)
                                except Exception:
                                    c_type = 'int64_t'
                                if c_type == 'void':
                                    c_type = 'int64_t'
                                c_params.append(f"{c_type} {_safe_pn(pname)}")
                            c_params.append('...')
                        else:
                            for pname, ptype in parameters:
                                # Strip default values (e.g., 'String = ""' becomes 'String')
                                if '=' in ptype:
                                    bare_type = ptype.split('=')[0].strip()
                                else:
                                    bare_type = ptype
                                try:
                                    c_type = self._mojo_type_to_c(bare_type)
                                except Exception:
                                    c_type = 'int64_t'
                                # A named parameter can never be typed 'void' in C
                                # (only the sole, unnamed '(void)' no-args marker is
                                # legal) -- e.g. a parameter annotated `: None`
                                # resolves to 'void' via _mojo_type since that's the
                                # correct RETURN-type mapping for NoneType, but is
                                # invalid here. Box it the same way gimple_codegen.py's
                                # own _param_ctype already does for the exact same
                                # case ("A named PARAMETER can never be typed void").
                                if c_type == 'void':
                                    c_type = 'int64_t'
                                c_params.append(f"{c_type} {_safe_pn(pname)}")

                        if name in exports:
                            existing = exports[name]
                            existing['signature'] = _ml_as_str(existing['c_return_type']) + ' ' + name + ' (...)'
                            existing['c_parameters'] = []
                            existing['parameters'] = []
                            existing['variadic'] = True
                            continue

                        # Overloaded name (defined more than once in this file,
                        # e.g. std.math.iota's several overloads): the single-
                        # signature model can't represent all of them, so emit a
                        # variadic extern `name(...)` that accepts any arity.
                        # This is the LAST overload's return type; the first
                        # single-line overload was parsed above but overloaded
                        # names must be variadic to satisfy every call site.
                        if name in _overloaded:
                            c_signature = _ml_as_str(c_return_type) + ' ' + name + ' (...)'
                            c_params = []
                        else:
                            c_param_str = ', '.join(c_params) if c_params else 'void'
                            c_signature = _ml_as_str(c_return_type) + ' ' + name + ' (' + c_param_str + ')'

                        exports[name] = {
                            'return_type': return_type,
                            'parameters': parameters,
                            'c_return_type': c_return_type,
                            'c_parameters': c_params,
                            'signature': c_signature,
                        }

            # Extract function definitions with full signatures
            _scan_source(content)

            # Self-host `.py` compiler modules: a module-scope
            # `NAME = frozenset({...})` / `NAME = set(...)` global is a real
            # export the `.mojo`-only `var NAME = ...` scan above never saw,
            # so an importer's cross-TU reference (`from gimple_codegen import
            # _C_RESERVED_FUNCS`, itself re-exported from gimple_ctypes) fell
            # to the codegen's "undeclared -> (int64_t)0" path — a NULL set
            # into `mojo_set_difference` / `mojo_set_union` -> segfault in the
            # compiled compile_to_gimple. SCOPED to frozenset/set-CALL RHS
            # only: the compiler's Phase-1.7 global-type inference doesn't
            # recognise `frozenset(...)` so its accessor return type is
            # `int64_t` (boxed pointer) — matching the extern emitted here.
            # Dict / set-LITERAL / list globals get a precise `MojoDict *` /
            # `MojoSet *` accessor from their home compile that a blind
            # int64_t extern here would CONFLICT with, so they are left out
            # (they weren't the crash and their undeclared->0 fallback, while
            # imprecise, is not a hard failure).
            _selfhost_dir = os.path.dirname(os.path.abspath(__file__))
            if path.endswith('.py') and os.path.dirname(os.path.abspath(path)) == _selfhost_dir:
                import re as _re_py
                _pydir = os.path.dirname(path)
                # `NAME = frozenset(...)` / `set(...)` -> boxed int64_t accessor
                # (Phase 1.7 doesn't classify a `frozenset(...)` CALL, so the
                # home emits an int64_t accessor and this extern must match).
                _SET_GLOBAL_RE = _re_py.compile(
                    r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:frozenset|set)\s*\(')
                # `NAME: set = {...}` / `NAME = {x, ...}` / `NAME: dict = {...}`
                # / `NAME = {k: v}` / `NAME: list = [...]` / `NAME = [...]` — a
                # container LITERAL global. The home compile's Phase 1.7 gives
                # these a precise `MojoSet *` / `MojoDict *` / `MojoList *`
                # accessor, so this extern must declare the SAME type (a blind
                # int64_t extern would `conflicting types` against the home
                # definition). Without exporting them at all, a re-exported
                # such global (`from generated_dispatch import _CMP_OPS as
                # _GD_CMP_OPS` in gimple_ctypes.py) fell to codegen's
                # "undeclared -> (int64_t)0" -> NULL set into
                # `mojo_set_contains_str` -> SEGV lowering any BinaryOp.
                #
                # SCOPED to `generated_dispatch.py`: it is nothing BUT
                # cross-module dispatch-table container globals, every one of
                # which its home compile emits a `__mojo_global_get_` accessor
                # for. A broader match hits modules (gimple_codegen.py,
                # gimple_ctypes.py) whose same-named `{...}` globals are also
                # locally re-defined / imported both ways, so the importer
                # extern raced the home's own decl -> `conflicting types for
                # 'gimple_codegen__mojo_global_get__RUNTIME_FUNCS'`.
                _scan_container_literals = (
                    os.path.basename(path) == 'generated_dispatch.py')
                _CONTAINER_GLOBAL_RE = _re_py.compile(
                    r'^([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*([A-Za-z_][\w.\[\], ]*?))?\s*=\s*([\{\[])')
                _local_set_globals = set()
                for _line in content.split('\n'):
                    if not _line or _line[0] in ' \t#':
                        continue
                    _ls = _line.rstrip()
                    _m = _SET_GLOBAL_RE.match(_ls)
                    if _m and _m.group(1) not in exports:
                        _local_set_globals.add(_m.group(1))
                        exports[_m.group(1)] = {
                            'kind': 'global_var', 'c_return_type': 'int64_t',
                            'home_module_path': path}
                        continue
                    if not _scan_container_literals:
                        continue
                    _cm = _CONTAINER_GLOBAL_RE.match(_ls)
                    if not _cm or _cm.group(1) in exports:
                        continue
                    _nm, _ann, _open = _cm.group(1), (_cm.group(2) or '').strip(), _cm.group(3)
                    _annb = _ann.split('[', 1)[0].strip().lower()
                    if _annb in ('dict', 'mapping'):
                        _crt = 'MojoDict *'
                    elif _annb in ('set', 'frozenset'):
                        _crt = 'MojoSet *'
                    elif _annb in ('list', 'tuple', 'sequence'):
                        _crt = 'MojoList *'
                    elif _open == '[':
                        _crt = 'MojoList *'
                    else:
                        # `{...}` with no annotation — a set literal `{a, b}` or
                        # a dict literal `{k: v}`. `:` at brace-depth 1 before
                        # the first top-level `,` means dict.
                        _body = _ls[_ls.index('{') + 1:]
                        _depth, _is_dict = 1, False
                        for _ch in _body:
                            if _ch in '([{':
                                _depth += 1
                            elif _ch in ')]}':
                                _depth -= 1
                                if _depth == 0:
                                    break
                            elif _ch == ':' and _depth == 1:
                                _is_dict = True
                                break
                            elif _ch == ',' and _depth == 1:
                                break
                        _crt = 'MojoDict *' if _is_dict else 'MojoSet *'
                    _local_set_globals.add(_nm)
                    exports[_nm] = {
                        'kind': 'global_var', 'c_return_type': _crt,
                        'home_module_path': path}
                # Re-exports: `from SIBLING import (a, b)` — a set global not
                # defined locally but surfaced through this module carries the
                # sibling's own home accessor.
                _reexp = _re_py.findall(
                    r'^from\s+([A-Za-z_][\w.]*)\s+import\s+\(([^)]*)\)',
                    content, _re_py.MULTILINE)
                _reexp += [(m.group(1), m.group(2)) for m in _re_py.finditer(
                    r'^from\s+([A-Za-z_][\w.]*)\s+import\s+([^\n(]+)$', content, _re_py.MULTILINE)]
                for _srcmod, _names_blob in _reexp:
                    _sib = os.path.join(_pydir, _srcmod.split('.')[-1] + '.py')
                    if not os.path.isfile(_sib) or _sib == path:
                        continue
                    _sib_exp = self.load_module_from_path(_sib)
                    for _nm in _re_py.findall(r'[A-Za-z_][A-Za-z0-9_]*', _names_blob):
                        _si = _sib_exp.get(_nm)
                        if (isinstance(_si, dict) and _si.get('kind') == 'global_var'
                                and _si.get('c_return_type') in (
                                    'int64_t', 'MojoSet *', 'MojoDict *', 'MojoList *')
                                and _nm not in exports):
                            exports[_nm] = dict(_si)

            # Extract module-scope PLAIN `var NAME = EXPR` globals (not
            # `comptime` — those are handled separately, by re-parsing and
            # constant-folding the imported module's own source directly at
            # the call site in gimple_codegen.py's `_prefold_imported_
            # comptime`, since a comptime constant's VALUE — not a runtime
            # symbol reference — is what a bare cross-module import needs).
            # See BUG-2026-009 (box.3d/game): a bare `from X import
            # <module_global>` for a plain `var` was previously invisible
            # to this scanner entirely (only fn/def signatures were ever
            # extracted here), so `_emit_stdlib_import_externs`/its callers
            # in gimple_codegen.py had no way to know the name even existed,
            # let alone that it needs a real cross-translation-unit
            # reference into the DEFINING module's own storage — the
            # importing module's own compile (each `mojo dylib` module is a
            # fully independent translation unit — see driver.compile_dylib)
            # silently fell through to codegen's "unknown identifier"
            # placeholder (0 / NULL), reading zero or segfaulting on a
            # stale/garbage pointer instead. This entry is consumed by
            # gimple_codegen.py's `_emit_imported_global_accessors`, which
            # declares a real `extern <c_type> <mod>__mojo_global_get_<name>
            # (void);` and routes any bare read of the imported name through
            # a call to it — a synthesized accessor function the DEFINING
            # module (see gen_module's own "Module-level globals" emission)
            # unconditionally exports for every one of its own module-scope
            # `var` globals, mirroring how every free function is already
            # unconditionally exported (no separate "who imports me"
            # tracking needed on the defining side).
            #
            # Deliberately NOT using an AST parse here (this whole file's
            # established convention — see `_scan_source`'s own docstring
            # comparison to gimple_codegen.py — is a fast, dependency-free
            # text scan, the same approach already used for fn/def). Only a
            # top-level (column-0, no indent) `var NAME = EXPR` line counts;
            # anything inside a function/struct body is indented and never
            # matches. `EXPR`'s own shape (not its evaluated value — this
            # scanner cannot evaluate arbitrary expressions) picks the C
            # return type: a scalar literal shape maps to the same concrete
            # C type gimple_codegen.py's own real compile would give it;
            # everything else (in particular a constructor call like
            # `World()`) defaults to `int64_t`, matching this codebase's
            # established convention that a struct-instance global is always
            # stored/returned as a boxed pointer via int64_t (see
            # gimple_codegen.py's own "Globals are stored at C level as
            # int64_t (boxed pointers)..." — the SAME default this scanner
            # mirrors here so both sides of the accessor call agree on the
            # return type without either side needing to know the other's
            # verdict in advance).
            import re as _re
            # BUG-2026-029 cross-file follow-up: a DECLARATION-ONLY global
            # (`var g_world: World`, no `= EXPR` — the real box.3d/game
            # shape, assigned later inside `ffi_init()`) never matched this
            # regex at all before (the trailing `=\s*(.+?)` was mandatory),
            # so `g_world` was invisible to this scanner entirely and a
            # cross-file `from game_ffi import g_world` in engine_world.mojo
            # fell straight through to codegen's "undeclared -> 0"
            # placeholder — with or without reflect.py's own same-file-only
            # struct-global gap (a SEPARATE mechanism entirely: this
            # `load_module_from_path` scan is what `mojo dylib`'s per-module-
            # independent compile actually consults via
            # `_local_sibling_module_exports` / `_emit_imported_global_
            # accessors`, not reflect.py's `collect_exports`/
            # `_register_link_imports`, which is `mojo build`'s link-mode-
            # only path). The `(?:=\s*(?P<rhs>.+?))?` group is now optional;
            # a bare `var NAME: Type` (or untyped `var NAME`, though Mojo
            # requires an annotation or initializer) still exports an entry.
            _VAR_GLOBAL_RE = _re.compile(
                r'^var\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*(?P<ann>[^=]+?))?'
                r'\s*(?:=\s*(?P<rhs>.+?))?\s*$')
            for _line in content.split('\n'):
                if not _line or _line[0] in ' \t#':
                    continue   # indented (not top-level) or a comment
                _m = _VAR_GLOBAL_RE.match(_line.strip()) if _line.strip().startswith('var ') else None
                if not _m:
                    continue
                _vname = _m.group(1)
                _vrhs = (_m.group('rhs') or '').strip()
                _vann = (_m.group('ann') or '').strip()
                if _vname in exports or (_apply_c_stdlib_skip and _vname in _C_STDLIB_SKIP):
                    continue   # a same-named fn/def export always wins
                _SCALAR_INT_ANNS = frozenset({
                    'Int', 'Int8', 'Int16', 'Int32', 'Int64',
                    'UInt', 'UInt8', 'UInt16', 'UInt32', 'UInt64',
                })
                if not _vrhs:
                    # Declaration-only global (BUG-2026-029): no RHS shape to
                    # read, so classify from the type annotation instead —
                    # the same handful of scalar C types the RHS-shape branch
                    # below already special-cases. A struct/custom/unresolved
                    # annotation (e.g. `World`) gets `void *`, NOT `int64_t`:
                    # BUG-2026-030's "structs are always T *" convention means
                    # the REAL accessor gen_module emits for a struct-typed
                    # global genuinely returns a pointer type — an `int64_t`
                    # extern here would declare a MISMATCHED prototype in
                    # this (separate) translation unit. Harmless at the ABI
                    # level (both are one register-width value on this
                    # platform, which is exactly why the wider "int64_t
                    # boxed pointer" convention already relies on the same
                    # coincidence elsewhere) but NOT harmless at the Mojo
                    # codegen level: `addr(x)`/pointer-directed lowering
                    # decisions key off whether the C type STRING ends in
                    # ' *' (see gimple_gen_calls.py's `addr()` lowering,
                    # BUG-2026-028) — an `int64_t`-declared accessor for a
                    # struct global made `Int64(addr(g_world))` silently fall
                    # through to the "no real address-of support" branch
                    # instead of recognizing the value as already-a-pointer.
                    _annb = _vann.split('[', 1)[0].strip()
                    if _annb in ('str', 'String', 'StringLiteral', 'StaticString'):
                        _vctype = 'char *'
                    elif _annb == 'Bool':
                        _vctype = '_Bool'
                    elif _annb in ('Float64', 'Float32'):
                        _vctype = 'double'
                    elif _annb in _SCALAR_INT_ANNS:
                        _vctype = 'int64_t'
                    else:
                        _vctype = 'void *'   # struct/custom/unresolved type: real pointer
                elif _vrhs.startswith('"') or _vrhs.startswith("'"):
                    _vctype = 'char *'
                elif _vrhs in ('True', 'False'):
                    _vctype = '_Bool'
                elif _re.match(r'^-?\d+\.\d+', _vrhs):
                    _vctype = 'double'
                elif _re.match(r'^-?\d+$', _vrhs):
                    _vctype = 'int64_t'
                elif _vann.split('[', 1)[0].strip() in _SCALAR_INT_ANNS:
                    # An explicit scalar-int annotation overrides a
                    # non-scalar-looking RHS shape (e.g. `var n: Int64 =
                    # compute()`) — still a real int64_t at the C level,
                    # not a boxed pointer.
                    _vctype = 'int64_t'
                else:
                    # struct instance / call / container / other: real
                    # pointer at the C level (BUG-2026-030's "structs are
                    # always T *"; see the declaration-only branch above for
                    # why `void *`, not `int64_t`, is the correct default
                    # here too — same reasoning, same ABI-identical fix).
                    _vctype = 'void *'
                exports[_vname] = {
                    'kind': 'global_var',
                    'c_return_type': _vctype,
                }

            # Package fallback: when the primary source is __init__.mojo,
            # also scan the same-named sibling file (common Mojo package
            # pattern: std.os/__init__.mojo re-exports from os.mojo, etc.)
            if path.endswith('__init__.mojo'):
                pkg_dir = os.path.dirname(path)
                base_name = os.path.basename(pkg_dir)
                same_name_file = os.path.join(pkg_dir, f'{base_name}.mojo')
                if os.path.isfile(same_name_file) and same_name_file != path:
                    try:
                        with open(same_name_file, 'r') as f:
                            _scan_source(f.read())
                    except Exception:
                        pass

            self._path_cache[path] = exports
            return exports

        except Exception:
            # Gracefully handle parse errors
            self._path_cache[path] = {}
            return {}

    @staticmethod
    def _mojo_type_to_c(mojo_type: str) -> str:
        """Convert Mojo type annotation to C type.

        This used to maintain its own small type_map (a second, independent
        implementation of the same job gimple_codegen.py's `_mojo_type` does)
        with subtly different defaults — most importantly 'Int' → 'int' (a
        32-bit C int) here vs 'int64_t' (Mojo's real 64-bit Int) there, and
        an unknown/unresolved annotation (e.g. a cross-module struct this
        source-only text scan can't see the definition of, like
        `AnyCoroutine`) defaulting to 'int' here vs 'int64_t' there.

        That divergence is not cosmetic: this fallback path's C parameter
        types feed straight into GimpleGen.overload_suffix_for's md5-based
        free-function overload mangling (see gimple_codegen.py's _func_csym).
        A module compiled standalone by build_stdlib_dylib.py (which goes
        through the real GimpleGen/_mojo_type resolver and its int64_t
        default) and a second module that only *imports* the same function
        without a dylib to reflect off of (falling back to this loader,
        module_loader.load_module, for a leading-underscore/unexported name)
        used to compute two DIFFERENT mangled C symbols for the exact same
        function — confirmed root cause of BUG-2026-036's `_coro_destroy_fn`
        dyld crash: coroutine.mojo's own compile emitted
        `_coro_destroy_fn_0c85c9` (int64_t, gimple_codegen's default) while
        device_context.mojo's import of it (routed through this method,
        since `_coro_destroy_fn` starts with `_` and reflect.py never
        exports underscore-prefixed names) computed `int` for the same
        unresolved `AnyCoroutine` parameter and expected
        `_coro_destroy_fn_fa7153` instead — two files disagreeing about one
        function's own C symbol, which crashes `dlopen` regardless of which
        Mojo program is actually run.

        Per CLAUDE.md ("consolidate duplicates ... don't maintain parallel
        implementations"), this delegates to gimple_codegen._mojo_type — the
        codegen's own canonical Mojo-annotation → C-type resolver, already
        reused as-is by reflect.py's `_c_signature` for the dylib-reflection
        import path. Deferred (function-local) import: gimple_codegen.py
        imports `load_module`/`get_symbol_type` from this module at its own
        top level, so a top-level import here would be a circular partial-
        init failure; by the time `load_module` is actually called at
        runtime both modules are fully loaded.
        """
        from gimple_codegen import _mojo_type
        mojo_type = mojo_type.strip()

        # A few shapes this text-only extractor can hand in that aren't a
        # bare Mojo source annotation `_mojo_type` expects — e.g. a type
        # string that already carries a trailing '*' (from a prior C
        # signature re-parse) or the runtime's own boxed-container spelling.
        # Pass everything else straight through to the canonical resolver.
        if mojo_type.endswith('*'):
            base_type = mojo_type[:-1].strip()
            c_base = _mojo_type(base_type)
            return f"{c_base} *"
        if mojo_type.startswith('MojoList'):
            return 'MojoList *'
        if mojo_type.startswith('MojoDict'):
            return 'MojoDict *'
        if mojo_type.startswith('MojoSet'):
            return 'MojoSet *'
        # Bare (unparameterized) `UnsafePointer` with no `[T]` — _mojo_type's
        # bracket handling only fires when it sees '[', so an un-bracketed
        # occurrence would otherwise silently fall to its int64_t catch-all
        # default instead of a pointer type.
        if mojo_type == 'UnsafePointer':
            return 'int64_t *'
        # Span/StringSlice: _mojo_type correctly resolves these to 'Span *'
        # (the fat-pointer struct GimpleGen seeds into struct_field_types
        # and typedefs into the preamble of a module IT is compiling), but
        # this call site emits a bare `extern <type> sym(...);` declaration
        # into a DIFFERENT file's translation unit that has no reason to
        # have that typedef too -- "unknown type name 'Span'". Unlike
        # MojoList/MojoDict/MojoSet (always available via mojo_runtime.h,
        # included everywhere), Span has no globally-available typedef, so
        # box it to the same opaque-handle convention every other
        # not-locally-declared struct type already uses in this codebase
        # (see gimple_codegen.py's _lower_UnaryOp: "Struct types: return
        # int64_t (opaque handle) -- can't cast struct to int64_t in
        # GIMPLE"). Found via build_stdlib_dylib.py regressing to 12 skipped
        # modules ("unknown type name 'Span'") the same day this method
        # started delegating to _mojo_type.
        if mojo_type.split('[', 1)[0].strip() in ('Span', 'StringSlice'):
            return 'int64_t *'
        return _mojo_type(mojo_type)

    def get_symbol_type(self, module_name: str, symbol_name: str) -> str:
        """Get the type of an imported symbol."""
        exports = self.load_module(module_name)
        return exports.get(symbol_name, 'unknown')


def read_reflection(dylib_path: str, runtime_dylib: str = None) -> dict:
    """Read a dylib's `__mojo_reflect` table (reflect.h) — the compiler's import
    path consuming the *same* C-ABI reflection interface any other language uses.
    Returns {name: {'signature': str, 'kind': int, 'addr': int}}.

    This is the structured, ABI-accurate replacement for the line-regex
    signature extraction above: when a prebuilt dylib exists, its self-describing
    table is authoritative.

    Args:
        dylib_path: Path to the module dylib to read
        runtime_dylib: Optional path to the runtime dylib (pre-loaded to resolve symbols)
    """
    # Pre-load runtime dylib if provided, so its symbols are available for the module dylib
    if runtime_dylib and os.path.exists(runtime_dylib):
        try:
            ctypes.CDLL(runtime_dylib)
        except Exception:
            pass  # If runtime dylib can't be loaded, module dylib might still work

    lib = ctypes.CDLL(dylib_path)
    tbl = _ReflectTable.in_dll(lib, '__mojo_reflect')
    if tbl.magic != 0x4D4F4A4F:   # 'MOJO'
        raise ValueError(f"{dylib_path}: not a Mojo reflection table")
    out = {}
    for i in range(tbl.n_syms):
        s = tbl.syms[i]
        name = s.name.decode() if s.name else ''
        if name:
            out[name] = {'signature': s.signature.decode() if s.signature else '',
                         'kind': s.kind, 'addr': s.addr}
    return out


# Global module loader instance
_module_loader = ModuleLoader()


def can_resolve_module_path(module_name: str) -> bool:
    """Module-level wrapper — see ModuleLoader.can_resolve_module_path's
    docstring for why callers on the compiled backend must guard with
    this instead of relying on try/except around `load_module`/
    `resolve_module_path`."""
    return _module_loader.can_resolve_module_path(module_name)


def load_module(module_name: str) -> dict:
    """Load a module and get its exported symbols."""
    return _module_loader.load_module(module_name)


def load_module_from_path(path: str) -> dict:
    """Load a module's exported symbols from an arbitrary file path (no
    STDLIB_PATH/TEST_PATH restriction — see ModuleLoader.load_module_from_path)."""
    return _module_loader.load_module_from_path(path)


def get_symbol_type(module_name: str, symbol_name: str) -> str:
    """Get the inferred type of an imported symbol."""
    return _module_loader.get_symbol_type(module_name, symbol_name)
