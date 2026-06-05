"""Module loader for stdlib imports.

Resolves and loads .mojo module files from the official stdlib.
Parses imported modules and makes symbols available to the codegen.
"""
import os
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))

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

    # Strategy 2: Relative to this module (from mojo-reference/)
    # Pattern: mojo-reference/ -> ../modular/mojo/stdlib
    relative_path = os.path.join(HERE, '..', 'modular', 'mojo', 'stdlib')
    abs_path = os.path.abspath(relative_path)
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

        path = self.resolve_module_path(module_name)

        if not os.path.exists(path):
            # Gracefully degrade: return empty exports if module not found
            self.loaded_modules[module_name] = {}
            return {}

        try:
            with open(path, 'r') as f:
                content = f.read()

            exports = {}

            # Extract function definitions with full signatures
            for line in content.split('\n'):
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
                    name = name_part.split()[-1] if name_part else ''
                    params_str = sig[paren_start + 1:paren_end].strip()

                    if not name or name.startswith('_'):
                        continue

                    # Extract return type
                    return_type = 'int'  # default
                    if '->' in sig:
                        after_arrow = sig.split('->')[-1].split(':')[0].strip()
                        return_type = after_arrow if after_arrow else 'int'

                    # Extract parameters as list of (name, type) tuples
                    parameters = []
                    if params_str:
                        for param in params_str.split(','):
                            param = param.strip()
                            if ':' in param:
                                param_name, param_type = param.split(':', 1)
                                param_name = param_name.strip()
                                param_type = param_type.strip()
                                parameters.append((param_name, param_type))

                    # Build C signature from extracted info
                    c_return_type = self._mojo_type_to_c(return_type)
                    c_params = []
                    for pname, ptype in parameters:
                        c_type = self._mojo_type_to_c(ptype)
                        c_params.append(f"{c_type} {pname}")

                    c_param_str = ', '.join(c_params) if c_params else 'void'
                    c_signature = f"{c_return_type} {name} ({c_param_str})"

                    exports[name] = {
                        'return_type': return_type,
                        'parameters': parameters,
                        'c_return_type': c_return_type,
                        'c_parameters': c_params,
                        'signature': c_signature,
                    }

            self.loaded_modules[module_name] = exports
            return exports

        except Exception:
            # Gracefully handle parse errors
            return {}

    @staticmethod
    def _mojo_type_to_c(mojo_type: str) -> str:
        """Convert Mojo type annotation to C type.

        Examples:
            'Int' → 'int'
            'Int64' → 'int64_t'
            'Float64' → 'double'
            'Bool' → '_Bool'
        """
        mojo_type = mojo_type.strip()

        # Mapping of Mojo types to C types
        type_map = {
            'Int': 'int',
            'Int8': 'int8_t',
            'Int16': 'int16_t',
            'Int32': 'int32_t',
            'Int64': 'int64_t',
            'UInt': 'unsigned int',
            'UInt8': 'uint8_t',
            'UInt16': 'uint16_t',
            'UInt32': 'uint32_t',
            'UInt64': 'uint64_t',
            'Float': 'float',
            'Float32': 'float',
            'Float64': 'double',
            'Bool': '_Bool',
            'String': 'char *',
        }

        # Check for direct mapping
        if mojo_type in type_map:
            return type_map[mojo_type]

        # Handle pointers and generic types
        if mojo_type.endswith('*'):
            base_type = mojo_type[:-1].strip()
            c_base = type_map.get(base_type, base_type)
            return f"{c_base} *"

        # Handle generic types like MojoList, UnsafePointer[T]
        if mojo_type.startswith('MojoList'):
            return 'MojoList *'
        if mojo_type.startswith('MojoDict'):
            return 'MojoDict *'
        if mojo_type.startswith('MojoSet'):
            return 'MojoSet *'
        if mojo_type.startswith('UnsafePointer'):
            return 'int64_t *'  # Pointer to 64-bit value

        # Default: unknown type as int
        return 'int'

    def get_symbol_type(self, module_name: str, symbol_name: str) -> str:
        """Get the type of an imported symbol."""
        exports = self.load_module(module_name)
        return exports.get(symbol_name, 'unknown')


def read_reflection(dylib_path: str) -> dict:
    """Read a dylib's `__mojo_reflect` table (reflect.h) — the compiler's import
    path consuming the *same* C-ABI reflection interface any other language uses.
    Returns {name: {'signature': str, 'kind': int, 'addr': int}}.

    This is the structured, ABI-accurate replacement for the line-regex
    signature extraction above: when a prebuilt dylib exists, its self-describing
    table is authoritative.
    """
    import ctypes

    class _Sym(ctypes.Structure):
        _fields_ = [('name', ctypes.c_char_p), ('signature', ctypes.c_char_p),
                    ('addr', ctypes.c_void_p), ('kind', ctypes.c_int32)]

    class _Table(ctypes.Structure):
        _fields_ = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
                    ('n_syms', ctypes.c_uint32), ('reserved', ctypes.c_uint32),
                    ('syms', ctypes.POINTER(_Sym))]

    lib = ctypes.CDLL(dylib_path)
    tbl = _Table.in_dll(lib, '__mojo_reflect')
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
