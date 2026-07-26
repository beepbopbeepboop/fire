# COMPILE_FAIL: Platforms/emscripten/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 |     """Validate that the emsdk cache contains the required emscripten version."""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 |     emsdk_env = emsdk_activate_path(emsdk_cache)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         )
      |           ^   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:107:11: warning: unused variable '_tag' [-Wunused-variable]
  107 |     """Returns os.environ updated by sourcing emsdk_env.sh"""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:116:13: warning: unused variable '_tag' [-Wunused-variable]
  116 |         text=True,
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function 'load_config_toml':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:483:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  483 |     if pydebug:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:479:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  479 |     python_version = lib_dir.removesuffix("-pydebug").rpartition("-")[-1]
      |          ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:478:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  478 |     pydebug = lib_dir.endswith("-pydebug")
      |          ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:477:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  477 |     lib_dir = os.fsdecode(lib_dirs[0])
      |          ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function 'get_build_paths_1ce6ce':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:58:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   58 |     if cross_build_dir is None:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py: In function 'validate_emsdk_version_0c85c9':
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:95:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   95 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:94:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
   94 |     print(f"✅ Emscripten version {required_version} found in {emsdk_cache}")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:80:10: warning: variable 'emsdk_env' set but not used [-Wunused-but-set-variable]
   80 | @functools.cache
      |          ^~~~~~~  
/Users/mrs/net/Python-3.14.6/Platforms/emscripten/__main__.py:71:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   71 |         "host_dir": host_triple_dir / "build" / "python",
... (788 more lines)
```

Exit code: 1
Elapsed: 13.18s
