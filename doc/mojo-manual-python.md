# Mojo Manual — Python Interoperability

Source: https://docs.modular.com/mojo/manual/python/
        https://docs.modular.com/mojo/manual/python/python-from-mojo/
        https://docs.modular.com/mojo/manual/python/mojo-from-python/
        https://docs.modular.com/mojo/manual/python/types/

---

## Overview

Mojo provides bidirectional Python interoperability:

- **Calling Python from Mojo**: import Python modules and call Python functions using CPython runtime
- **Calling Mojo from Python**: expose Mojo functions and types as Python extension modules

---

## Calling Python from Mojo

Source: https://docs.modular.com/mojo/manual/python/python-from-mojo/

Mojo uses the CPython runtime without modification for full compatibility with existing Python libraries.

### Specifying Python Version

Use Pixi for consistency across environments:
```
pixi add "python==3.11"
```

### Importing Python Modules

```mojo
from std.python import Python

def main() raises:
    np = Python.import_module("numpy")
    array = np.array(Python.list(1, 2, 3))
    print(array)  # [1 2 3]
```

- `import_module()` returns a `PythonObject` wrapper around the module
- Individual members cannot be imported directly; access through module reference
- Import statements must occur within functions, not at top level
- The method may raise exceptions

### Local Python Modules

```mojo
from std.python import Python

def main() raises:
    Python.add_to_path("path/to/module")  # or "." for current directory
    mypython = Python.import_module("mypython")
```

### Important Caution

`mojo build` does NOT include Python packages. They must be available in the environment where the program runs.

---

## Python Types in Mojo

Source: https://docs.modular.com/mojo/manual/python/types/

### Mojo Types → Python

When calling Python methods, Mojo automatically converts: integers, floats, booleans, and strings to corresponding Python types (`int`, `float`, `bool`, `str`).

### Python Types → Mojo: `PythonObject`

Mojo wraps Python objects in `PythonObject`, which exposes dunder methods for attribute access and method calls.

**Creating Python collections**:
```mojo
from std.python import Python

def main() raises:
    py_dict = Python.dict()
    py_dict["item_name"] = "whizbang"
    py_dict["price"] = 11.75

    py_list = Python.list("cat", 2, 3.14159, 4)
    n = py_list[2]
    py_list.append(5)

    py_tuple = Python.tuple("cat", 2, 3.1415, "cat")
    print("Number of cats:", py_tuple.count("cat"))

    var py_set = Python.evaluate('{2, 3, 2, 7, 11, 3}')
```

**Custom types via evaluation**:
```mojo
py_utils = Python.evaluate(my_python_code, file=True, name="py_utils")
py_utils.type_printer(4)
```

### Converting Python Values to Mojo

Most Mojo APIs don't accept `PythonObject` directly:

```mojo
var mojo_string = String(py=py_string)
var mojo_bool = Bool(py=py_bool)
var mojo_int = Int(py=py_int)
var mojo_float = Float64(py=py_float)
```

### Comparing Python Types

```mojo
py_float_type = Python.evaluate("float")
print("Is float:", Python.type(value1) is py_float_type)
```

---

## Calling Mojo from Python

Source: https://docs.modular.com/mojo/manual/python/mojo-from-python/

### Module Structure

Projects combine Python entry points with Mojo modules. The system uses Python's extension module mechanism with a `PyInit_<module_name>()` entry point.

### Import Mechanism

When Python imports a Mojo module, the `mojo.importer` hook automatically:
1. Detects `.mojo` files matching the import name
2. Compiles them using `mojo build --emit shared-lib`
3. Caches compiled artifacts in `__mojocache__/`
4. Rebuilds only when source files change

### Type Binding

Use `PythonModuleBuilder` to expose Mojo types to Python.

Required traits for Mojo types:
- `Writable` — always required
- `Movable` — required for custom initializers
- `Defaultable` + `Movable` — for default initializers

### Object Construction

**Custom initializer**:
```mojo
def_py_init()  # manual argument validation and conversion
```

**Default initializer** (zero-argument):
```mojo
def_init_defaultable()
```

### Value Conversion

Two mechanisms:
1. **Conversion**: creates new Mojo values from Python objects via `ConvertibleFromPython` trait
2. **Downcasting**: accesses inner Mojo values via `downcast_value_ptr[Type]()` or `unchecked_downcast_value_ptr[Type]()`

### Exposing Methods

Methods must be `@staticmethod` with either:
- `py_self: PythonObject` — full allocation access
- `self_ptr: UnsafePointer[Self]` — direct field access

Method registration functions:
- `def_function()` — standard fixed-arity (up to 6 arguments)
- `def_method()` — instance methods
- `def_staticmethod()` — static methods
- `def_py_function()` — lower-level, for variadic arguments

### Keyword Arguments

```mojo
# Requires OwnedKwargsDict[PythonObject] as final parameter
```

### Current Limitations

- Functions limited to 6 `PythonObject` arguments maximum
- Keyword-only arguments unsupported
- Native `**kwargs` syntax unavailable (use `OwnedKwargsDict`)
- Package dependencies require manual compilation
- Properties not supported
- Limited trait implementations in stdlib
