# COMPILE_FAIL: Lib/concurrent/interpreters/_queues.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py: In function '_alloc_Queue':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 |     unbound = _serialize_unbound(unbounditems)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py: In function '_serialize_unbound_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:280:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  280 |         try:
      |           ^~ 
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py: In function '_resolve_unbound_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:63:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   63 |     return resolved
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:62:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   62 |         resolved = UNBOUND
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py: In function 'create_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:83:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   83 | def list_all():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:77:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   77 |     qid = _queues.create(maxsize, unboundop, -1)
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:76:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   76 |     unboundop, = unbound
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:71:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   71 |     "unbounditems" sets the default for Queue.put(); see that method for
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:68:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   68 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py: In function 'list_all':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:89:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   89 |             self._set_unbound(unboundop)
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:85:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   85 |     queues = []
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py: In function 'Queue___new__':
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:116:1: warning: label 'bb_11' defined but not used [-Wunused-label]
  116 |     def __del__(self):
      | ^   ~
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:122:1: warning: label 'bb_10' defined but not used [-Wunused-label]
  122 |             del _known_queues[self._id]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:119:1: warning: label 'bb_8' defined but not used [-Wunused-label]
  119 |         except QueueNotFoundError:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/concurrent/interpreters/_queues.py:127:1: warning: label 'bb_6' defined but not used [-Wunused-label]
... (1283 more lines)
```

Exit code: 1
Elapsed: 9.97s
