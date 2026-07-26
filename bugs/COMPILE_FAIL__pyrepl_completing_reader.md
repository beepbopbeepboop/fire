# COMPILE_FAIL: _pyrepl/completing_reader.py

Source: `/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py`

## Error

```
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:84:7: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:105:15: error: invalid operands to binary % (have 'char *' and 'char *')
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:114:15: error: invalid operands to binary % (have 'char *' and 'int64_t' {aka 'long long int'})
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:169:13: error: 'complete' has no member named 'reader'
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:170:13: error: 'complete' has no member named '__class__'
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:182:4: error: 'CompletingReader' has no member named 'msg'
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:183:4: error: 'CompletingReader' has no member named 'dirty'
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:192:11: error: 'CompletingReader' has no member named 'console'
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:195:4: error: 'CompletingReader' has no member named 'dirty'
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/completing_reader.py:199:4: error: 'CompletingReader' has no member named 'msg'
```

Exit code: 1
