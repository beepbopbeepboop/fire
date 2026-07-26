# COMPILE_FAIL: _pyrepl/main.py

Source: `/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/main.py`

## Error

```
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/main.py:19:29: error: assignment to 'char *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_pyrepl/main.py:22:29: error: assignment to 'char *' from 'int64_t' {aka 'long long int'} makes pointer from integer without a cast [-Wint-conversion]
```

Exit code: 1
