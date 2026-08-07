# COMPILE_FAIL: Android/android.py

Source file: `/Users/mrs/net/Python-3.14.6/Android/android.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; the original ~880-line GCC warning dump below is STALE (it was
truncated before ever reaching the real error). The actual, current
failure is an honest up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) async_check_output,
find_device, find_pid, gradle_task, list_devices, logcat_task,
read_bytes, read_int, read_logcat, run_testbed (async function(s),
declared `async def`); async_process (async generator function(s),
declared `async def` AND contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these cannot
be represented as compiled C without emitting silently wrong or broken
code; falling back to interpreting this module from source instead
```

This is an async/generator codegen refusal, part of the separate,
already-tracked compiled-generator/async-codegen project (tasks
#95-135) — not investigated further here per that project's scope.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_alloc_LogPriority':
/Users/mrs/net/Python-3.14.6/Android/android.py:123:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  123 |     if log:
      | ^   
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Android/android.py:137:11: warning: unused variable '_tag' [-Wunused-variable]
  137 | # Format the environment so it can be pasted into a shell.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Android/android.py:142:11: warning: unused variable '_tag' [-Wunused-variable]
  142 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Android/android.py:147:11: warning: unused variable '_tag' [-Wunused-variable]
  147 |         prefix = ANDROID_DIR / "prefix"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Android/android.py:162:11: warning: unused variable '_tag' [-Wunused-variable]
  162 |     for line in env_output.splitlines():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Android/android.py:171:13: warning: unused variable '_tag' [-Wunused-variable]
  171 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'log_verbose_132aaf':
/Users/mrs/net/Python-3.14.6/Android/android.py:621:7: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  621 |         raise ValueError(
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Android/android.py:612:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  612 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'delete_glob_0c85c9':
/Users/mrs/net/Python-3.14.6/Android/android.py:99:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   99 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'subdir':
/Users/mrs/net/Python-3.14.6/Android/android.py:127:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  127 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Android/android.py:125:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  125 |     return subprocess.run(command, env=env, **kwargs)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Android/android.py:122:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  122 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Android/android.py:103:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  103 |     if not path.exists():
      |          ^~~
/Users/mrs/net/Python-3.14.6/Android/android.py: In function 'run_0211bc':
... (826 more lines)
```

Exit code: 1
Elapsed: 5.39s
