# COMPILE_FAIL: Lib/test/test_xml_dom_minicompat.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |         # Writing
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:78:11: warning: unused variable '_tag' [-Wunused-variable]
   78 |         node_list = NodeList([3, 4]) + [1, 2]
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:83:11: warning: unused variable '_tag' [-Wunused-variable]
   83 |         self.assertEqual(node_list, NodeList([1, 2, 3, 4]))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 |             node_list.append(2)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:107:13: warning: unused variable '_tag' [-Wunused-variable]
  107 |         copied = copy.copy(node_list)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py: In function 'EmptyNodeListTestCase_test_emptynodelist_item':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:208:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:206:11: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:205:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:204:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:203:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:202:14: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:201:7: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:200:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:199:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:198:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:197:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:196:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:195:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:194:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:193:14: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:192:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:191:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:190:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:189:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:188:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:187:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:186:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:185:11: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:184:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:183:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:182:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:181:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_minicompat.py:180:11: warning: variable 'node_list' set but not used [-Wunused-but-set-variable]
... (376 more lines)
```

Exit code: 1
Elapsed: 12.74s
