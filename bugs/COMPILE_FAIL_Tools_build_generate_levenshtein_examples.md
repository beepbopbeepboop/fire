# COMPILE_FAIL: Tools/build/generate_levenshtein_examples.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:41:11: warning: unused variable '_tag' [-Wunused-variable]
   41 |     args = parser.parse_args()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:46:11: warning: unused variable '_tag' [-Wunused-variable]
   46 |             "To force, add --overwrite to the invocation of this tool or"
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:51:11: warning: unused variable '_tag' [-Wunused-variable]
   51 |     examples: set[tuple[str, str, int]] = set()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:66:11: warning: unused variable '_tag' [-Wunused-variable]
   66 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:75:13: warning: unused variable '_tag' [-Wunused-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py: In function '_gimple_main':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:145:11: warning: variable '_t101' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:142:11: warning: variable '_t98' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:138:11: warning: variable 'f' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:130:7: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:118:11: warning: variable '_t75' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:111:7: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:100:11: warning: variable '_t60' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:98:11: warning: variable '_t58' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:97:11: warning: variable '_t57' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:90:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:88:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:87:11: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:68:7: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
   68 | if __name__ == "__main__":
      |       ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:58:7: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
   58 |         examples.add((a, b, expected))
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:50:11: warning: variable '_t14' set but not used [-Wunused-but-set-variable]
   50 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:47:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   47 |             " delete the existing file."
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:44:11: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   44 |         print(f"{output_path} already exists, skipping regeneration.")
      |           ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_levenshtein_examples.py:41:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   41 |     args = parser.parse_args()
      |           ^~~
... (38 more lines)
```

Exit code: 1
Elapsed: 14.35s
