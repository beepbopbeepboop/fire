# COMPILE_FAIL: Lib/email/quoprimime.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:43:11: warning: unused variable '_tag' [-Wunused-variable]
   43 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:48:11: warning: unused variable '_tag' [-Wunused-variable]
   48 | EMPTYSTRING = ''
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:53:11: warning: unused variable '_tag' [-Wunused-variable]
   53 | # characters.  Initialize both maps with the full expansion, and then override
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 |           b'abcdefghijklmnopqrstuvwxyz{|}~\t'):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:77:13: warning: unused variable '_tag' [-Wunused-variable]
   77 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function 'header_check_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:216:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  216 |                 # will be the only content on the subsequent line.
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function 'body_check_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:81:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   81 |     return chr(octet) != _QUOPRI_BODY_MAP[octet]
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function 'header_length_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:86:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   86 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function 'body_length_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:99:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   99 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py: In function '_max_append_7a6366':
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:113:34: error: passing argument 3 of 'mojo_list_set_int' makes integer from pointer without a cast [-Wint-conversion]
  113 |         L[-1] += extra + s
      |                                  ^   
      |                                  |
      |                                  char *
In file included from quoprimime.ci:14:
/Users/mrs/net/chatgpt/claude/mojo-reference/runtime/mojo_runtime.h:105:60: note: expected 'int64_t' {aka 'long long int'} but argument is of type 'char *'
  105 | void     mojo_list_set_int(MojoList *l, int64_t i, int64_t v);
      |                                                    ~~~~~~~~^
/Users/mrs/net/Python-3.14.6/Lib/email/quoprimime.py:163:7: warning: variable '_t55' set but not used [-Wunused-but-set-variable]
  163 |     quoted-printable character "=" appended to them, so the decoded text will
      |       ^~~~
... (132 more lines)
```

Exit code: 1
Elapsed: 9.56s
