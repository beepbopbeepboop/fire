# COMPILE_FAIL: Lib/test/test_tracemalloc.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:257:11: warning: unused variable '_tag' [-Wunused-variable]
  257 |         self.assertEqual(tracemalloc.get_traced_memory(), (0, 0))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:262:11: warning: unused variable '_tag' [-Wunused-variable]
  262 |         self.assertGreaterEqual(size, obj_size)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:267:11: warning: unused variable '_tag' [-Wunused-variable]
  267 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:282:11: warning: unused variable '_tag' [-Wunused-variable]
  282 |         # Example: allocate a large piece of memory, temporarily
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:291:13: warning: unused variable '_tag' [-Wunused-variable]
  291 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py: In function 'get_frames_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:31:9: error: lvalue required as left operand of assignment
   31 |     for index in range(nframe):
      |         ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:36:15: warning: comparison between pointer and integer
   36 |         frame = frame.f_back
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:50:8: error: assignment to 'int64_t' {aka 'long long int'} from 'char * (*)(const char *, int)' makes integer from pointer without a cast [-Wint-conversion]
   50 | 
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:51:9: error: lvalue required as left operand of assignment
   51 |     # _tracemalloc._get_traces() returns a list of (domain, size,
      |         ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:593:7: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  593 |             tracemalloc.StatisticDiff(tb4, 0, -7, 0, -1),
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:574:11: warning: unused variable '_var_index' [-Wunused-variable]
  574 |             tracemalloc.Statistic(tb4, 7, 1),
      |           ^ ~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:571:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  571 |         self.assertEqual(stats1, [
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py: In function 'allocate_bytes_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:63:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
   63 |         (3, 7, (('<unknown>', 0),), 1),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_tracemalloc.py:58:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   58 | 
      |           ^   
... (10881 more lines)
```

Exit code: 1
Elapsed: 15.70s
