# COMPILE_FAIL: Tools/build/compute-changes.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py: In function '_alloc_Outputs':
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:84:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   84 |     Path("Modules/_json.c"),
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py: In function 'compute_changes':
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:396:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:392:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py: In function 'git_refs':
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:205:10: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
  205 |     if len(file.parts) >= 2 and Path(*file.parts[:2]) in WASI_DIRS: # Tools/wasm/
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:204:10: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
  204 |         return "emscripten"
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:185:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  185 |     print(*args)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:184:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
  184 |     args = ("git", "diff", "--name-only", f"{ref_a}...{ref_b}", "--")
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py: In function 'get_changed_files_abb124':
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:190:20: error: passing argument 1 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
  190 |     return frozenset(map(Path, filter(None, map(str.strip, changed_files))))
      |                    ^~~~
      |                    |
      |                    int64_t {aka long long int}
In file included from compute-changes.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:22: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                ~~~~~~^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:190:26: error: passing argument 2 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
  190 |     return frozenset(map(Path, filter(None, map(str.strip, changed_files))))
      |                          ^~~~~~~~~~~~~
      |                          |
      |                          int64_t {aka long long int}
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:34: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                            ~~~~~~^~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:190:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
  190 |     return frozenset(map(Path, filter(None, map(str.strip, changed_files))))
      |        ^
/Users/mrs/net/Python-3.14.6/Tools/build/compute-changes.py:190:26: error: passing argument 2 of 'mojo_filter' makes pointer from integer without a cast [-Wint-conversion]
  190 |     return frozenset(map(Path, filter(None, map(str.strip, changed_files))))
      |                          ^~~~
      |                          |
      |                          int64_t {aka long long int}
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:334:37: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  334 | void *mojo_filter(void *func, void *iterable);
      |                               ~~~~~~^~~~~~~~
... (141 more lines)
```

Exit code: 1
Elapsed: 13.97s
