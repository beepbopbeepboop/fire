# COMPILE_FAIL: Platforms/emscripten/wasm_assets.py

Source file: `/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |     "http/",
      |           ^~  
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |     "socketserver.py",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |     "urllib/robotparser.py",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |     "_ssl": ["ssl.py"],
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:97:13: warning: unused variable '_tag' [-Wunused-variable]
   97 |         builddir = f.read()
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function 'get_builddir_0c85c9':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:287:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:280:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function 'get_sysconfigdata_0c85c9':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:105:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  105 |     filename = data_name + ".py"
      |           ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:103:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  103 |     assert isinstance(args.builddir, pathlib.Path)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function '_alloc_create_stdlib_zip_filterfunc_env':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:114:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  114 |     def filterfunc(filename: str) -> bool:
      | ^   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py: In function 'create_stdlib_zip_filterfunc':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:140:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  140 |     with open(args.buildroot / "Makefile") as f:
      | ^   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:138:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  138 | 
      |       ^   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:137:9: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  137 |     modules = {}
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:136:7: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  136 | def detect_extension_modules(args: argparse.Namespace) -> dict[str, bool]:
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/wasm_assets.py:135:9: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  135 | 
... (135 more lines)
```

Exit code: 1
Elapsed: 13.47s
