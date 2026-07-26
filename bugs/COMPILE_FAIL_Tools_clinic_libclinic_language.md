# COMPILE_FAIL: Tools/clinic/libclinic/language.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/language.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_fail", referenced from:
      _Language_validate_assert_only_one_local_fail in language.o
      _Language_validate_assert_only_one_local_fail in language.o
      _Language_validate_assert_only_one in language.o
      _Language_validate_assert_only_one in language.o
      _Language_validate_assert_only_one in language.o
      _PythonLanguage_validate_assert_only_one_local_fail in language.o
      _PythonLanguage_validate_assert_only_one_local_fail in language.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.97s
