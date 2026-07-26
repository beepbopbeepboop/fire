# COMPILE_FAIL: Lib/email/policy.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/policy.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function '_alloc_EmailPolicy':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:77:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   77 |                            special treatment, while all other fields are
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function 'EmailPolicy___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:106:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  106 |     def header_max_count(self, name):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:289:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:281:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:279:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:278:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:277:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:276:14: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:275:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:274:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:273:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:272:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:271:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:270:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:269:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:268:17: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:267:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:266:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:265:9: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:264:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:263:9: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:262:7: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:261:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function 'EmailPolicy_header_max_count':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:119:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  119 |     # convert it to use the newer style by just changing its policy.  It is
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:117:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  117 |     # Message object constructed with this policy to be passed to a library
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:116:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  116 |     # from this class and have the results stay consistent.  This allows a
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:115:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  115 |     # switch a Message object between a Compat32 policy and a policy derived
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:114:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  114 |     # The logic of the next three methods is chosen such that it is possible to
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:113:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  113 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:112:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
... (196 more lines)
```

Exit code: 1
Elapsed: 9.54s
