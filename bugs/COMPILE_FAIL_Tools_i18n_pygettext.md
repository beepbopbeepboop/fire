# COMPILE_FAIL: Tools/i18n/pygettext.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current error:

```
error: non-trivial conversion in 'var_decl'
```
at `def get_source_comments(source):` (an unannotated parameter,
declared `int64_t` per the generated `.ci`'s `int64_t
get_source_comments_0c85c9 (int64_t source)`). The function builds and
returns a `MojoDict *` (`comments = mojo_dict_new()` ... eventually
returned), but the C function signature declares `int64_t` as its
return type — a return-type/param-type mismatch consistent with (but
not conclusively pinned to) the general "unannotated parameter/field
defaults to int64_t regardless of real usage" family already documented
in `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
(that doc is about `__init__` fields specifically; this would be the
analogous free-function RETURN-type gap if confirmed — not chased down
far enough to be certain). Not fixed here.

```
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: warning: f-string interpolation '{}' could not be compiled; emitting it as literal text (SyntaxError: 0:0: Unexpected EOF(''))
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function '_alloc_GettextVisitor':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:92:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   92 |         extracted string is found in the source.  These lines appear before
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function '_alloc_Location':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:106:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  106 |     --style stylename
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function '_alloc_Message':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:120:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  120 |     --version
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function 'usage_cebb44':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:526:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  526 |         max_index = max(spec.values())
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:525:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  525 |         """
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function 'make_escapes_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:192:11: warning: variable 'escape' set but not used [-Wunused-but-set-variable]
  192 |         # escape any character outside the 32..126 range.
      |           ^~~~~~
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function 'escape_ascii_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:209:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  209 |                    for c in s)
      |              ^  
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function 'escape_nonascii_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:222:10: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
  222 |     else:
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:217:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  217 |     # This converts the various Python string types into a format that is
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:213:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  213 |     return ''.join(escapes[b] for b in s.encode(encoding))
      |              ^~~
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py: In function 'normalize_1ce6ce':
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:257:10: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  257 |         if not name:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:251:11: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
  251 |         # try to find module or package
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/i18n/pygettext.py:221:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  221 |         s = '"' + escape(s, encoding) + '"'
      |          ^~~
... (1210 more lines)
```

Exit code: 1
Elapsed: 13.91s
