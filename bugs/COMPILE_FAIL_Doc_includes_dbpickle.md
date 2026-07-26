# COMPILE_FAIL: Doc/includes/dbpickle.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py: In function '_alloc_DBPickler':
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:49:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   49 | def main():
      | ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py: In function '_alloc_DBUnpickler':
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:63:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   63 |         cursor.execute("INSERT INTO memos VALUES(NULL, ?)", (task,))
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py: In function 'DBPickler_persistent_id':
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:221:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py: In function 'DBUnpickler___init__':
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:36:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   36 |         type_tag, key_id = pid
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:34:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   34 |         # Here, pid is the tuple returned by DBPickler.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:33:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   33 |         # This method is invoked whenever a persistent ID is encountered.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:32:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   32 |     def persistent_load(self, pid):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:31:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   31 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py: In function 'DBUnpickler_persistent_load':
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:48:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   48 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:44:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   44 |             # Otherwise, the unpickler will think None is the object referenced
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:52:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   52 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 |     # Update a record, just for good measure.
      | ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:73:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
   73 |     pprint.pprint(memos)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:72:11: warning: variable 'task' set but not used [-Wunused-but-set-variable]
   72 |     print("Pickled records:")
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:71:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
   71 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py:70:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
... (169 more lines)
```

Exit code: 1
Elapsed: 5.29s
