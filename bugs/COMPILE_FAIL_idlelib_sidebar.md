# COMPILE_FAIL: Lib/idlelib/sidebar.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function '_alloc_EndLineDelegator':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:179:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  179 |         # upon <B1-Motion>, until <B1-Enter> or the mouse button is released.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function '_alloc_LineNumbers':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:193:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  193 |             a, b = sorted([start_line, lineno])
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function '_alloc_WrappedLineHeightChangeDelegator':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:207:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  207 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function 'get_lineno_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:18:3: error: cannot convert to a pointer type
   18 |     return int(float(text_index)) if text_index else None
      |   ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:639:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:637:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function 'get_end_linenumber_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:23:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   23 |     return get_lineno(text, 'end-1c')
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function 'get_displaylines_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:41:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   41 |         raise ValueError(f"Unsupported geometry manager: {manager}")
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:40:10: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   40 |     else:
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:34:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   34 |     # TODO: use also in codecontext.py
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:28:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   28 |     return text.count(f"{index} linestart",
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function 'get_widget_padding_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:45:20: error: passing argument 1 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
   45 |     padx = sum(map(widget.tk.getint, [
      |                    ^~~~
      |                    |
      |                    int64_t {aka long long int}
In file included from sidebar.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:333:22: note: expected 'void *' but argument is of type 'int64_t' {aka 'long long int'}
  333 | void *mojo_map(void *func, void *iterable);
      |                ~~~~~~^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:45:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
   45 |     padx = sum(map(widget.tk.getint, [
      |        ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:45:20: error: passing argument 1 of 'mojo_sum' makes pointer from integer without a cast [-Wint-conversion]
... (4821 more lines)
```

Exit code: 1
Elapsed: 10.58s
