# COMPILE_FAIL: Doc/includes/mp_pool.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:33:11: warning: unused variable '_tag' [-Wunused-variable]
   33 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:38:11: warning: unused variable '_tag' [-Wunused-variable]
   38 | # Test code
      |           ^   
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:43:11: warning: unused variable '_tag' [-Wunused-variable]
   43 |     print('Creating pool with %d processes\n' % PROCESSES)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 |         for r in results:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:67:13: warning: unused variable '_tag' [-Wunused-variable]
   67 |         print('Unordered results using pool.imap_unordered():')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function 'calculate_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:12:14: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   12 |     return '%s says that %s%s = %s' % (
      |              ^
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function 'mul_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:29:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   29 |     return 1.0 / (x - 5.0)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:28:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   28 | def f(x):
      |           ^  
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function 'plus_1ce6ce':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:33:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   33 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:32:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   32 |     return x ** 3
      |           ^~~
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py: In function 'test':
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:43:13: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
   43 |     print('Creating pool with %d processes\n' % PROCESSES)
      |             ^
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:130:3: error: cannot convert to a pointer type
  130 |                 sys.stdout.write('\n\t%s' % res.get(0.02))
      |   ^    
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:130:17: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
  130 |                 sys.stdout.write('\n\t%s' % res.get(0.02))
      |                 ^
/Users/mrs/net/Python-3.14.6/Doc/includes/mp_pool.py:142:17: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
... (93 more lines)
```

Exit code: 1
Elapsed: 5.25s
