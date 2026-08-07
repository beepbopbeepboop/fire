# COMPILE_FAIL: Apple/testbed/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Apple/testbed/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; the original stale doc below was truncated GCC-warning noise
(and mistakenly duplicated `Apple/__main__.py`'s own content — a
doc-generation bug in whatever produced these boilerplate reports, not
something about this file). Current real errors:

```
/Users/mrs/net/Python-3.14.6/Apple/testbed/__main__.py:148:15: error: invalid operands to binary / (have 'char *' and 'int64_t' {aka 'long long int'})
/Users/mrs/net/Python-3.14.6/Apple/testbed/__main__.py:176:29: error: invalid operands to binary / (have 'char *' and 'int64_t' {aka 'long long int'})
/Users/mrs/net/Python-3.14.6/Apple/testbed/__main__.py:225:17: error: invalid operands to binary / (have 'char *' and 'int')
/Users/mrs/net/Python-3.14.6/Apple/testbed/__main__.py:425:17: error: invalid operands to binary / (have 'char *' and 'int64_t' {aka 'long long int'})
```

All four are `pathlib.Path.__truediv__` (`/`) sites where the RHS is a
subscript into the module-level dict global `TEST_SLICES = {"iOS":
"ios-arm64_x86_64-simulator"}` (line 176: `xc_framework_path /
TEST_SLICES[platform]`; line 135/400 area similar) or a related
opaque-typed expression. Root-caused: `TEST_SLICES[platform]` resolves
to `int64_t` instead of `char *` inside any function OTHER than
`_toplevel`, so the codegen's `/` → `mojo_path_join` dispatch (which
gates on `rt == 'char *'`, `gimple_codegen.py:9157`) never fires and a
raw (invalid) `char * / int64_t` C expression is emitted instead.

Attempted a narrow, additive fix (teach `gen_module`'s Phase 1.7 global
prescan to record a dict global's VALUE type, mirroring the shipped
list-element-type fix in `bugs/COMPILE_FAIL_importlib__bootstrap_external.md`,
commit `fd29316`) — implemented and confirmed REACHED (Phase 1.7 does
record it), but instrumented tracing then showed it has **zero
effect**: `_reset_func()` (called at the very start of every
`gen_func`, before Phase 2a compiles ANY function body) unconditionally
wipes the exact side-table (`_dict_val_types`, and — confirmed by the
same investigation — `_elem_types`, the list-case sibling) that Phase
1.7 just populated, before even the FIRST function body's first
statement is processed. This is a genuinely deeper, pre-existing bug
that also appears to undermine the already-shipped `fd29316` fix's
general robustness (its own motivating file evidently still compiles
clean, via some difference in trigger shape not chased down here — but
the mechanism it depends on does not work in general, confirmed via a
hand-reduced repro of that exact same list-global shape).

Reverted the attempted fix (didn't actually work, so nothing to keep)
and wrote it up in full as a new hard bug instead:
`bugs/hard/CODEGEN_reset_func_wipes_global_container_type_inference.md`
— NOT fixed here. `_lower_IdentExpr`'s global-read branch (which this
would need to touch) is the single highest-traffic function in this
codegen and the repro already shows entanglement with return-type
inference, one of the three machinery classes this session's CLAUDE.md
flags as high-risk. Left for a dedicated session per that doc's own
"What a real fix needs".

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
Elapsed: 5.35s
