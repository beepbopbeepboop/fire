# COMPILE_FAIL: antigravity.py

Source: `/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/antigravity.py`

## Error

```
# ERROR: compiling imported module 'hashlib' from /opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/hashlib.py: 140:7: Expected COLON got LPAREN('(')
# ERROR: compiling imported module 'webbrowser' from /opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/webbrowser.py: 265:17: Expected COLON got DOT('.')
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/antigravity.py:43:15: error: invalid operands to binary % (have 'char *' and 'int')
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/antigravity.py:17:15: error: invalid operands to binary % (have 'char *' and 'MojoList *')
```

Exit code: 1
