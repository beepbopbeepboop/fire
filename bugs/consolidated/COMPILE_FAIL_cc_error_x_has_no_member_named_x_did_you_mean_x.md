# COMPILE_FAIL: CC ERROR: 'X' has no member named 'X'; did you mean 'X'?

**17 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:64:11: warning: unused variable '_tag' [-Wunused-variable]
   64 |     in order to inherit Cmd's methods and encapsulate action methods.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 |     ruler = '='
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 |     misc_header = "Miscellaneous help topics:"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:89:11: warning: unused variable '_tag' [-Wunused-variable]
   89 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:98:13: warning: unused variable '_tag' [-Wunused-variable]
   98 |         self.cmdqueue = []
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function 'Cmd___init__':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:100:1: warning: label 'bb_7' defined but not used [-Wunused-label]
  100 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:98:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   98 |         self.cmdqueue = []
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:102:1: warning: label 'bb_6' defined but not used [-Wunused-label]
  102 |         """Repeatedly issue a prompt, accept input, parse an initial prefix
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:96:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   96 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:94:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   94 |         if stdout is not None:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:86:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   86 |         specify alternate input and output file objects; if not specified,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:252:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  252 |         By default, it returns an empty list.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:250:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  250 |         complete_*() method is available.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:249:14: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  249 |         """Method called to complete an input line when no command-specific
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:248:14: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  248 |     def completedefault(self, *ignored):
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:247:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  247 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:246:10: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  246 |         self.stdout.write('*** Unknown syntax: %s\n'%line)
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:245:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  245 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:244:10: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  244 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:243:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  243 |         returns.
      |           ^~~~
/Users/mrs/net/P
```

## Affected files

- `Lib/cmd.py`
- `Lib/idlelib/autocomplete_w.py`
- `Lib/idlelib/calltip.py`
- `Lib/idlelib/window.py`
- `Lib/idlelib/zzdummy.py`
- `Lib/test/_test_eintr.py`
- `Lib/test/libregrtest/main.py`
- `Lib/test/test_asyncio/test_windows_events.py`
- `Lib/test/test_calendar.py`
- `Lib/test/test_dynamicclassattribute.py`
- `Lib/test/test_importlib/resources/test_reader.py`
- `Lib/test/test_importlib/test_abc.py`
- `Lib/test/test_pathlib/test_copy.py`
- `Lib/test/test_property.py`
- `Lib/test/test_sched.py`
- `Tools/clinic/libclinic/converters.py`
- `Tools/peg_generator/pegen/parser_generator.py`
