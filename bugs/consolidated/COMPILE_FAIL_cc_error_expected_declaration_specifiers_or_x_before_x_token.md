# COMPILE_FAIL: CC ERROR: expected declaration specifiers or 'X' before 'X' token

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:61:35: error: expected declaration specifiers or '...' before '*' token
   61 |         except AttributeError:
      |                                   ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:62:43: error: expected declaration specifiers or '...' before '*' token
   62 |             raise ValueError(f'{name}.__spec__ is not set') from None
      |                                           ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:63:1: warning: no semicolon at end of struct or union
   63 |         else:
      | ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:76:11: warning: unused variable '_tag' [-Wunused-variable]
   76 |     value of 'path' given to the finders. None is returned if no spec could
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:81:11: warning: unused variable '_tag' [-Wunused-variable]
   81 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:96:11: warning: unused variable '_tag' [-Wunused-variable]
   96 |                     f"while trying to find {fullname!r}", name=fullname) from e
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:105:13: warning: unused variable '_tag' [-Wunused-variable]
  105 |             spec = module.__spec__
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:183:4: error: '_lazymodule__dispatch_t' has no member named 'LazyModule___delattr__'
  183 |                 # exec_module() and self-referential imports are the primary ways this can
      |    ^            ~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:183:40: error: expected declaration specifiers or '...' before '*' token
  183 |                 # exec_module() and self-referential imports are the primary ways this can
      |                                        ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:183:29: warning: excess elements in struct initializer
  183 |                 # exec_module() and self-referential imports are the primary ways this can
      |                             ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:183:29: note: (near initialization for '_lazymodule__dispatch')
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:183:57: error: expected '}' before '_LazyModule___delattr__'
  183 |                 # exec_module() and self-referential imports are the primary ways this can
      |                                                         ^~~~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:182:62: note: to match this '{'
  182 |                 # triggering the load again.
      |                                                              ^
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: In function 'source_hash_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:239:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  239 |     def __check_eager_loader(loader):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py:235:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  235 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/util.py: I
```

## Affected files

- `Lib/importlib/util.py`
- `Lib/unittest/case.py`
