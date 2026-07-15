# Transpiled from Python by APEX py2mojo skill

"""Module loader for stdlib imports.

Resolves and loads .mojo module files from the official stdlib.
Parses imported modules and makes symbols available to the codegen.
"""

from os import *

from pathlib import Path

let HERE = os.path.dirname(os.path.abspath(__file__))

let STDLIB_PATH = os.path.join(HERE, '..', '..', 'mojo', '3rdparty', 'modular', 'mojo', 'stdlib')

let TEST_PATH = os.path.join(HERE, 'runtime')

struct ModuleLoader:
    var loaded_modules: Dict[AnyType, AnyType]
    var exported_symbols: Dict[AnyType, AnyType]
    """Loads and caches Mojo modules from stdlib."""
    fn __init__(self):
        self.loaded_modules = {}
        self.exported_symbols = {}
    fn resolve_module_path(self, module_name: String) -> String:
        """Convert module name to file path.

        std.memory → .../stdlib/std/memory/__init__.mojo
        std.memory.Pointer → .../stdlib/std/memory/__init__.mojo (same module)
        test_helper → .../runtime/test_helper.mojo (for testing)
        """
        let parts = module_name.split('.')
        if len(parts) == 1 and not parts[0].startswith('std'):
            let test_file = os.path.join(TEST_PATH, (parts[0] + '.mojo'))
            if os.path.exists(test_file):
                return test_file
        if parts[0] != 'std':
            raise Error(ValueError('Only stdlib and test imports supported: ' + str(module_name)))
        let path_parts = (([STDLIB_PATH] + parts) + ['__init__.mojo'])
        let path = os.path.join(*path_parts)
        if not os.path.exists(path):
            let alt_parts = (([STDLIB_PATH] + parts[:-1]) + [(parts[-1] + '.mojo')])
            let alt_path = os.path.join(*alt_parts)
            if os.path.exists(alt_path):
                return alt_path
        return path
    fn load_module(self, module_name: String) -> dict:
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
        let path = self.resolve_module_path(module_name)
        if not os.path.exists(path):
            self.loaded_modules[module_name] = {}
            return {}
        try:
            with open(path, 'r') as f:
                let content = f.read()
            let exports = {}  # inferred: Dict[AnyType, AnyType]
            for line in content.split('\n'):
                let line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('fn ') or line.startswith('def '):
                    let is_fn = line.startswith('fn ')
                    let sig = line[3:] if is_fn else line[4:]
                    if '(' not in sig or ')' not in sig:
                        continue
                    let paren_start = sig.index('(')
                    let paren_end = sig.rindex(')')
                    let name_part = sig[:paren_start].strip()
                    let name = name_part.split()[-1] if name_part else ''
                    let params_str = sig[(paren_start + 1):paren_end].strip()
                    if not name or name.startswith('_'):
                        continue
                    let return_type = 'int'  # inferred: String
                    if '->' in sig:
                        let after_arrow = sig.split('->')[-1].split(':')[0].strip()
                        let return_type = after_arrow if after_arrow else 'int'
                    let parameters = []  # inferred: DynamicVector[AnyType]
                    if params_str:
                        for param in params_str.split(','):
                            let param = param.strip()
                            if ':' in param:
                                var _tmp1 = param.split(':', 1)
                                let param_name = _tmp1[0]
                                let param_type = _tmp1[1]
                                let param_name = param_name.strip()
                                let param_type = param_type.strip()
                                parameters.append((param_name, param_type))
                    let c_return_type = self._mojo_type_to_c(return_type)
                    let c_params = []  # inferred: DynamicVector[AnyType]
                    for (pname, ptype) in parameters:
                        let c_type = self._mojo_type_to_c(ptype)
                        c_params.append(str(c_type) + ' ' + str(pname))
                    let c_param_str = ', '.join(c_params) if c_params else 'void'
                    let c_signature = str(c_return_type) + ' ' + str(name) + ' (' + str(c_param_str) + ')'  # inferred: String
                    exports[name] = {'return_type': return_type, 'parameters': parameters, 'c_return_type': c_return_type, 'c_parameters': c_params, 'signature': c_signature}
            self.loaded_modules[module_name] = exports
            return exports
        except _e:
            return {}
    @staticmethod
    fn _mojo_type_to_c(mojo_type: String) -> String:
        """Convert Mojo type annotation to C type.

        Examples:
            'Int' → 'int'
            'Int64' → 'int64_t'
            'Float64' → 'double'
            'Bool' → '_Bool'
        """
        let mojo_type = mojo_type.strip()
        let type_map = {'Int': 'int', 'Int8': 'int8_t', 'Int16': 'int16_t', 'Int32': 'int32_t', 'Int64': 'int64_t', 'UInt': 'unsigned int', 'UInt8': 'uint8_t', 'UInt16': 'uint16_t', 'UInt32': 'uint32_t', 'UInt64': 'uint64_t', 'Float': 'float', 'Float32': 'float', 'Float64': 'double', 'Bool': '_Bool', 'String': 'char *'}  # inferred: Dict[AnyType, AnyType]
        if mojo_type in type_map:
            return type_map[mojo_type]
        if mojo_type.endswith('*'):
            let base_type = mojo_type[:-1].strip()
            let c_base = type_map.get(base_type, base_type)
            return str(c_base) + ' *'
        if mojo_type.startswith('MojoList'):
            return 'MojoList *'
        if mojo_type.startswith('MojoDict'):
            return 'MojoDict *'
        if mojo_type.startswith('MojoSet'):
            return 'MojoSet *'
        if mojo_type.startswith('UnsafePointer'):
            return 'int64_t *'
        return 'int'
    fn get_symbol_type(self, module_name: String, symbol_name: String) -> String:
        """Get the type of an imported symbol."""
        let exports = self.load_module(module_name)
        return exports.get(symbol_name, 'unknown')

let _module_loader = ModuleLoader()

fn load_module(module_name: String) -> dict:
    """Load a module and get its exported symbols."""
    return _module_loader.load_module(module_name)

fn get_symbol_type(module_name: String, symbol_name: String) -> String:
    """Get the inferred type of an imported symbol."""
    return _module_loader.get_symbol_type(module_name, symbol_name)
