# COMPILE_FAIL: Platforms/emscripten/web_example/server.py

Source file: `/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 |     if not args.bind:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 |         protocol="HTTP/1.1",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:44:11: warning: unused variable '_tag' [-Wunused-variable]
   44 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:59:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:68:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function 'MyHTTPRequestHandler_end_headers':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:135:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:133:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:132:7: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function 'MyHTTPRequestHandler_send_my_headers':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:37:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   37 |     server.test(  # type: ignore[attr-defined]
      | ^   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:35:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   35 |         args.bind = None
      |           ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:34:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   34 |     if not args.bind:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:33:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   33 |     args = parser.parse_args()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:32:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   32 | def main() -> None:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:31:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   31 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:30:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   30 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:47:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function 'main':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py:46:8: error: variable or field 'result' declared void
   46 |     main()
      |        ^~~   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/web_example/server.py: In function '_toplevel':
... (31 more lines)
```

Exit code: 1
Elapsed: 13.44s
