# COMPILE_FAIL: Tools/ssl/multissltests.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:144:11: warning: unused variable '_tag' [-Wunused-variable]
  144 | parser.add_argument(
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:149:11: warning: unused variable '_tag' [-Wunused-variable]
  149 | )
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:154:11: warning: unused variable '_tag' [-Wunused-variable]
  154 |     url_templates = None
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:169:11: warning: unused variable '_tag' [-Wunused-variable]
  169 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:178:13: warning: unused variable '_tag' [-Wunused-variable]
  178 |         self.src_dir = os.path.join(args.base_directory, 'src')
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py: In function 'AbstractBuilder___init__':
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:491:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  491 |         if not os.path.samefile('python', sys.executable):
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:489:7: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  489 |                     "Must be executed from CPython build dir"
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:488:10: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
  488 |                 parser.error(
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:487:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  487 |             if not os.path.isfile(os.path.join(PYTHONROOT, name)):
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:486:10: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
  486 |         for name in ['Makefile.pre.in', 'Modules/_ssl.c']:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:485:7: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
  485 |     if args.steps in {'modules', 'tests'}:
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:484:10: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
  484 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:483:11: warning: variable '_t40' set but not used [-Wunused-but-set-variable]
  483 |     start = datetime.now()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:482:11: warning: variable '_t39' set but not used [-Wunused-but-set-variable]
  482 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/ssl/multissltests.py:481:10: warning: variable '_t38' set but not used [-Wunused-but-set-variable]
... (3694 more lines)
```

Exit code: 1
Elapsed: 13.77s
