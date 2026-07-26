# COMPILE_FAIL: Lib/importlib/abc.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py: In function '_register':
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:148:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
  148 |         set to.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:147:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
  147 |         """Abstract method which should return the value that __file__ is to be
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:128:10: warning: unused variable '_t18' [-Wunused-variable]
  128 |         return compile(data, path, 'exec', dont_inherit=True)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:118:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  118 |         Raises ImportError if the module cannot be found.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:117:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  117 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py: In function 'abc_MetaPathFinder_invalidate_caches':
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:52:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   52 | class PathEntryFinder(metaclass=abc.ABCMeta):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:50:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   50 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py: In function 'abc_PathEntryFinder_invalidate_caches':
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:51:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   51 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:49:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   49 |           machinery.PathFinder, machinery.WindowsRegistryFinder)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py: In function 'abc_ResourceLoader_get_data':
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:64:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   64 | class ResourceLoader(Loader):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:62:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   62 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py: In function 'abc_InspectLoader_is_package':
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:87:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   87 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:85:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   85 |     """Abstract base class for loaders which support inspection about the
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py: In function 'abc_InspectLoader_get_code':
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:113:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  113 |     @abc.abstractmethod
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py:114:1: warning: label 'bb_3' defined but not used [-Wunused-label]
... (1213 more lines)
```

Exit code: 1
Elapsed: 10.23s
