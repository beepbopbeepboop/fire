# COMPILE_FAIL: Lib/importlib/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:63:35: error: expected declaration specifiers or '...' before '*' token
   63 |         else:
      |                                   ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:64:43: error: expected declaration specifiers or '...' before '*' token
   64 |             if spec is None:
      |                                           ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:65:1: warning: no semicolon at end of struct or union
   65 |                 raise ValueError(f'{name}.__spec__ is None')
      | ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |     so, then sys.modules[name].__spec__ is returned. If that happens to be
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:83:11: warning: unused variable '_tag' [-Wunused-variable]
   83 |     In other words, relative module names (with leading dots) work.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |             parent_path = None
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:107:13: warning: unused variable '_tag' [-Wunused-variable]
  107 |             raise ValueError(f'{name}.__spec__ is not set') from None
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:4: error: '_lazymodule__dispatch_t' has no member named 'LazyModule___delattr__'
  185 |                 if loader_state['is_loading']:
      |    ^            ~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:40: error: expected declaration specifiers or '...' before '*' token
  185 |                 if loader_state['is_loading']:
      |                                        ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:29: warning: excess elements in struct initializer
  185 |                 if loader_state['is_loading']:
      |                             ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:29: note: (near initialization for '_lazymodule__dispatch')
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:185:57: error: expected '}' before '_LazyModule___delattr__'
  185 |                 if loader_state['is_loading']:
      |                                                         ^                      
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:184:62: note: to match this '{'
  184 |                 # happen, but in any case we must return something to avoid deadlock.
      |                                                              ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function 'source_hash_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:241:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  241 |             raise TypeError('loader must define exec_module()')
... (793 more lines)
```

Exit code: 1
Elapsed: 10.31s
