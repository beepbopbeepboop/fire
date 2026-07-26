# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/_info.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py: In function '_alloc_TextInfo':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:35:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   35 |                 lno = fileinfo.lno
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py: In function 'TextInfo___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:21:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   21 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:21:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   21 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:16:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   16 |         self.text = text.strip()
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:16:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   16 |         self.text = text.strip()
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:16:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   16 |         self.text = text.strip()
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:14:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   14 |         # mutable:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:243:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:238:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:236:7: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:235:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:234:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:233:7: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:232:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:231:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:230:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:229:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:228:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:227:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:226:9: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:225:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:224:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:223:7: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:222:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:221:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:220:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:219:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:218:14: warning: variable 'lines' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:217:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:216:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:215:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:214:14: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/_info.py:213:9: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
... (1209 more lines)
```

Exit code: 1
Elapsed: 13.72s
