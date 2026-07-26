# COMPILE_FAIL: Lib/test/test_asyncio/test_base_events.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/test/test_asyncio/test_base_events.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo: In function 'std_python__cpython_CPython_PyRun_String':
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:1858:52: error: passing argument 1 of 'std_python__cpython_CPython__PyRun_String' makes integer from pointer without a cast [-Wint-conversion]
 1858 |         return self._PyRun_String(
      |                                                    ^   
      |                                                    |
      |                                                    CPython *
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:515:82: note: expected 'int64_t' {aka 'long long int'} but argument is of type 'CPython *'
  515 |             Py_tp_init, rebind[OpaquePointer[MutUntrackedOrigin]](func)
      |                                                                                  ^    
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo: In function 'std_python__cpython_CPython_Py_CompileString':
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:1879:56: error: passing argument 1 of 'std_python__cpython_CPython__Py_CompileString' makes integer from pointer without a cast [-Wint-conversion]
 1879 |         return self._Py_CompileString(
      |                                                        ^   
      |                                                        |
      |                                                        CPython *
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:519:86: note: expected 'int64_t' {aka 'long long int'} but argument is of type 'CPython *'
  519 |     def tp_methods(methods: _CPointer[PyMethodDef, MutUntrackedOrigin]) -> Self:
      |                                                                              ~~~     ^    
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo: In function 'std_python__cpython_CPython_PyEval_EvalCode':
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:1899:55: error: passing argument 1 of 'std_python__cpython_CPython__PyEval_EvalCode' makes integer from pointer without a cast [-Wint-conversion]
 1899 |         return self._PyEval_EvalCode(co, globals, locals)
      |                                                       ^~~ 
      |                                                       |
      |                                                       CPython *
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:523:85: note: expected 'int64_t' {aka 'long long int'} but argument is of type 'CPython *'
  523 |         )
      |                                                                                     ^    
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo: In function 'std_python__cpython_CPython_Py_NewRef':
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:1916:49: error: passing argument 1 of 'std_python__cpython_CPython__Py_NewRef' makes integer from pointer without a cast [-Wint-conversion]
 1916 |         return self._Py_NewRef(o)
      |                                                 ^   
      |                                                 |
      |                                                 CPython *
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:527:79: note: expected 'int64_t' {aka 'long long int'} but argument is of type 'CPython *'
  527 |         return PyType_Slot(
      |                                                                               ^    
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo: In function 'std_python__cpython_CPython_PyErr_GetRaisedException':
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:2034:64: error: passing argument 1 of 'std_python__cpython_CPython__PyErr_GetRaisedException' makes integer from pointer without a cast [-Wint-conversion]
 2034 |         return self._PyErr_GetRaisedException()
      |                                                                ^   
      |                                                                |
      |                                                                CPython *
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:559:94: note: expected 'int64_t' {aka 'long long int'} but argument is of type 'CPython *'
  559 |     var object_ref_count: Py_ssize_t
      |                                                                                              ^    
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo: In function 'std_python__cpython_CPython_PyErr_Fetch':
/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib/std/python/_cpython.mojo:2050:52: error: passing argument 1 of 'std_python__cpython_CPython__PyErr_Fetch' makes integer from pointer without a cast [-Wint-conversion]
 2050 |         self._PyErr_Fetch(
      |                                                    ^   
      |                                                    |
... (19600 more lines)
```

Exit code: 1
Elapsed: 12.01s
