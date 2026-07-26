# COMPILE_FAIL: Lib/collections/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_alloc_Counter':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:231:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  231 |         "D.keys() -> a set-like object providing a view on D's keys"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_alloc_OrderedDict':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:245:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  245 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_alloc_UserDict':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:259:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  259 |             link_prev.next = link_next
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_alloc__Link':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:273:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  273 |         if key in self:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_alloc__OrderedDictItemsView':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:287:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  287 |         state = self.__getstate__()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_alloc__OrderedDictKeysView':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:301:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  301 |                 state = state or None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_alloc__OrderedDictValuesView':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:315:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  315 |         return self
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_OrderedDictKeysView___reversed__':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:955:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  955 |         '''
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:953:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  953 |         Counter({'b': 2, 'a': 1})
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py: In function '_OrderedDictItemsView___reversed__':
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:83:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   83 |         for key in reversed(self._mapping):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:81:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   81 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:80:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   80 | class _OrderedDictValuesView(_collections_abc.ValuesView):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:79:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   79 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/collections/__init__.py:78:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
... (5553 more lines)
```

Exit code: 1
Elapsed: 9.84s
