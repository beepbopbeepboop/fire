# COMPILE_FAIL: Tools/build/generate_sbom.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py: In function '_alloc_PackageFiles':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:61:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   61 |     ),
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py: In function 'spdx_id_584a43':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:309:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  309 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py: In function 'error_if_4ea62f':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:105:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
  105 |         subprocess.check_call(
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:104:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
  104 |     try:
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:96:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   96 |     if value:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py: In function 'is_root_directory_git_index':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:126:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
  126 |     """
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:123:11: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
  123 |     And looks like this for matching (excluded) files:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:113:10: warning: unused variable '_t7' [-Wunused-variable]
  113 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:107:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  107 |             stdout=subprocess.DEVNULL,
      |          ^  
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py: In function 'filter_gitignored_paths_79c856':
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:188:7: warning: variable '_t66' set but not used [-Wunused-but-set-variable]
  188 |         # Properties and ID must be properly formed.
      |       ^ ~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:185:11: warning: variable '_t63' set but not used [-Wunused-but-set-variable]
  185 |     """Make a bunch of assertions about the SBOM package data to ensure it's consistent."""
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:178:11: warning: variable '_t56' set but not used [-Wunused-but-set-variable]
  178 |                 raise OSError(msg) from ex
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:169:11: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
  169 |                           base_delay: float = 2.25,
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:145:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
  145 |     # Return the list of paths sorted
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/generate_sbom.py:117:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  117 |     Filter out paths excluded by the gitignore file.
... (159 more lines)
```

Exit code: 1
Elapsed: 14.11s
