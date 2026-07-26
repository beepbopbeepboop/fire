# COMPILE_FAIL: CC ERROR: invalid operands to binary % (have 'X' and 'X')

**40 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:29:11: warning: unused variable '_tag' [-Wunused-variable]
   29 | ONE_THIRD = 1.0/3.0
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:34:11: warning: unused variable '_tag' [-Wunused-variable]
   34 | # Y: perceived grey level (0.0 == black, 1.0 == white)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:39:11: warning: unused variable '_tag' [-Wunused-variable]
   39 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:54:11: warning: unused variable '_tag' [-Wunused-variable]
   54 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:63:13: warning: unused variable '_tag' [-Wunused-variable]
   63 |     if g > 1.0:
      |             ^~~ 
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'rgb_to_hls_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:96:15: error: invalid operands to binary % (have 'double' and 'double')
   96 |     h = (h/6.0) % 1.0
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_v_37269f':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:110:13: error: invalid operands to binary % (have 'double' and 'double')
  110 |     hue = hue % 1.0
      |             ^
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'rgb_to_hsv_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:142:15: error: invalid operands to binary % (have 'double' and 'double')
  142 |     h = (h/6.0) % 1.0
      |               ^
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'hsv_to_rgb_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:148:3: error: cannot convert to a pointer type
  148 |     i = int(h*6.0) # XXX assume int() truncates!
      |   ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function '_toplevel':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:173:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: In function 'hsv_to_rgb_132aaf':
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:169:1: warning: control reaches end of non-void function [-Wreturn-type]
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py: At top level:
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:50:13: warning: '_mojo_classattr_init' defined but not used [-Wunused-function]
   50 | 
      |             ^                   
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:81:15: warning: '_mojo_repr_dict' defined but not used [-Wunused-function]
   81 |     if minc == maxc:
      |               ^~~~~~         
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:52:15: warning: '_mojo_dispatch_repr' defined but not used [-Wunused-function]
   52 |     g = y - 0.27478764629897834*i - 0.6356910791873801*q
      |               ^~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:43:12: warning: '_mojo_dispatch_is_dataclass' defined but not used [-Wunused-function]
   43 |     q = 0.48*(r-y) + 0.41*(b-y)
      |            ^~~~~~~~~~~~~~~~~~~~       
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:38:19: warning: '_mojo_dispatch_fields' defined but not used [-Wunused-function]
   38 | # The ones in this library uses constants from the FCC version of NTSC.
      |                   ^~~~~~~~~~~~~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Lib/colorsys.py:33:13: warning: '_mojo_dispatch_setattr' defined but not used [-Wunused-function]
   33 | # YIQ: used by composite video signals (linear combinations of RGB)
      |            
```

## Affected files

- `Lib/colorsys.py`
- `Lib/curses/has_key.py`
- `Lib/email/base64mime.py`
- `Lib/email/message.py`
- `Lib/email/utils.py`
- `Lib/encodings/uu_codec.py`
- `Lib/opcode.py`
- `Lib/test/bisect_cmd.py`
- `Lib/test/libregrtest/run_workers.py`
- `Lib/test/pythoninfo.py`
- `Lib/test/support/threading_helper.py`
- `Lib/test/test_bdb.py`
- `Lib/test/test_code.py`
- `Lib/test/test_ctypes/test_strings.py`
- `Lib/test/test_gdb/test_pretty_print.py`
- `Lib/test/test_multiprocessing_main_handling.py`
- `Lib/test/test_sax.py`
- `Lib/test/test_urllib.py`
- `Lib/test/test_zipimport_support.py`
- `Lib/test/test_zstd.py`
- `Lib/turtledemo/penrose.py`
- `Lib/unittest/loader.py`
- `Lib/unittest/util.py`
- `Lib/wsgiref/handlers.py`
- `Lib/wsgiref/headers.py`
- `Lib/wsgiref/validate.py`
- `Lib/xml/dom/expatbuilder.py`
- `Modules/_decimal/tests/deccheck.py`
- `Modules/_decimal/tests/formathelper.py`
- `PCbuild/prepare_ssl.py`
- `Tools/build/generate_token.py`
- `Tools/c-analyzer/distutils/util.py`
- `Tools/freeze/makemakefile.py`
- `Tools/freeze/regen_frozen.py`
- `Tools/patchcheck/reindent.py`
- `Tools/patchcheck/untabify.py`
- `Tools/scripts/combinerefs.py`
- `Tools/unicode/comparecodecs.py`
- `Tools/unicode/gencodec.py`
- `Tools/unicode/mkstringprep.py`
