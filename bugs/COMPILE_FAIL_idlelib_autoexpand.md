# COMPILE_FAIL: Lib/idlelib/autoexpand.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |             return "break"
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 |         if index == 0:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |         self.state = words, index, curinsert, curline
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |             return []
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:75:13: warning: unused variable '_tag' [-Wunused-variable]
   75 |             dict[w] = w
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py: In function 'AutoExpand___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:170:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:168:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:167:7: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:166:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:165:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:164:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:163:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:162:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:161:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:160:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:159:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:158:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py: In function 'AutoExpand_expand_word_event':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:43:15: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
   43 |         self.text.delete("insert - %d chars" % len(word), "insert")
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:134:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:122:10: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:114:7: warning: variable '_t77' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:111:7: warning: variable '_t74' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:108:7: warning: variable '_t71' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:105:11: warning: variable '_t68' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:96:11: warning: variable 'newword' set but not used [-Wunused-but-set-variable]
   96 |     main('idlelib.idle_test.test_autoexpand', verbosity=2)
      |           ^~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/autoexpand.py:90:7: warning: variable '_t54' set but not used [-Wunused-but-set-variable]
   90 |             i = i-1
      |       ^   
... (167 more lines)
```

Exit code: 1
Elapsed: 10.18s
