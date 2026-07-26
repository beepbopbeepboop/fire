# COMPILE_FAIL: CC ERROR: cannot convert to a pointer type

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function '_alloc_EndLineDelegator':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:146:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  146 |         # Note that without this, scrolling with the mouse only scrolls
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function '_alloc_LineNumbers':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:160:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  160 |             for event_name in (f'<Button-{button}>',
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function '_alloc_WrappedLineHeightChangeDelegator':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:174:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  174 |         # start_line is set upon <Button-1> to allow selecting a range of rows
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py: In function 'get_lineno_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:18:3: error: cannot convert to a pointer type
   18 |     return int(float(text_index)) if text_index else None
      |   ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:564:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/sidebar.py:562:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
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
   45 |     padx = sum(map(widget.tk.getint, [
      |                    ^~~~
      |                    |
      |                    int64_t {aka long long int}
/Users/mrs/net/chatgpt/claude
```

## Affected files

- `Lib/idlelib/sidebar.py`
- `Lib/test/test_tomllib/burntsushi.py`
