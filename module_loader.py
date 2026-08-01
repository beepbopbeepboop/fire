"""Module loader for stdlib imports.

Resolves and loads .mojo module files from the official stdlib.
Parses imported modules and makes symbols available to the codegen.
"""
import os
import ctypes
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))


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

        if not os.path.exists(path):
            # Gracefully degrade: return empty exports if module not found
            self.loaded_modules[module_name] = {}
            return {}

        try:
            with open(path, 'r') as f:
                content = f.read()

            exports = {}

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

                        if not name or name in _C_STDLIB_SKIP:
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
                        c_return_type = self._mojo_type_to_c(return_type)
                        c_params = []
                        for pname, ptype in parameters:
                            # Strip default values (e.g., 'String = ""' becomes 'String')
                            if '=' in ptype:
                                bare_type = ptype.split('=')[0].strip()
                            else:
                                bare_type = ptype
                            c_type = self._mojo_type_to_c(bare_type)
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
                            c_params.append(f"{c_type} {pname}")

                        if name in exports:
                            existing = exports[name]
                            existing['signature'] = f"{existing['c_return_type']} {name} (...)"
                            existing['c_parameters'] = []
                            existing['parameters'] = []
                            existing['variadic'] = True
                            continue

                        c_param_str = ', '.join(c_params) if c_params else 'void'
                        c_signature = f"{c_return_type} {name} ({c_param_str})"

                        exports[name] = {
                            'return_type': return_type,
                            'parameters': parameters,
                            'c_return_type': c_return_type,
                            'c_parameters': c_params,
                            'signature': c_signature,
                        }

            # Extract function definitions with full signatures
            _scan_source(content)

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

            self.loaded_modules[module_name] = exports
            return exports

        except Exception:
            # Gracefully handle parse errors
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


def load_module(module_name: str) -> dict:
    """Load a module and get its exported symbols."""
    return _module_loader.load_module(module_name)


def get_symbol_type(module_name: str, symbol_name: str) -> str:
    """Get the inferred type of an imported symbol."""
    return _module_loader.get_symbol_type(module_name, symbol_name)
