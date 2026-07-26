# COMPILE_FAIL: Lib/importlib/metadata/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function '_alloc_EntryPoints':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:278:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  278 |         return EntryPoints(ep for ep in self if ep.matches(**params))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function '_alloc_FileHash':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:292:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  292 |         return {ep.group for ep in self}
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function '_alloc_Lookup':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:306:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  306 | class PackagePath(pathlib.PurePosixPath):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function '_alloc_PackagePath':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:320:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  320 |         """Return a path-like object for this path"""
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function '_alloc_PathDistribution':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:334:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  334 |     def __new__(cls, *args, **kwargs):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function '_alloc_Prepared':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:348:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  348 |             )
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function 'PackageNotFoundError___str__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:1005:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1005 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function 'PackageNotFoundError_name':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:67:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   67 |     Pair(name='sec1', value='# comments ignored')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:59:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   59 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py: In function 'Sectioned_section_pairs':
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:71:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   71 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:69:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   69 |     Pair(name='sec1', value='b = 2')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:68:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   68 |     Pair(name='sec1', value='a = 1')
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:67:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   67 |     Pair(name='sec1', value='# comments ignored')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/__init__.py:66:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (4348 more lines)
```

Exit code: 1
Elapsed: 10.67s
