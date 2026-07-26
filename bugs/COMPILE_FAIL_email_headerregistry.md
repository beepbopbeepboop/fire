# COMPILE_FAIL: Lib/email/headerregistry.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py: In function '_alloc_Group':
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:185:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  185 |     The subclass should also make sure that a 'max_count' attribute is defined
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py: In function 'Address___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:126:1: warning: label 'bb_18' defined but not used [-Wunused-label]
  126 |         return self._display_name
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:122:1: warning: label 'bb_17' defined but not used [-Wunused-label]
  122 |         self._addresses = tuple(addresses) if addresses else tuple()
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:114:1: warning: label 'bb_16' defined but not used [-Wunused-label]
  114 |         lists that are a combination of Groups and individual Addresses.  In
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:109:1: warning: label 'bb_15' defined but not used [-Wunused-label]
  109 |         An address group consists of a display_name followed by colon and a
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:93:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   93 |             return "{} <{}>".format(disp, addr_spec)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:85:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   85 |                         self.display_name, self.username, self.domain)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:80:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   80 |         return lp
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:76:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   76 |         if self.domain:
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:72:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   72 |         """
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:54:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   54 |         self._domain = domain
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:67:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   67 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:61:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   61 |     def username(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:53:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   53 |         self._username = username
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:50:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   50 |             username = a_s.local_part
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/headerregistry.py:42:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   42 |                                 "domain also specified")
... (5878 more lines)
```

Exit code: 1
Elapsed: 11.25s
