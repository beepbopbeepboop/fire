# COMPILE_FAIL: Lib/xml/etree/ElementPath.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py: In function '_alloc__SelectorContext':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 |     r"\.\.|"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py: In function 'xpath_tokenizer_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:324:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  324 |                 index = -1
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:323:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  323 |             else:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:321:9: warning: variable 'parsing_attribute' set but not used [-Wunused-but-set-variable]
  321 |                 if index > -2:
      |         ^       ~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:320:11: warning: variable 'default_namespace' set but not used [-Wunused-but-set-variable]
  320 |                     raise SyntaxError("unsupported expression")
      |           ^         ~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py: In function 'get_parent_map_0b3eb7':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:98:11: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   98 | def get_parent_map(context):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py: In function '_alloc__prepare_tag_select_env':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:117:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  117 |         # justification for '{*}*' doing the same.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py: In function '_prepare_tag_select':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:127:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  127 |                 if _isinstance(el_tag, _str) and el_tag[0] != '{':
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:125:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  125 |             for elem in result:
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py: In function '_prepare_tag_79c856':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:189:11: warning: variable 'no_ns' set but not used [-Wunused-but-set-variable]
  189 |         tag = "*"
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:154:11: warning: variable '_str' set but not used [-Wunused-but-set-variable]
  154 |     tag = token[1]
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:151:11: warning: variable '_isinstance' set but not used [-Wunused-but-set-variable]
  151 | 
      |           ^          
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py: In function 'prepare_child_select_select_child':
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:157:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  157 |         def select(context, result):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/etree/ElementPath.py:155:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  155 |     if _is_wildcard_tag(tag):
      |          ^~~
... (241 more lines)
```

Exit code: 1
Elapsed: 14.09s
