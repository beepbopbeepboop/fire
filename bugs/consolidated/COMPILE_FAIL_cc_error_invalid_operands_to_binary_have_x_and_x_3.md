# COMPILE_FAIL: CC ERROR: invalid operands to binary + (have 'X' and 'X')

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: warning: f-string interpolation '{'.join(cmd)}' could not be compiled; emitting it as literal text (SyntaxError: 1:1: Unexpected DOT('.'))
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: warning: f-string interpolation '{'.join(cmd)}' could not be compiled; emitting it as literal text (SyntaxError: 1:1: Unexpected DOT('.'))
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:65:11: warning: unused variable '_tag' [-Wunused-variable]
   65 |     and EXCLUSIVEADDRUSE on Windows:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:70:11: warning: unused variable '_tag' [-Wunused-variable]
   70 |     port returned to us by the OS won't immediately be dished back out to some
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:75:11: warning: unused variable '_tag' [-Wunused-variable]
   75 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:90:11: warning: unused variable '_tag' [-Wunused-variable]
   90 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:99:13: warning: unused variable '_tag' [-Wunused-variable]
   99 |                 raise support.TestFailed("tests should never set the "
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: In function 'find_unused_port_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:268:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  268 |         filter_error(err)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:262:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  262 |             # The error can also be wrapped as __cause__:
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:260:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  260 |             elif len(a) >= 2 and isinstance(a[1], OSError):
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py: In function 'bind_port_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:176:11: warning: variable '_t93' set but not used [-Wunused-but-set-variable]
  176 |     errors = [errno.ECONNREFUSED]
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:173:11: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
  173 |     Get the different socket error numbers ('errno') which can be received
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:168:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
  168 |         return test
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:166:11: warning: variable '_t83' set but not used [-Wunused-but-set-variable]
  166 |         return unittest.skip(msg)(test)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:162:11: warning: variable '_t79' set but not used [-Wunused-but-set-variable]
  162 |             finally:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/support/socket_helper.py:141:11: warning: variable '_t58' set but not used [-Wunused-but-set-variab
```

## Affected files

- `Lib/test/support/socket_helper.py`
