# COMPILE_FAIL: CC ERROR: invalid call to non-function before 'X' token

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:129:11: warning: unused variable '_tag' [-Wunused-variable]
  129 |         for attr, value in expected.items():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:134:11: warning: unused variable '_tag' [-Wunused-variable]
  134 |             self.assertEqual(getattr(added, attr), value)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:139:11: warning: unused variable '_tag' [-Wunused-variable]
  139 |     def test_fold_utf8(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:154:11: warning: unused variable '_tag' [-Wunused-variable]
  154 |         self.assertEqual(p_utf8.fold('Subject', s), expected_utf8)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:163:13: warning: unused variable '_tag' [-Wunused-variable]
  163 |         p2 = email.policy.default.clone(max_line_length=None)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py: In function 'make_defaults_1ce6ce':
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:317:7: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  317 | 
      |       ^  
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py: In function 'PolicyAPITests_test_defaults':
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:84:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   84 |                         self.assertIn(attr, expected,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:75:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   75 |     def test_all_attributes_covered(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:81:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   81 |                                   types.FunctionType)):
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:82:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   82 |                         continue
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:78:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   78 |                 with self.subTest(policy=policy, attr=attr):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:90:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   90 |         msg = str(cm.exception)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:79:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   79 |                     if (attr.startswith('_') or
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:75:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   75 |     def test_all_attributes_covered(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:66:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   66 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_email/test_policy.py:64:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
   64 |     # later that proves this.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_ema
```

## Affected files

- `Lib/test/test_email/test_policy.py`
- `Tools/wasm/wasi/__main__.py`
