# COMPILE_FAIL: Lib/zipfile/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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
