# COMPILE_FAIL: Lib/test/test_type_annotations.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:177:11: warning: unused variable '_tag' [-Wunused-variable]
  177 |     return mod
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:182:11: warning: unused variable '_tag' [-Wunused-variable]
  182 |         code = textwrap.dedent(code)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:187:11: warning: unused variable '_tag' [-Wunused-variable]
  187 |                     ns = run_code(code)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:202:11: warning: unused variable '_tag' [-Wunused-variable]
  202 |         """)
      |           ^~  
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:211:13: warning: unused variable '_tag' [-Wunused-variable]
  211 |                 x: int = 1
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py: In function 'TypeAnnotationTests_test_lazy_create_annotations':
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:26:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   26 |         foo = type("Foo", (), {})
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:31:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   31 |             self.assertTrue("__annotations_cache__" in foo.__dict__)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:26:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   26 |         foo = type("Foo", (), {})
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:22:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   22 |             self.assertEqual(foo.__dict__['__annotations_cache__'], d)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:558:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  558 |         self.assertEqual(ns["res"].__annotations__, {"x": "closure var"})
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:556:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
  556 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:555:10: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
  555 |         res = f("closure var")
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:554:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
  554 |             return inner
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:553:10: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
  553 |             def inner(x: format): pass
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_type_annotations.py:552:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
... (5719 more lines)
```

Exit code: 1
Elapsed: 15.35s
