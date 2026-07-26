# COMPILE_FAIL: Lib/idlelib/idle_test/test_editmenu.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:47:11: warning: unused variable '_tag' [-Wunused-variable]
   47 |     def test_paste_entry(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:52:11: warning: unused variable '_tag' [-Wunused-variable]
   52 |             for end, ans in (0, 'onetwo'), ('end', 'two'):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |                     entry.event_generate('<<Paste>>')
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:81:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py: In function 'PasteTest_setUpClass':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:19:6: error: request for member 'root' in something not a structure or union
   19 |         cls.root = root = tk.Tk()
      |      ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:209:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:207:11: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:206:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:205:10: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:204:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:203:10: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:202:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:201:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:200:11: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:199:10: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:198:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:197:11: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:196:10: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:195:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:194:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:193:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:192:10: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:191:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:190:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:189:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:188:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:187:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:186:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:185:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:184:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:183:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_editmenu.py:182:10: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
... (454 more lines)
```

Exit code: 1
Elapsed: 11.57s
