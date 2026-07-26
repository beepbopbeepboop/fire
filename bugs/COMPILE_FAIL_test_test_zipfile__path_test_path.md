# COMPILE_FAIL: Lib/test/test_zipfile/_path/test_path.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py: In function '_alloc_DirtyZipInfo':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:108:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  108 |         assert c.is_file() and f.is_file()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py: In function 'build_alpharep_fixture':
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:101:11: warning: variable '_t70' set but not used [-Wunused-but-set-variable]
  101 |         root = zipfile.Path(alpharep)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:100:10: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
  100 |     def test_iterdir_and_types(self, alpharep):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:97:11: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
   97 |         return path
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:94:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
   94 |         path = tmpdir / alpharep.filename
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:93:10: warning: variable '_t62' set but not used [-Wunused-but-set-variable]
   93 |         alpharep.close()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:90:11: warning: variable '_t59' set but not used [-Wunused-but-set-variable]
   90 |     def zipfile_ondisk(self, alpharep):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:87:11: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
   87 |         self.fixtures = contextlib.ExitStack()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:86:10: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
   86 |     def setUp(self):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:83:11: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
   83 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:80:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
   80 | ]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:79:10: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
   79 |     Invoked.wrap(compose(zipfile._path.CompleteDirs.inject, build_alpharep_fixture)),
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:76:11: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
   76 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:73:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
   73 |     zf.filename = "alpharep.zip"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:72:10: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   72 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_zipfile/_path/test_path.py:69:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   69 |     zf.writestr("j/m.bar", b"content of m")
... (6297 more lines)
```

Exit code: 1
Elapsed: 13.65s
