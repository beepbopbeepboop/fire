# COMPILE_FAIL: Lib/test/test_xml_dom_xmlbuilder.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_xml_dom_xmlbuilder.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_getDOMImplementation", referenced from:
      _XMLBuilderTest_test_builder in test_xml_dom_xmlbuilder.o
      _XMLBuilderTest_test_parse_uri in test_xml_dom_xmlbuilder.o
      _XMLBuilderTest_test_parse_with_systemId in test_xml_dom_xmlbuilder.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 14.97s
