# COMPILE_FAIL: Lib/email/_header_value_parser.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_AddrSpec':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:960:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  960 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_Address':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:974:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  974 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_AddressList':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:988:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  988 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_AngleAddr':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1002:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1002 | #
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_Atom':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1016:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1016 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_Attribute':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1030:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1030 |     This function turns a run of qcontent, ccontent-without-comments, or
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_BareQuotedString':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1044:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1044 |             if escape:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_CFWSList':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1058:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1058 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_Comment':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1072:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1072 |     """ encoded-word = "=?" charset "?" encoding "?" encoded-text "?="
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_ContentDisposition':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1086:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1086 |         remstr[1] in hexdigits and
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_ContentTransferEncoding':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1100:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1100 |             "encoded word format invalid: '{}'".format(ew.cte))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_ContentType':
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py:1114:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1114 |     # Encoded words should be followed by a WS
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_header_value_parser.py: In function '_alloc_DisplayName':
... (8896 more lines)
```

Exit code: 1
Elapsed: 64.08s
