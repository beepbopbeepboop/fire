# COMPILE_FAIL: CC ERROR: expected identifier or 'X' before 'X'

**37 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:43:17: error: expected identifier or '(' before 'default'
   43 |     depending on the type of the field.  The folding algorithm fully
      |                 ^~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:55:4: error: expected identifier before 'default'
   55 | 
      |    ^      
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:56:3: error: expected '}' before '.' token
   56 |     refold_source       -- if the value for a header in the Message object
      |   ^
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:50:37: note: to match this '{'
   50 |                            serialized as ASCII, using encoded words to encode
      |                                     ^
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function '_alloc_EmailPolicy':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:74:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   74 |                            header.  A default header_factory is provided that
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |                            content_manager is
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:93:11: warning: unused variable '_tag' [-Wunused-variable]
   93 |     message_factory = EmailMessage
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:98:11: warning: unused variable '_tag' [-Wunused-variable]
   98 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:113:11: warning: unused variable '_tag' [-Wunused-variable]
  113 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:122:13: warning: unused variable '_tag' [-Wunused-variable]
  122 |     # applications only a few headers will actually be inspected.
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py: In function 'EmailPolicy___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:106:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  106 |     def header_max_count(self, name):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:243:1: warning: label 'bb_3' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:235:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  235 | del default.header_factory
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:233:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  233 | default = EmailPolicy()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:232:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  232 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:231:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  231 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:230:14: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
  230 |         return name + ': ' + self.linesep.join(lines) + self.linesep
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:229:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  229 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/policy.py:228:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
  228 |             return 
```

## Affected files

- `Lib/email/policy.py`
- `Lib/multiprocessing/reduction.py`
- `Lib/multiprocessing/resource_tracker.py`
- `Lib/test/test_capi/test_abstract.py`
- `Lib/test/test_capi/test_bytearray.py`
- `Lib/test/test_capi/test_bytes.py`
- `Lib/test/test_capi/test_codecs.py`
- `Lib/test/test_capi/test_dict.py`
- `Lib/test/test_capi/test_eval_code_ex.py`
- `Lib/test/test_capi/test_exceptions.py`
- `Lib/test/test_capi/test_file.py`
- `Lib/test/test_capi/test_import.py`
- `Lib/test/test_capi/test_list.py`
- `Lib/test/test_capi/test_long.py`
- `Lib/test/test_capi/test_run.py`
- `Lib/test/test_capi/test_sys.py`
- `Lib/test/test_capi/test_tuple.py`
- `Lib/test/test_capi/test_unicode.py`
- `Lib/test/test_capi/test_weakref.py`
- `Tools/build/deepfreeze.py`
- `Tools/build/umarshal.py`
- `Tools/c-analyzer/c_common/scriptutil.py`
- `Tools/cases_generator/analyzer.py`
- `Tools/cases_generator/cwriter.py`
- `Tools/cases_generator/lexer.py`
- `Tools/cases_generator/opcode_id_generator.py`
- `Tools/cases_generator/opcode_metadata_generator.py`
- `Tools/cases_generator/parser.py`
- `Tools/cases_generator/parsing.py`
- `Tools/cases_generator/py_metadata_generator.py`
- `Tools/cases_generator/target_generator.py`
- `Tools/cases_generator/tier1_generator.py`
- `Tools/cases_generator/tier2_generator.py`
- `Tools/cases_generator/uop_id_generator.py`
- `Tools/cases_generator/uop_metadata_generator.py`
- `Tools/clinic/libclinic/utils.py`
- `Tools/ftscalingbench/ftscalingbench.py`
