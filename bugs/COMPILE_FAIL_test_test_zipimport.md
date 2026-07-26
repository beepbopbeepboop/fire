# COMPILE_FAIL: Lib/test/test_zipimport.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:336:11: warning: unused variable '_tag' [-Wunused-variable]
  336 |         self.addCleanup(os_helper.unlink, TEMP_ZIP)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:341:11: warning: unused variable '_tag' [-Wunused-variable]
  341 |             z.writestr('a/b/c/d.py', test_src)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:346:11: warning: unused variable '_tag' [-Wunused-variable]
  346 |         self.addCleanup(os_helper.unlink, TEMP_ZIP)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:361:11: warning: unused variable '_tag' [-Wunused-variable]
  361 |     def _testPackage(self, initfile):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:370:13: warning: unused variable '_tag' [-Wunused-variable]
  370 |             self.assertEqual(zi.get_source('b'), test_src)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:650:32: warning: trigraph '??>' ignored, use '-trigraphs' to enable [-Wtrigraphs]
  650 |         self.assertEqual(sorted(zi._get_files()), sorted([*files, *extra_files]))
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function 'make_pyc_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:744:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  744 |         self.assertRaises(OSError, zi.get_data, os.path.join(TEMP_ZIP, 'a', 'b'))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:742:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  742 |         self.assertEqual(zi.get_data(os.path.join(TEMP_ZIP, 'a', 'b', '')), b'')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:735:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  735 |     def _testGetData(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:723:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  723 |             z.mkdir('a/b/c')
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function 'module_path_to_dotted_name_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:55:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   55 | TESTMOD2 = "ziptestmodule2"
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:53:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   53 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py: In function 'ImportHooksBaseTestCase_setUp':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:91:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   91 |         # cached directory info and linecache.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipimport.py:89:7: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   89 |     def setUp(self):
... (25343 more lines)
```

Exit code: 1
Elapsed: 13.99s
