# COMPILE_FAIL: Lib/test/test_tstring.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{=x}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected ASSIGN('='))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{=x}' could not be compiled; emitting it as literal text (SyntaxError: 1:0: Unexpected ASSIGN('='))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |         t = t"Name: {person.upper()}"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 |             t, ("Name: ", ", Age: ", ""),
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         # Test !s conversion (str)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:101:13: warning: unused variable '_tag' [-Wunused-variable]
  101 |         self.assertEqual(fstring(t), f"Data: {repr(obj)}")
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py: In function 'TestTString_test_string_representation':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:294:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:292:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:291:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  291 |     unittest.main()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:290:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  290 | if __name__ == '__main__':
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:289:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  289 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:288:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  288 |         self.assertEqual(fstring(t), "\n        Hello,\n        Python\n        ")
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tstring.py:287:10: warning: variable 'name' set but not used [-Wunused-but-set-variable]
  287 |         )
... (2201 more lines)
```

Exit code: 1
Elapsed: 15.27s
