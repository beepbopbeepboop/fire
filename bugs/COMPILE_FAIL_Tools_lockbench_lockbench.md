# COMPILE_FAIL: Tools/lockbench/lockbench.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 | def jains_fairness(values):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
   36 | def main():
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |             acquisitions, thread_iters = benchmark_locks(
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: In function 'jains_fairness_fa7153':
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:34:19: error: passing argument 1 of 'mojo_sum' makes pointer from integer without a cast [-Wint-conversion]
   34 |     return (sum(values) ** 2) / (len(values) * sum(x ** 2 for x in values))
      |                   ^~~~~~
      |                   |
      |                   int
In file included from lockbench.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:346:24: note: expected 'void *' but argument is of type 'int'
  346 | int64_t mojo_sum(void *args);
      |                  ~~~~~~^~~~
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:68:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:64:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:65:1: warning: control reaches end of non-void function [-Wreturn-type]
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py: At top level:
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:83:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:54:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:45:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
   45 |             fairness = jains_fairness(thread_iters)
      |            ^~~~~~~~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:40:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
   40 |         for num_threads in range(1, MAX_THREADS + 1):
      |                   ^~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:35:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
   35 | 
      |             ^                     
/Users/mrs/net/Python-3.14.6/Tools/lockbench/lockbench.py:30:16: warning: '_mojo_dispatch_getattr' defined but not used [-Wunused-function]
   30 | 
      |                ^                     
lockbench.ci:458:16: warning: 'id' defined but not used [-Wunused-function]
  458 | static int64_t id (int64_t x) { return x; }
      |                ^~
lockbench.ci:457:19: warning: '_Bool_items' defined but not used [-Wunused-function]
... (15 more lines)
```

Exit code: 1
Elapsed: 14.03s
