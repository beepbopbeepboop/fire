# Bootstrap Next Steps

## Current Status
- ✅ mojo/simple_compiler.mojo created (bootstrap entry point)
- ✅ Parser enhanced (let keyword, slice support)
- ✅ Transpiler partially fixed (? → AnyType, comment placement)
- 🔄 Agent: Fixing gimple_codegen.mojo parse errors (struct methods, decorators)

## When gimple_codegen.mojo Parses Successfully

### 1. Update simple_compiler.mojo
```mojo
# Replace:
from mojo_compiler import tokenize, Parser, compile as mojo_compile

# With:
from mojo_compiler import tokenize, Parser, compile as mojo_compile
from gimple_codegen import GimpleGen

# Then update mojo_gimple to use GimpleGen instead of Python IR
fn mojo_gimple(src: String) -> String:
    let tokens = tokenize(src)
    let stmts = Parser(tokens).parse_module()
    return GimpleGen().gen_module(stmts)
```

### 2. Run make bootstrap
```bash
make clean-bootstrap
make bootstrap
```

This will:
- Transpile gimple_codegen.py → mojo/gimple_codegen.mojo (now with valid syntax)
- Compile stage1 using Python build/mojo
  - Dumps GIMPLE from mojo/simple_compiler.mojo
  - Links with compiler_main.c + mojo_runtime.c
- Compile stage2 using stage1/mojo
  - Self-compiles the Mojo compiler
- Verify by comparing --dump-all output between stage1 and stage2

### 3. Expected Blockers After gimple_codegen.mojo Parses

#### Link Time
- `mojo_compile`, `tokenize`, Parser not available as C symbols
- Solution: Either (a) provide from Python via C API, or (b) refactor imports

#### Runtime Issues
- GimpleGen may depend on Python structures not available in Mojo
- Need to verify all external dependencies are Mojofied

#### Verification Failures
- stage1 and stage2 may produce different dumps
- Indicates: compilation bugs, determinism issues, or missing features

## Branch Points

### If gimple_compile.mojo still has errors after compiler fixes
- Consider alternative: implement gimple_codegen natively in Mojo (high effort)
- Or: accept Python IR for now, defer full GIMPLE to future

### If link errors prevent stage1 from compiling
- Refactor simple_compiler.mojo to not import unresolved functions
- Provide compiler functions from C harness using Python C API

### If stage1 and stage2 dumps differ
- Debug which part of the compiler has non-determinism
- Check compilation of that module
- May need iterative fixes to compiler/generated code

## Success Criteria

✅ Bootstrap complete when:
1. stage1/mojo compiles successfully
2. stage2/mojo compiles successfully  
3. stage1 and stage2 produce identical --dump-all output
4. stage2/mojo can self-compile itself (mojo build mojo/simple_compiler.mojo)
