# COMPILE_FAIL: Lib/importlib/resources/readers.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function '_alloc_MultiplexedPath':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:73:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   73 |         self._paths = list(map(_ensure_traversable, remove_duplicates(paths)))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'remove_duplicates_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:260:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader___init__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:34:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   34 |     def files(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:32:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   32 |         return str(self.path.joinpath(resource))
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:31:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   31 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:30:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   30 |         copy.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:29:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   29 |         `resources.path()` from creating a temporary
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:28:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   28 |         Return the file system path to prevent
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:27:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   27 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:26:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   26 |     def resource_path(self, resource):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:25:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   25 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:24:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   24 |         self.path = pathlib.Path(loader.path).parent
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader_resource_path':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 | class ZipReader(abc.TraversableResources):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:31:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   31 |         """
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:29:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   29 |         `resources.path()` from creating a temporary
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader_files':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:39:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (1120 more lines)
```

Exit code: 1
Elapsed: 10.35s
