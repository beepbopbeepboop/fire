# COMPILE_FAIL: Lib/unittest/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:58:11: warning: unused variable '_tag' [-Wunused-variable]
   58 |     """Finds elements in only one or the other of two, sorted input lists.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |     "expected" list.    Duplicate elements in either input list are ignored.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 |                 unexpected.append(a)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:87:13: warning: unused variable '_tag' [-Wunused-variable]
   87 |                 finally:
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function '_shorten_4e874b':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:193:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function '_common_shorten_repr':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:26:7: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
   26 |     maxlen = max(map(len, args))
      |       ^
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function 'safe_repr_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:56:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   56 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:52:10: warning: unused variable '_t6' [-Wunused-variable]
   52 |     return result[:_MAX_LENGTH] + ' [truncated]...'
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py: In function 'sorted_list_difference_3af0c6':
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:91:1: warning: label 'bb_24' defined but not used [-Wunused-label]
   91 |         except IndexError:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:125:7: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
  125 |     m, n = len(s), len(t)
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:121:7: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
  121 | def _count_diff_all_purpose(actual, expected):
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:102:10: warning: unused variable '_t37' [-Wunused-variable]
  102 |     As it does a linear search per item (remove) it
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/unittest/util.py:90:7: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
   90 |                         j += 1
      |       ^   
... (87 more lines)
```

Exit code: 1
Elapsed: 14.14s
