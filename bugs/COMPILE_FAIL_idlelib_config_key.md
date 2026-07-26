# COMPILE_FAIL: Lib/idlelib/config_key.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py: In function '_alloc_GetKeysFrame':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:177:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  177 |         if sys.platform == "darwin":
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py: In function 'translate_key_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:632:11: warning: variable '_t84' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:629:10: warning: variable '_t81' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:625:10: warning: variable '_t77' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:548:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py: In function 'GetKeysFrame___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:75:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:81:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   81 |         # Basic entry key sequence.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:79:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   79 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:75:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:93:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   93 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:91:7: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
   91 |                            borderwidth=2)
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:90:9: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
   90 |                            textvariable=self.key_string, relief='groove',
      |         ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:89:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
   89 |         basic_keys = Label(self.frame_keyseq_basic, justify='left',
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:88:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   88 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:87:7: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
   87 |         basic_title.pack(anchor='w')
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:86:14: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
   86 |                             text=f"New keys for '{self.action}' :")
      |              ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:85:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
   85 |         basic_title = Label(self.frame_keyseq_basic,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config_key.py:84:11: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
   84 |                                       padx=5, pady=5)
      |           ^   
... (1836 more lines)
```

Exit code: 1
Elapsed: 11.83s
