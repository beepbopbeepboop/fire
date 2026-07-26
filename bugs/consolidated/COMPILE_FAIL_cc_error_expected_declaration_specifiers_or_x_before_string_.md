# COMPILE_FAIL: CC ERROR: expected declaration specifiers or 'X' before string constant

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
In file included from test_getargs.ci:7:
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:420:11: error: expected declaration specifiers or '...' before string constant
  420 |         # K return 'unsigned long long', no range checking
      |           ^~~
In file included from /Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk/usr/include/stdint.h:52,
                 from /opt/local/lib/gcc15/gcc/aarch64-apple-darwin25/15.2.0/include/stdint.h:11,
                 from test_getargs.ci:4:
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:423:11: error: expected identifier or '(' before 'void'
  423 |         self.assertEqual(0, getargs_K(IndexIntSubclass()))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:423:11: error: expected ')' before numeric constant
  423 |         self.assertEqual(0, getargs_K(IndexIntSubclass()))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:439:4: error: 'struct _root_toplev' has no member named '__builtin_nanf'
  439 |         self.assertEqual(42, getargs_K(42))
      |    ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:439:4: error: expected '=' before '(' token
  439 |         self.assertEqual(42, getargs_K(42))
      |    ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:440:3: error: expected '}' before '.' token
  440 | 
      |   ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:433:37: note: to match this '{'
  433 | 
      |                                     ^
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:444:17: warning: integer constant is too large for its type
  444 | class Float_TestCase(unittest.TestCase, FloatsAreIdenticalMixin):
      |                 ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py: In function '_alloc_BadComplex':
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:458:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  458 |         self.assertRaises(TypeError, getargs_f, Int())
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py: In function '_alloc_BadComplex2':
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:472:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  472 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py: In function '_alloc_BadComplex3':
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:486:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  486 |         self.assertEqual(getargs_d(FloatSubclass2(7.5)), 7.5)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py: In function '_alloc_BadFloat':
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:500:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  500 |         r = getargs_d(NAN)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py: In function '_alloc_BadFloat2':
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:514:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  514 |         self.assertEqual(getargs_D(BadComplex3(7.5+0.25j)), 7.5+0.25j)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py: In function '_alloc_BadFloat3':
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:528:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  528 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py: In function '_alloc_BadIndex':
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.py:542:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  542 |         self.assertEqual(0, getargs_p(''))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_capi/test_getargs.p
```

## Affected files

- `Lib/test/test_capi/test_getargs.py`
- `Lib/test/test_ctypes/test_numbers.py`
