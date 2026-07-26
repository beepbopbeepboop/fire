# COMPILE_FAIL: Lib/cmd.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/cmd.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 |         sys.stdin and sys.stdout are used.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |         else:
      |           ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:97:11: warning: unused variable '_tag' [-Wunused-variable]
   97 |             self.stdout = sys.stdout
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:112:11: warning: unused variable '_tag' [-Wunused-variable]
  112 |                 self.old_completer = readline.get_completer()
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:121:13: warning: unused variable '_tag' [-Wunused-variable]
  121 |                     command_string = f"{self.completekey}: complete"
      |             ^   
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
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:275:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  275 |                 cmd, args, foo = self.parseline(line)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:273:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  273 |             endidx = readline.get_endidx() - stripped
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:272:14: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  272 |             begidx = readline.get_begidx() - stripped
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/cmd.py:271:14: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
... (2564 more lines)
```

Exit code: 1
Elapsed: 9.48s
