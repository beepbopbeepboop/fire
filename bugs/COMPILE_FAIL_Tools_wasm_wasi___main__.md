# COMPILE_FAIL: Tools/wasm/wasi/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:80:11: warning: unused variable '_tag' [-Wunused-variable]
   80 |     environment = env_defaults | os.environ | updates
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:85:11: warning: unused variable '_tag' [-Wunused-variable]
   85 |             env_diff[key] = value
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
   90 |     log("🌎", f"Environment changes:{''.join(env_vars)}")
      |           ^~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:105:11: warning: unused variable '_tag' [-Wunused-variable]
  105 |             separator()
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:114:13: warning: unused variable '_tag' [-Wunused-variable]
  114 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function 'separator':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:410:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
  410 |     return builder
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:405:10: warning: unused variable '_t7' [-Wunused-variable]
  405 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:399:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  399 |         if LOCAL_SETUP.read_bytes() == LOCAL_SETUP_MARKER:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function 'mojo_log_132aaf':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:55:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   55 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py: In function 'updated_env_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:127:11: warning: variable 'item' set but not used [-Wunused-but-set-variable]
  127 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:126:11: warning: variable 'key' set but not used [-Wunused-but-set-variable]
  126 |     """Execute a command.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:120:7: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
  120 |         return wrapper
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:119:13: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
  119 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py:82:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
   82 |     env_diff = {}
... (591 more lines)
```

Exit code: 1
Elapsed: 11.28s
