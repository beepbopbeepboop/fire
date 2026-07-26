# COMPILE_FAIL: Tools/c-analyzer/distutils/cygwinccompiler.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
   94 |     def __init__(self, verbose=0, dry_run=0, force=0):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:99:11: warning: unused variable '_tag' [-Wunused-variable]
   99 |         self.debug_print("Python's GCC status: %s (details: %s)" %
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:104:11: warning: unused variable '_tag' [-Wunused-variable]
  104 |                 "Reason: %s. "
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:119:11: warning: unused variable '_tag' [-Wunused-variable]
  119 |         # dllwrap 2.10.90 is buggy
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:128:13: warning: unused variable '_tag' [-Wunused-variable]
  128 |             shared_option = "-shared"
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py: In function 'get_msvcr':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:276:11: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
  276 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:262:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  262 |     out = Popen(cmd, shell=True, stdout=PIPE).stdout
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:255:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  255 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py: In function 'CygwinCCompiler___init__':
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:154:1: warning: label 'bb_12' defined but not used [-Wunused-label]
  154 | # the same as cygwin plus some additional parameters
      | ^~~~~
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:149:1: warning: label 'bb_13' defined but not used [-Wunused-label]
  149 |             # Include the appropriate MSVC runtime library if Python was built
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:144:1: warning: label 'bb_11' defined but not used [-Wunused-label]
  144 |             # (gcc version 2.91.57) -- perhaps something about initialization
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:133:1: warning: label 'bb_9' defined but not used [-Wunused-label]
  133 |         # XXX optimization, warnings etc. should be customizable.
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:131:1: warning: label 'bb_10' defined but not used [-Wunused-label]
  131 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/distutils/cygwinccompiler.py:134:1: warning: label 'bb_8' defined but not used [-Wunused-label]
  134 |         self.set_executables(compiler='gcc -mcygwin -O -Wall',
      | ^   
... (562 more lines)
```

Exit code: 1
Elapsed: 13.51s
