# Mojo Standard Library Build System

## Overview

The Mojo standard library contains **130 compilable modules** from the official Modular stdlib at `../mojo/3rdparty/modular/mojo/stdlib/std/`.

Each module can be compiled individually to GIMPLE code and linked into shared libraries or executables.

## Quick Start

### List all available stdlib modules

```bash
make stdlib
```

This generates:
- `build/stdlib/stdlib_modules.json` - Registry of all modules with metadata
- `build/stdlib/stdlib_index.h` - C header file for module management
- `build/stdlib/stdlib_index.c` - Module initialization code

### Compile a single stdlib module

```bash
python3 build_module.py path/to/module.mojo -o build/module.so --symbols build/module.json
```

Example - build the `bool` type:
```bash
python3 build_module.py ../mojo/3rdparty/modular/mojo/stdlib/std/builtin/bool.mojo \
  -o build/bool.so \
  --symbols build/bool.json
```

## Available Modules by Category

### Builtin Types (25 modules)
- `builtin/bool.mojo` - Boolean type and operations
- `builtin/range.mojo` - Range iterator
- `builtin/error.mojo` - Exception handling
- `builtin/int_literal.mojo` - Integer literals
- `builtin/string_literal.mojo` - String literals
- `builtin/none.mojo` - None/null type
- `builtin/len.mojo` - len() function
- And 18 others...

### Collections (9 modules)
- `collections/bitset.mojo` - Bit set data structure
- `collections/counter.mojo` - Element counter
- `collections/set.mojo` - Hash set
- `collections/string/__init__.mojo` - String type and operations
- And 5 others...

### Memory Management (8 modules)
- `memory/pointer.mojo` - Unsafe pointers
- `memory/arc.mojo` - Atomic reference counting
- `memory/unsafe.mojo` - Unsafe operations
- And 5 others...

### GPU Support (23 modules)
- `gpu/host/_nvidia_cuda.mojo` - NVIDIA CUDA integration
- `gpu/host/_metal.mojo` - Apple Metal GPU
- `gpu/host/_amdgpu_hip.mojo` - AMD GPU HIP
- `gpu/compute/tensor_ops.mojo` - Tensor operations
- And 19 others...

### OS/System (23 modules)
- `os/env.mojo` - Environment variables
- `os/path/__init__.mojo` - Path operations
- `os/process.mojo` - Process management
- `sys/arg.mojo` - Command-line arguments
- And 19 others...

### Math & Utilities (15 modules)
- `math/constants.mojo` - Mathematical constants
- `math/fast.mojo` - Fast math functions
- `utils/lock.mojo` - Synchronization primitives
- `bit/bit.mojo` - Bit manipulation
- And 11 others...

### Additional Modules (17 modules)
- `io/__init__.mojo` - Input/output
- `python/__init__.mojo` - Python integration
- `format/__init__.mojo` - String formatting
- `testing/__init__.mojo` - Testing utilities
- `logger/__init__.mojo` - Logging
- And 12 others...

## Building Strategies

### Strategy 1: Build Individual Modules (Recommended)

Build only the modules you need as shared libraries:

```bash
# Build memory management modules
python3 build_module.py ../mojo/3rdparty/modular/mojo/stdlib/std/memory/pointer.mojo -o build/stdlib_memory_pointer.so

# Build collections
python3 build_module.py ../mojo/3rdparty/modular/mojo/stdlib/std/collections/set.mojo -o build/stdlib_collections_set.so
```

Then link your application with these .so files:
```bash
gcc -o myapp myapp.o build/stdlib_*.so
```

### Strategy 2: Create a Custom Stdlib Bundle

Create a wrapper module that imports your needed stdlib modules:

```mojo
# mystdlib.mojo
from std.memory import pointer, arc
from std.collections import set
from std.os import env

# Your custom additions
def custom_init():
    print("Custom stdlib initialized")
```

Then compile it:
```bash
python3 mojo.py --dump mystdlib.mojo
gcc-mp-15 -fgimple -dynamiclib -I runtime -o libmystdlib.dylib mystdlib.ci runtime/mojo_runtime.c
```

### Strategy 3: Incremental Module Loading

Use the stdlib registry to load modules on-demand:

```python
import json

# Load registry
with open('build/stdlib/stdlib_modules.json') as f:
    stdlib = json.load(f)

# Find a module
for module_name, info in stdlib['modules']['collections'].items():
    if info['exists']:
        print(f"Can build: {module_name}")
```

## Module Compilation Pipeline

For each module:

1. **Parse** - mojo.py tokenizes and parses .mojo source
2. **Codegen** - gimple_codegen.py generates GIMPLE C code
3. **Compile** - gcc-mp-15 with -fgimple flag compiles to machine code
4. **Link** - Link with runtime/mojo_runtime.c for symbol support

## Symbol Extraction

Each compiled module produces a symbol table:

```bash
# Extract symbols automatically
python3 build_module.py builtin/bool.mojo -o build/bool.so --symbols build/bool.json

# Or use nm to inspect
nm -g build/bool.so | grep "T " | head -10
```

## Troubleshooting

### Module compilation fails

Check if the module is in the compilable list:
```bash
grep "module_name" build/stdlib/stdlib_modules.json
```

If not found, the module may use advanced Mojo syntax not yet supported by gimple_codegen.

### Symbol conflicts when linking multiple modules

Use separate .so files in different namespaces:
```bash
# Use full path in symbol names
python3 build_module.py path/to/module.mojo -o build/category_name.so
```

### Runtime errors loading stdlib

Ensure `runtime/mojo_runtime.c` has all required symbols:
```bash
nm -g build/libmojo.dylib | grep mojo_
```

## Integration with Applications

To use stdlib modules in your Mojo application:

### From Mojo code
```mojo
from std.memory import pointer
from std.collections import set

fn main():
    var ptr = pointer[Int64](0)
    var s = set[Int64]()
```

### From C code
```c
#include "runtime/mojo_runtime.h"
#include "build/stdlib/stdlib_index.h"

int main() {
    mojo_stdlib_init();
    // Use stdlib functions
    return 0;
}
```

## Performance Notes

- Individual .so files: Slower startup (dynamic loading), better isolation
- Combined dylib: Faster startup, larger binary size, potential symbol conflicts
- Current recommendation: Build only needed modules as individual .so files

## Build Statistics

Generated by `make stdlib`:
- **Total modules**: 130
- **Compilable percentage**: 100% of listed modules
- **Combined size** (if merged): ~1.2 MB GIMPLE + runtime
- **Average module size**: ~12 KB

See `build/stdlib/stdlib_modules.json` for detailed module information.

## Next Steps

1. Use `make stdlib` to generate the registry
2. Choose modules based on your needs
3. Compile with `python3 build_module.py` or `build_module_batch.py` (coming soon)
4. Link into your application
