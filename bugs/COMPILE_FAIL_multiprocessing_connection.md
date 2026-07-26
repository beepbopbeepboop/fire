# COMPILE_FAIL: Lib/multiprocessing/connection.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:103:9: error: conflicting types for 'wait'; have 'int64_t()' {aka 'long long int()'}
  103 |     '''
      |         ^   
In file included from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/_stdlib.h:70,
                 from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/stdlib.h:58,
                 from connection.ci:5:
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/sys/wait.h:246:9: note: previous declaration of 'wait' with type 'pid_t(int *)' {aka 'int(int *)'}
  246 | pid_t   wait(int *) __DARWIN_ALIAS_C(wait);
      |         ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py: In function '_alloc_Connection':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:184:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  184 |                 self._close()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py: In function '_alloc_ConnectionWrapper':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:198:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  198 |             m = m.cast('B')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py: In function '_alloc_SocketListener':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:212:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  212 |     def send(self, obj):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py: In function 'arbitrary_address_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:85:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
   85 |         return (r'\\.\pipe\pyc-%d-%d-%s' %
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:115:11: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
  115 |         raise ValueError('address type of %r unrecognized' % address)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:93:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
   93 |     '''
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:71:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   71 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py: In function '_validate_family_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:101:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  101 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py: In function 'address_type_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:205:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
  205 |             size = n - offset
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:194:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  194 |         self._check_closed()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py:178:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  178 |         return self._handle
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/multiprocessing/connection.py: In function '_ConnectionBase___init__':
... (3515 more lines)
```

Exit code: 1
Elapsed: 10.12s
