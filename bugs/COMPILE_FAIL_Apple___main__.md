# COMPILE_FAIL: Apple/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Apple/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:69:11: warning: unused variable '_tag' [-Wunused-variable]
   69 |     "iOS": {
      |           ^~  
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:74:11: warning: unused variable '_tag' [-Wunused-variable]
   74 |             "arm64-apple-ios-simulator": "arm64-iphonesimulator",
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:79:11: warning: unused variable '_tag' [-Wunused-variable]
   79 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:94:11: warning: unused variable '_tag' [-Wunused-variable]
   94 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:103:13: warning: unused variable '_tag' [-Wunused-variable]
  103 |     """Run a command in an Apple development environment.
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function 'subdir_dd9b3c':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:521:7: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
  521 |     except FileExistsError:
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:520:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
  520 |         package_path.mkdir()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:517:11: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
  517 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:502:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  502 |     in the lib directory.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function 'run_e1e570':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:128:11: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
  128 |         return str(args)
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:117:7: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  117 |         print(">", join_command(command))
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:99:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   99 |     env: EnvironmentT | None = None,
      |           ^~~
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:97:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   97 |     *,
      |          ^  
/Users/mrs/net/Python-3.14.6/Apple/__main__.py: In function 'join_command_584a43':
/Users/mrs/net/Python-3.14.6/Apple/__main__.py:130:8: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
  130 |         return shlex.join(map(str, args))
... (650 more lines)
```

Exit code: 1
Elapsed: 5.37s
