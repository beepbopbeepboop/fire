# COMPILE_FAIL: Doc/includes/mp_workers.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:37:11: warning: unused variable '_tag' [-Wunused-variable]
   37 | #
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:42:11: warning: unused variable '_tag' [-Wunused-variable]
   42 |     TASKS1 = [(mul, (i, 7)) for i in range(20)]
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     done_queue = Queue()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |     # Add more tasks using `put()`
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:71:13: warning: unused variable '_tag' [-Wunused-variable]
   71 |     for i in range(NUMBER_OF_PROCESSES):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function 'worker_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:159:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function 'calculate_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:21:14: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   21 |     return '%s says that %s%s = %s' % \
      |              ^
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function 'mul_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:32:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   32 | def plus(a, b):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:31:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   31 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function 'plus_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:41:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   41 |     NUMBER_OF_PROCESSES = 4
      |           ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:40:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   40 | def test():
      |           ^  
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py: In function 'test':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:156:11: warning: variable '_t111' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:153:11: warning: variable '_t108' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:141:14: warning: variable '_t96' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:130:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:126:11: warning: variable '_t81' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:110:14: warning: variable '_t65' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:98:11: warning: variable '_t53' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_workers.py:92:11: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
... (36 more lines)
```

Exit code: 1
Elapsed: 5.23s
