# COMPILE_FAIL: False Positive - Build Reports Failure Despite Successful Compilation

## Status
**Open** - `mojo.py build` reports failure with `-g3` flag even though compilation succeeds.

## Test Reference
Full file: `/opt/homebrew/opt/python@3.14/Frameworks/Python.framework/Versions/3.14/lib/python3.14/_compat_pickle.py`

## Symptoms
- `mojo.py build -o /tmp/t.o <file>` exits with code 1
- stderr contains: `Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)`
- But `/tmp/t.o` is produced and is a valid executable
- Running the compiled file works correctly (exit code 0)

## Example
```
$ python3 mojo.py build -o /tmp/t.o _compat_pickle.py
... (gcc warnings about -g3) ...
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
$ echo $?
1
$ /tmp/t.o
$ echo $?
0
```

## Root Cause
The `-g3` debug flag is not supported by the gcc installation, causing a warning that is treated as an error. However, the compilation still succeeds and produces a valid executable.

## Impact
- False positives in automated testing
- Build system incorrectly reports failures
- Affects many stdlib files

## Affected Files
- _compat_pickle.py
- _ios_support.py (though this one has real linker errors too)
- _markupbase.py
- _osx_support.py
- _py_abc.py
- _pyio.py
- (and many others that succeed despite the warning)

## Python Spec
This is not a Python syntax issue, but a toolchain compatibility issue.

## Related Issues
- [ ] Test runner should verify output file exists and is valid before declaring failure
- [ ] gcc-15 or appropriate toolchain configuration needed
- [ ] Consider using `-g2` instead of `-g3` as default

