# COMPILE_FAIL: CC ERROR: unknown type name 'X'

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:47:58: error: unknown type name 'saved'
   47 |         self.test_name = test_name
      |                                                          ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:48:38: error: unknown type name 'saved'
   48 |         self.verbose = verbose
      |                                      ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:49:46: error: unknown type name 'saved'
   49 |         self.quiet = quiet
      |                                              ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:50:69: error: unknown type name 'saved'
   50 |         self.pgo = pgo
      |                                                                     ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:51:58: error: unknown type name 'saved'
   51 | 
      |                                                          ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:52:38: error: unknown type name 'saved'
   52 |     # To add things to save and restore, add a name XXX to the resources list
      |                                      ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:53:41: error: unknown type name 'saved'
   53 |     # and add corresponding get_XXX/restore_XXX functions.  get_XXX should
      |                                         ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:54:42: error: unknown type name 'saved'
   54 |     # return the value to be saved and compared against a second call to the
      |                                          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:55:59: error: unknown type name 'saved'
   55 |     # get function when test execution completes.  restore_XXX should accept
      |                                                           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:56:56: error: unknown type name 'saved'
   56 |     # the saved value and restore the resource using it.  It will be called if
      |                                                        ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:57:42: error: unknown type name 'saved'
   57 |     # and only if a change in the value is detected.
      |                                          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:58:69: error: unknown type name 'saved'
   58 |     #
      |                                                                     ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:59:49: error: unknown type name 'saved'
   59 |     # Note: XXX will have any '.' replaced with '_' characters when determining
      |                                                 ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:60:61: error: unknown type name 'saved'
   60 |     # the corresponding method names.
      |                                                             ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:61:60: error: unknown type name 'saved'
   61 | 
      |                                                            ^    
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:62:45: error: unknown type name 'saved'
   62 |     resources = ('sys.argv', 'cwd', 'sys.stdin', 'sys.stdout', 'sys.stderr',
      |                                             ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:63:47: error: unknown type name 'saved'
   63 |                  'os.environ', 'sys.path', 'sys.path_hooks', '__import__',
      |                                               ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:64:44: error: unknown type name 'saved'
   6
```

## Affected files

- `Lib/test/libregrtest/save_env.py`
