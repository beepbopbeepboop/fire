# COMPILE_FAIL: Lib/idlelib/pyshell.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function '_alloc_ModifiedInterpreter':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:352:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  352 |                 return
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function '_alloc_MyRPCClient':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:366:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  366 |     def undo_event(self, event):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function '_alloc_PyShell':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:380:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  380 | class UserInputTaggingDelegator(Delegator):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function '_alloc_PyShellFileList':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:394:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  394 | def restart_line(width, filename):  # See bpo-38141.
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function '_alloc_UserInputTaggingDelegator':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:408:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  408 | class ModifiedInterpreter(InteractiveInterpreter):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:915:16: error: conflicting types for 'system'; have 'int64_t()' {aka 'long long int()'}
  915 |         text.bind("<<squeeze-current-text>>",
      |                ^~~~~~
In file included from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/stdlib.h:58,
                 from pyshell.ci:5:
/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/_stdlib.h:208:10: note: previous declaration of 'system' with type 'int(const char *)'
  208 | int      system(const char *) __DARWIN_ALIAS_C(system);
      |          ^~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function 'idle_showwarning_b9e112':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:1314:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
 1314 |             self.text.see("insert")
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:1312:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
 1312 |         if self.reading:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:1308:10: warning: unused variable '_t11' [-Wunused-variable]
 1308 |             self.newline_and_indent_event(event)
      |          ^  ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:1298:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
 1298 |         if self.text.compare("insert", "<", "iomark"):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function 'capture_warnings_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:91:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   91 |             _warnings_showwarning = warnings.showwarning
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py: In function 'extended_linecache_checkcache_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/pyshell.py:151:7: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
  151 |         ("Set Breakpoint", "<<set-breakpoint>>", None),
... (9392 more lines)
```

Exit code: 1
Elapsed: 10.31s
