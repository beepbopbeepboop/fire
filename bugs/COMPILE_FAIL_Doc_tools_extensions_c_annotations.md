# COMPILE_FAIL: Doc/tools/extensions/c_annotations.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/extensions/c_annotations.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_sphinx_gettext", referenced from:
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      __stable_abi_annotation_a3d5f3 in c_annotations.o
      ...
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 10.52s
