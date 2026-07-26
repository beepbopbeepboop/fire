# COMPILE_FAIL: Lib/xml/dom/pulldom.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py: In function '_alloc_DOMEventStream':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:121:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  121 |             node.setAttributeNode(attr)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py: In function '_alloc_PullDOM':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:135:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  135 |             self.lastEvent = self.lastEvent[1]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py: In function 'PullDOM___init__':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:30:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   30 |         self._current_context = self._ns_contexts[-1]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:39:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   39 |         self._locator = locator
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:33:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   33 |     def pop(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:32:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   32 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:29:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   29 |         self._ns_contexts = [{XML_NAMESPACE:'xml'}] # contains uri -> prefix dicts
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:493:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:491:14: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:490:14: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:489:7: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:488:11: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:487:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:486:7: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:485:14: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:484:14: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:483:10: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:482:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:481:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:480:10: warning: variable '_t37' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:479:10: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:478:14: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:477:14: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:476:9: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:475:9: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:474:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:473:9: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:472:11: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:471:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:470:7: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:469:10: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/pulldom.py:468:11: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
... (4243 more lines)
```

Exit code: 1
Elapsed: 14.16s
