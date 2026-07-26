# COMPILE_FAIL: PC/layout/support/appxmanifest.py

Source file: `/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 |     DisplayName="IDLE (Python {})".format(VER_DOT),
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:71:11: warning: unused variable '_tag' [-Wunused-variable]
   71 | )
      |           ^   
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:76:11: warning: unused variable '_tag' [-Wunused-variable]
   76 |     "": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:91:11: warning: unused variable '_tag' [-Wunused-variable]
   91 |     xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:100:13: warning: unused variable '_tag' [-Wunused-variable]
  100 |               ProcessorArchitecture="" />
      |             ^ ~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py: In function 'get_packagefamilyname_1ce6ce':
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:404:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
  404 |     for k in node.keys():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:398:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  398 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:397:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  397 |     QN = ET.QName
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:395:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  395 |     xml = ET.parse(io.StringIO(APPXMANIFEST_TEMPLATE))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:394:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  394 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:383:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  383 |     e = find_or_add(xml, "m:Properties")
      |           ^~~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:379:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  379 |             k.set("ValueType", "REG_SZ")
      |           ^ ~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py: In function '_fixup_sccd_d02436':
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:239:14: error: request for member 'name' in something not a structure or union
  239 |     sccd = ns.temp / sccd.name
      |              ^~
/Users/mrs/net/Python-3.14.6/PC/layout/support/appxmanifest.py:240:14: error: request for member 'parent' in something not a structure or union
  240 |     sccd.parent.mkdir(parents=True, exist_ok=True)
      |              ^~
... (395 more lines)
```

Exit code: 1
Elapsed: 13.14s
