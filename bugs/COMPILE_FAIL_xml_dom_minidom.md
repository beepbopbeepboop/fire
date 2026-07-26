# COMPILE_FAIL: Lib/xml/dom/minidom.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_Attr':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:560:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  560 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_CDATASection':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:574:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  574 |                 node.ownerDocument = self._ownerElement.ownerDocument
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_Comment':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:588:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  588 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_Document':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:602:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  602 |                 n.ownerElement = None
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_DocumentFragment':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:616:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  616 |         else:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_DocumentType':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:630:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  630 |         return old
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_Element':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:644:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  644 |         self._attrs, self._attrsNS, self._ownerElement = state
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_Entity':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:658:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  658 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_NamedNodeMap':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:672:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  672 | _no_type = TypeInfo(None, None)
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_Notation':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:686:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  686 |                          Node.COMMENT_NODE,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_ProcessingInstruction':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:700:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  700 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_ReadOnlySequentialNamedNodeMap':
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py:714:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  714 |             self._attrs = {}
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/xml/dom/minidom.py: In function '_alloc_Text':
... (36315 more lines)
```

Exit code: 1
Elapsed: 15.54s
