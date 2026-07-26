# COMPILE_FAIL: Lib/idlelib/config.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py: In function '_alloc_IdleConf':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:200:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  200 |         if not os.path.exists(userDir):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py: In function '_alloc_IdleConfParser':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:214:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  214 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py: In function '_alloc_IdleUserConfParser':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:228:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  228 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py: In function 'IdleConfParser___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:894:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  894 |         print('\n', cfg, '\n')  # Cfg has variable '0xnnnnnnnn' address.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:892:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  892 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:891:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  891 |         #print('***', line, crc, '***')  # Uncomment for diagnosis.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:890:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  890 |         print(txt)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:889:20: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  889 |         crc = crc32(txt.encode(encoding='utf-8'), crc)
      |                    ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:888:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  888 |         line += 1
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:887:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  887 |         txt = str(obj)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:886:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  886 |         nonlocal line, crc
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:885:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  885 |     def sprint(obj):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py: In function 'IdleConfParser_Get':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:66:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   66 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:73:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   73 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/config.py:68:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   68 |         "Return a list of options for given section, else []."
... (5177 more lines)
```

Exit code: 1
Elapsed: 11.25s
