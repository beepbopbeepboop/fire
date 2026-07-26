# COMPILE_FAIL: Lib/test/test_zipimport_support.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:86:11: warning: unused variable '_tag' [-Wunused-variable]
   86 |             zip_name, run_name = make_zip_script(d, 'test_zip',
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:91:11: warning: unused variable '_tag' [-Wunused-variable]
   91 |             try:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:96:11: warning: unused variable '_tag' [-Wunused-variable]
   96 |     def test_doctest_issue4197(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:111:11: warning: unused variable '_tag' [-Wunused-variable]
  111 |         sample_sources = {}
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:120:13: warning: unused variable '_tag' [-Wunused-variable]
  120 |             sample_sources[mod_name] = src
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py: In function '_run_object_doctest_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:299:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:288:10: warning: variable 'name' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:276:10: warning: unused variable '_t10' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py: In function 'ZipSupportTests_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:102:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  102 |         test_src = inspect.getsource(test_doctest)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:100:7: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
  100 |         # location, and then throwing it in a zip file to make sure
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:99:14: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
   99 |         # test_doctest itself, rewriting it a bit to cope with a new
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:98:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   98 |         # unit tests in sync, this test works by taking the source of
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:97:10: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
   97 |         # To avoid having to keep two copies of the doctest module's
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:96:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   96 |     def test_doctest_issue4197(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:95:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   95 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport_support.py:94:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   94 |                 del sys.modules["zip_pkg"]
      |           ^   
... (1368 more lines)
```

Exit code: 1
Elapsed: 13.21s
