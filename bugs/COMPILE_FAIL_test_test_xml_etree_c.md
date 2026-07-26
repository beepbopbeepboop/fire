# COMPILE_FAIL: Lib/test/test_xml_etree_c.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:118:11: warning: unused variable '_tag' [-Wunused-variable]
  118 |         elem.clear()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:123:11: warning: unused variable '_tag' [-Wunused-variable]
  123 |     @support.cpython_only
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:128:11: warning: unused variable '_tag' [-Wunused-variable]
  128 |         self.assertRaises(ValueError, parser.close)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:143:11: warning: unused variable '_tag' [-Wunused-variable]
  143 |                                '_children': [cET.Element('child')],
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:152:13: warning: unused variable '_tag' [-Wunused-variable]
  152 |         self.assertEqual(elem[0].tag, 'child')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py: In function 'MiscTests_test_length_overflow':
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:36:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   36 |         with self.assertRaises(AttributeError):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:29:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   29 |         element = cET.Element('tag')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:26:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   26 |             data = None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:31:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   31 |         element.tag = 'TAG'
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:33:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   33 |             del element.tag
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:306:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:304:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:303:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:302:10: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:301:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:300:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:299:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:298:10: warning: unused variable '_t10' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:296:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:295:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:294:9: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:293:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_etree_c.py:292:11: warning: variable 'parser' set but not used [-Wunused-but-set-variable]
... (1930 more lines)
```

Exit code: 1
Elapsed: 12.90s
