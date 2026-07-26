# COMPILE_FAIL: Lib/test/test_turtle.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py: In function '_alloc_Multiplier':
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:214:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  214 |             with self.subTest(case=test_case):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:228:11: warning: unused variable '_tag' [-Wunused-variable]
  228 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:233:11: warning: unused variable '_tag' [-Wunused-variable]
  233 |         ]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:238:11: warning: unused variable '_tag' [-Wunused-variable]
  238 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:253:11: warning: unused variable '_tag' [-Wunused-variable]
  253 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:262:13: warning: unused variable '_tag' [-Wunused-variable]
  262 |         self.assertEqual(vec * M, Vec2D(f"{vec[0]}*M", f"{vec[1]}*M"))
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py: In function 'patch_screen_mock_iscolorstring':
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:75:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:75:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:75:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:75:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:75:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:75:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:525:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  525 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_turtle.py:523:7: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
  523 |             with open(file_path, "w") as f:
      |       ^   
... (5753 more lines)
```

Exit code: 1
Elapsed: 15.29s
