# COMPILE_FAIL: Lib/email/_policybase.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py: In function '_alloc_Compat32':
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:90:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   90 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py: In function 'validate_header_name_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:319:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  319 |         value = ''.join((value, *sourcelines[1:])).lstrip(' \t\r\n')
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py: In function '_PolicyBase___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:69:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   69 |     def clone(self, **kw):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:66:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   66 |                  for name, value in self.__dict__.items() ]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:61:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   61 |                     "{!r} is an invalid keyword argument for {}".format(
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:85:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   85 |         return newpolicy
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:75:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   75 |         """
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:66:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   66 |                  for name, value in self.__dict__.items() ]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:62:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   62 |                         name, self.__class__.__name__))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:379:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  379 |             # Assume it is a Header-like object.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:377:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
  377 |                 h = header.Header(value, header_name=name)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:376:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
  376 |             else:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:375:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  375 |                     h = None
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:374:11: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
  374 |                     parts.append(value)
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:373:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
  373 |                     # be to not split the string and risk it being too long.
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_policybase.py:372:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
... (1537 more lines)
```

Exit code: 1
Elapsed: 62.00s
