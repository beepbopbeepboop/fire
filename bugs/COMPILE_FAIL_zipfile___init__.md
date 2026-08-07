# COMPILE_FAIL: Lib/zipfile/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-06)

Re-ran; current errors:

```
error: non-trivial conversion in 'integer_cst'   (x2, near line 567)
error: mismatching comparison operand types       (near line 625)
error: non-trivial conversion in 'var_decl'        (x2, near line 1290)
error: passing argument 3 of 'ZipFile_mojo_open' makes integer from pointer without a cast [-Wint-conversion]  (line 1690)
```

Most of the reported source line numbers (567, 625, 1290) point at
blank lines or docstrings, not executable code — the same line-number
misattribution pattern seen in several other files this session
(`bugs/COMPILE_FAIL_importlib_util.md`'s LazyModule case,
`bugs/COMPILE_FAIL_Tools_unicode_gencodec.md`) where generated code
continues past the last real `#line` directive without resetting it,
so GCC blames the wrong physical line. Not root-caused further given
time constraints.

The one cleanly-attributed error, line 1690's `with self.open(name,
"r", pwd) as fp:` (`ZipFile.read`/similar — `pwd` is an optional
`bytes | None = None` parameter), suggests a `None`-default optional
parameter not getting the right boxed type at a call site expecting a
real `char *`/bytes value — not confirmed further. None fixed here.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc_LZMACompressor':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:459:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  459 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc_LZMADecompressor':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:473:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  473 |         self.create_version = DEFAULT_VERSION  # Version which created ZIP archive
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc_ZipExtFile':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:487:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  487 |     # Maintain backward compatibility with the old protected attribute name.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc_ZipFile':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:501:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  501 |                                                self.compress_type))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc_ZipInfo':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:515:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  515 |         result.append('>')
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc__SharedFile':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:529:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  529 |             # Set these to zero because we write them after the file data
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc__Tellable':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:543:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  543 |         if zip64:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_alloc__ZipWriteFile':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:557:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  557 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_Extra___new__':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:1587:1: warning: label 'bb_2' defined but not used [-Wunused-label]
 1587 |             (x.create_version, x.create_system, x.extract_version, x.reserved,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:1585:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
 1585 |             x.comment = fp.read(centdir[_CD_COMMENT_LENGTH])
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_Extra___init__':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:210:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  210 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:208:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  208 |     @classmethod
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py: In function '_Extra_read_one':
/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py:255:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  255 |     """Quickly see if a file is a ZIP file by checking the magic number.
... (20667 more lines)
```

Exit code: 1
Elapsed: 14.07s
