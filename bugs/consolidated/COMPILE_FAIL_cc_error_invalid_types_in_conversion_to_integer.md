# COMPILE_FAIL: CC ERROR: invalid types in conversion to integer

**6 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:57:11: warning: unused variable '_tag' [-Wunused-variable]
   57 |             else:
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:62:11: warning: unused variable '_tag' [-Wunused-variable]
   62 |             # status will be the same as the char before it, if should.
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:67:11: warning: unused variable '_tag' [-Wunused-variable]
   67 |         self.rawtext = parser.code[:-2]
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 |         """Set the index to which the functions relate.
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:91:13: warning: unused variable '_tag' [-Wunused-variable]
   91 |         self.indexinrawtext = indexinrawtext
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function 'HyperParser___init___index2line':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:197:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  197 |             # identifier, don't eat anything. At this point that is only
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:195:10: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
  195 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:194:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  194 |                 i -= 1
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:193:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  193 |             if i - 1 >= limit and ('a' + str[i - 1:pos]).isidentifier():
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:36:1: error: invalid types in conversion to integer
   36 |         lno = index2line(text.index(index))
      | ^
char *
double
_t3 = (char *) _t1;
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py: In function 'HyperParser___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:30:9: error: 'HyperParser' has no member named 'text'; did you mean 'rawtext'?
   30 |         self.text = text = editwin.text
      |         ^~~~
      |         rawtext
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_14' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_18' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_16' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_17' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: label 'bb_15' defined but not used [-Wunused-label]
   76 |                          self.bracketing[i-1][1]
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/idlelib/hyperparser.py:76:1: warning: la
```

## Affected files

- `Lib/idlelib/hyperparser.py`
- `Lib/idlelib/idle_test/test_codecontext.py`
- `Lib/idlelib/idle_test/test_sidebar.py`
- `Lib/test/test_int.py`
- `Lib/test/test_numeric_tower.py`
- `Lib/test/test_strtod.py`
