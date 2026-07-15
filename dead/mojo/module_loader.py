"""Module loader stubs for stdlib imports.

Provides minimal implementations for loading and caching modules.
Full implementation would load actual .mojo files from stdlib.
"""

class ModuleLoader:
    """Stub module loader for stdlib imports."""

    def __init__(self):
        self.loaded_modules = {}
        self.exported_symbols = {}

    def resolve_module_path(self, module_name):
        """Stub: Convert module name to file path.

        For bootstrap, returns empty path as we don't load external modules yet.
        """
        return f"{module_name}.mojo"

    def load_module(self, module_name):
        """Stub: Load a module and return its AST.

        For bootstrap, returns empty module dict to allow code to run
        even when imports would fail.
        """
        if module_name not in self.loaded_modules:
            # Return minimal module structure
            self.loaded_modules[module_name] = {
                'module_name': module_name,
                'symbols': {},
                'ast': None,
            }
        return self.loaded_modules[module_name]

    def get_symbol_type(self, module_name, symbol_name):
        """Stub: Get the type/signature of a symbol in a module.

        For bootstrap, returns a minimal type placeholder.
        """
        return {
            'name': symbol_name,
            'type': 'unknown',
            'module': module_name,
        }


# Module-level functions for convenience
_loader = ModuleLoader()

def load_module(module_name):
    """Load a module by name."""
    return _loader.load_module(module_name)

def get_symbol_type(module_name, symbol_name):
    """Get a symbol's type from a module."""
    return _loader.get_symbol_type(module_name, symbol_name)
