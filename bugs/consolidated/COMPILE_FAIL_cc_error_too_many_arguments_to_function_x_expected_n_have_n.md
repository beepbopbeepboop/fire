# COMPILE_FAIL: CC ERROR: too many arguments to function 'X'; expected N, have N

**10 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:31:11: warning: unused variable '_tag' [-Wunused-variable]
   31 |     encdata = str(_bencode(orig), 'ascii')
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:36:11: warning: unused variable '_tag' [-Wunused-variable]
   36 | def encode_quopri(msg):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |     orig = msg.get_payload(decode=True)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:56:11: warning: unused variable '_tag' [-Wunused-variable]
   56 |     try:
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:65:13: warning: unused variable '_tag' [-Wunused-variable]
   65 |     """Do nothing."""
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function '_qencode_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:158:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:156:10: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function 'encode_base64_79c856':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:31:9: error: too many arguments to function 'mojo_str'; expected 1, have 2
   31 |     encdata = str(_bencode(orig), 'ascii')
      |         ^~~~~~~~       ~~~
In file included from encoders.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:312:7: note: declared here
  312 | char *mojo_str(void *obj);  /* Flexible signature for both int and char* */
      |       ^~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:36:7: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   36 | def encode_quopri(msg):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:35:10: warning: variable 'encdata' set but not used [-Wunused-but-set-variable]
   35 | 
      |          ^      
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:27:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   27 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function 'encode_quopri_79c856':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:43:7: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   43 |     msg.set_payload(encdata)
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:42:10: warning: variable 'encdata' set but not used [-Wunused-but-set-variable]
   42 |     encdata = _qencode(orig)
      |          ^~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:38:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   38 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py: In function 'encode_7or8bit_79c856':
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:71:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:68:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:65:10: warning: unused variable '_t16' [-Wunused-variable]
   65 |     """Do nothing."""
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/encoders.py:49:10: warning: variable '_t1' set but not used [-Wunused-but-
```

## Affected files

- `Lib/email/encoders.py`
- `Lib/encodings/__init__.py`
- `Lib/encodings/idna.py`
- `Lib/encodings/punycode.py`
- `Lib/test/crashers/gc_inspection.py`
- `Lib/test/test_ctypes/test_bitfields.py`
- `Lib/test/test_shelve.py`
- `Modules/_decimal/tests/bignum.py`
- `Modules/_decimal/tests/randdec.py`
- `Tools/freeze/freeze.py`
