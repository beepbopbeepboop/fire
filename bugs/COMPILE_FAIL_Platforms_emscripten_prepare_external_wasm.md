# COMPILE_FAIL: Platforms/emscripten/prepare_external_wasm.py

Source file: `/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 |         function_name=function_name, hex_string=hex_string
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
   36 |     return 0
      |           ^~  
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |         description="Compile WebAssembly text files using wasm-as"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function 'prepare_wasm_132aaf':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:147:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:143:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:138:10: warning: variable 'hex_string' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:135:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:133:11: warning: variable 'wasm_bytes' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: At top level:
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:39:9: error: conflicting types for '_gimple_main'; have 'int64_t(void)' {aka 'long long int(void)'}
   39 | def main():
      |         ^~~         
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:11:9: note: previous declaration of '_gimple_main' with type 'int64_t()' {aka 'long long int()'}
   11 |     return new WebAssembly.Module(hexStringToUTF8Array("{hex_string}"));
      |         ^~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:61:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:58:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:55:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:52:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   52 | if __name__ == "__main__":
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:49:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   49 |     return prepare_wasm(args.input_file, args.output_file, args.function_name)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:46:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   46 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:76:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:75:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py: At top level:
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:83:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:54:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/prepare_external_wasm.py:45:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
... (28 more lines)
```

Exit code: 1
Elapsed: 13.39s
