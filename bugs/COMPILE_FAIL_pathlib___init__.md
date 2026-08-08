# COMPILE_FAIL: Lib/pathlib/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-07)

Re-ran fresh against current master. The 2026-08-06 error set (the
`_os.py` exception-attribute errors and the `__init__.py:72`/`:404`
negative-index-slice errors) no longer reproduces at all — compilation
now gets further and fails at a completely different point:

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py
[gimple_codegen] generator method Path.'walk' not eligible for C++ coroutine path, falling back to honest refusal: walk: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
Error building: cannot compile module: function(s) walk (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification:** same family as `bugs/hard/
CODEGEN_generator_struct_typed_param_refused.md` (see that doc's
scope note and `CODEGEN_generator_function_Lib_ftplib.md`'s matching
`mlsd` case) — `Path.walk()` does `yield path, dirnames, filenames` (a
3-tuple), which the coroutine codegen's scalar-only yield-value
allow-list refuses outright, escalating to a fatal whole-module
`RuntimeError` for the CLI's `mojo.py build` path since `walk` is a
real `Path`/`PosixPath`/`WindowsPath` method reachable from the module
root.

Not fixed here — genuine feature-sized coroutine-codegen scope
boundary already covered by task #147's exclusion for this session (see
that doc). The two previously-reported issues (exception dynamic-attr
write, negative-index slice) may or may not still be latent further
into the file; both are now moot since `walk`'s refusal is hit first
and hard-fails the whole module before either is reached.

None fixed here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py: In function '_alloc__PathParents':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:381:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  381 |     @property
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py: In function '_PathParents___init__':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1116:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1116 |             target = self.with_segments(target_dir, name)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1114:7: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
 1114 |             target = target_dir / name
      |       ^   
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1113:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
 1113 |         elif hasattr(target_dir, 'with_segments'):
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1112:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
 1112 |             raise ValueError(f"{self!r} has an empty name")
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1111:10: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
 1111 |         if not name:
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1110:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
 1110 |         name = self.name
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1109:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
 1109 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1108:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
 1108 |         Copy this file or directory tree into the given existing directory.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1107:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
 1107 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1106:7: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
 1106 |     def copy_into(self, target_dir, **kwargs):
      |       ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1105:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
 1105 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1104:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
 1104 |         return target.joinpath()  # Empty join to ensure fresh metadata.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1103:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
 1103 |         target._copy_from(self, **kwargs)
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:1102:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
 1102 |         ensure_distinct_paths(self, target)
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py: In function '_PathParents___len__':
/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py:68:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (34916 more lines)
```

Exit code: 1
Elapsed: 10.23s
