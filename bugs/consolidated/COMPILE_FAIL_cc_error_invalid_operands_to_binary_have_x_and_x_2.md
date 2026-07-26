# COMPILE_FAIL: CC ERROR: invalid operands to binary * (have 'X' and 'X')

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:25:11: warning: unused variable '_tag' [-Wunused-variable]
   25 |     print('Success: no fatal errors found.')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:30:11: warning: unused variable '_tag' [-Wunused-variable]
   30 |     raise SystemExit(main())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:35:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:50:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:59:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:18:15: error: invalid operands to binary * (have 'char *' and 'int')
   18 |         s = 's' * (err_count != 1)
      |               ^
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:128:11: warning: variable 'lines' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:125:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:47:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:46:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:45:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py: At top level:
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:77:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:48:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:39:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:34:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:29:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
   29 | if __name__ == '__main__':
      |             ^~~~~~~~~~~~~~        
/Users/mrs/net/Python-3.14.6/Doc/tools/check-epub.py:24:16: warning: '_mojo_dispatch_getattr' defined but not used [-Wunused-function]
   24 | 
      |                ^                     
check-epub.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
check-epub.ci:457:19: warning: '_Bool_items' defined but not used [-Wunused-function]
  457 | static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }
      |                   ^~~~~~~~~~~
check-epub.ci:456:15: warning: '_ReflectTable_in_dll' defined but not used [-Wunused-function]
  456 | static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }
      |               ^~~~~~~~~~~~~~~~~~~~
In file included from check-epub.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:396:12: warning: '_mojo_vprintf'
```

## Affected files

- `Doc/tools/check-epub.py`
