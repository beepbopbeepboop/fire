# COMPILE_FAIL: CC ERROR: %s" % (e[N], error))

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |             self.tz = ''
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |         saved_locale = setlocale(LC_TIME)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 |             for i in range(25):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:96:13: warning: unused variable '_tag' [-Wunused-variable]
   96 |         now = self.now
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py: In function 'escapestr_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:67:10: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
   67 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:65:10: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
   65 |         elif now[3] > 0: self.clock12 = now[3]
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:54:10: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
   54 |         )
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:52:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   52 |                 -1,  # tm_isdst (let the system determine)
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:41:10: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   41 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:39:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
   39 |         if now[3] < 12: self.ampm='(AM|am)'
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:32:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   32 | class StrftimeTest(unittest.TestCase):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:30:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   30 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:29:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   29 |     return new_text
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:24:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   24 |     new_text = re.escape(text)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:22:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   22 |     syntax while allowing regex syntax used for comparison.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py: In function 'StrftimeTest__update_variables':
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:68:1: warning: label 'bb_18' defined but not used [-Wunused-label]
   68 |         self.now = now
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_strftime.py:77:1: warning: label 'bb_19' defined but not used [-Wunused-label]
   77 |         now =
```

## Affected files

- `Lib/test/test_strftime.py`
