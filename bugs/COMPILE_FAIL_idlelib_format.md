# COMPILE_FAIL: Lib/idlelib/format.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:63:11: warning: unused variable '_tag' [-Wunused-variable]
   63 |         if comment_header:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:68:11: warning: unused variable '_tag' [-Wunused-variable]
   68 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:73:11: warning: unused variable '_tag' [-Wunused-variable]
   73 |             text.insert(first, newdata)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:88:11: warning: unused variable '_tag' [-Wunused-variable]
   88 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:97:13: warning: unused variable '_tag' [-Wunused-variable]
   97 |     comment_header = get_comment_header(line)
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py: In function 'FormatParagraph___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:272:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  272 |                 lines[pos] = self.editwin._make_blanks(effective) + line[raw:]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:270:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  270 |                 raw, effective = get_line_indent(line, self.editwin.tabwidth)
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py: In function 'FormatParagraph_reload':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:50:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   50 |         by blank lines) and formats it.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:48:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   48 |         If no text is selected, format_paragraph_event uses the current
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:47:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   47 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:46:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   46 |         at the max width, starting from the beginning selection.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:45:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   45 |         If text is selected, format_paragraph_event will start breaking lines
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:44:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   44 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/format.py:43:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   43 |         """Formats paragraph to a max width specified in idleConf.
      |          ^~~
... (859 more lines)
```

Exit code: 1
Elapsed: 11.84s
