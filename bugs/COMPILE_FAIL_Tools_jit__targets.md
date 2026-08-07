# COMPILE_FAIL: Tools/jit/_targets.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/jit/_targets.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current failure is an honest up-front refusal, not a GCC error:

```
Error building: cannot compile module: function(s) _build_stencils,
_compile, _parse (async function(s), declared `async def`) — this
codegen compiles every function into a single straight-line C function
and has no suspend/resume state-machine transform for generators, nor
an event loop / suspend-resume codegen for async functions, yet, so
these cannot be represented as compiled C without emitting silently
wrong or broken code; falling back to interpreting this module from
source instead
```

Async-function codegen refusal, part of the separate, already-tracked
compiled-generator/async-codegen project (tasks #95-135) — not
investigated further here per that project's scope.

```
# ERROR: compiling imported module '_stencils' from /Users/mrs/net/Python-3.14.6/Tools/jit/_stencils.py: 11:1: Expected NAME got KW('enum')
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/jit/_schema.py: In function '__schema_toplevel':
/Users/mrs/net/Python-3.14.6/Tools/jit/_schema.py:61:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   61 |     """A Mach-O object file relocation record."""
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py: In function '_dump_footer_2fc997':
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:260:10: warning: variable '_t133' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:259:11: warning: variable '_t132' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:258:10: warning: variable '_t131' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:257:11: warning: variable '_t130' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:254:10: warning: variable '_t127' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:243:11: warning: variable '_t116' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:226:10: warning: variable '_t101' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:217:11: warning: variable '_t92' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:216:10: warning: variable '_t91' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:215:11: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:214:10: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:213:11: warning: variable '_t88' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:210:10: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:205:11: warning: variable '_t80' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:197:11: warning: variable '_t72' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:175:10: warning: variable '_t52' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:174:11: warning: variable '_t51' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:173:10: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:172:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:171:10: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:164:11: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:159:11: warning: variable '_t36' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:158:10: warning: variable '_t35' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:157:11: warning: variable '_t34' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:156:10: warning: variable '_t33' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:155:11: warning: variable '_t32' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:154:10: warning: variable '_t31' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:153:11: warning: variable '_t30' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:152:10: warning: variable '_t29' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:151:11: warning: variable '_t28' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:150:10: warning: variable '_t27' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:149:11: warning: variable '_t26' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:148:10: warning: variable '_t25' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:147:11: warning: variable '_t24' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:146:10: warning: variable '_t23' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:145:11: warning: variable '_t22' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:144:10: warning: variable '_t21' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:143:11: warning: variable '_t20' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:142:10: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:141:11: warning: variable '_t18' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:140:10: warning: variable '_t17' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:139:11: warning: variable '_t16' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/jit/_writer.py:138:10: warning: variable '_t15' set but not used [-Wunused-but-set-variable]
... (18380 more lines)
```

Exit code: 1
Elapsed: 14.80s
