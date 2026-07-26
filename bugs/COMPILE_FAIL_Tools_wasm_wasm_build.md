# COMPILE_FAIL: Tools/wasm/wasm_build.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py: In function '_alloc_BuildProfile':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:214:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  214 |         raise MissingDependency("cc", INSTALL_NATIVE)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py: In function '_alloc_Platform':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:228:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  228 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py: In function 'parse_emconfig_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:724:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
  724 |         host=Host.wasm32_emscripten,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:719:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  719 |         dynamic_linking=True,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:697:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  697 | _profiles = [
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py: In function 'read_python_version_0c85c9':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:150:11: warning: variable 'f' set but not used [-Wunused-but-set-variable]
  150 |             mo = version_re.match(line)
      |           ^
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:147:11: warning: variable 'version_re' set but not used [-Wunused-but-set-variable]
  147 |     version_re = re.compile(r"^PACKAGE_VERSION='(\d\.\d+)'")
      |           ^~~~~~~~~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:143:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  143 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:140:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  140 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py: In function 'ConditionError___init__':
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:173:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  173 |     pass
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:171:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
  171 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:170:10: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
  170 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:169:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
  169 |     pass
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:168:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
  168 | class MissingDependency(ConditionError):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Tools/wasm/wasm_build.py:167:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
  167 | 
... (2366 more lines)
```

Exit code: 1
Elapsed: 11.19s
