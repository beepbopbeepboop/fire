# COMPILE_FAIL: CC ERROR: assignment to 'X' {aka 'X'} from 'X' makes integer from pointer without a cast [-Wint-conversion]

**10 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 |         return range(len(self.object))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:87:11: warning: unused variable '_tag' [-Wunused-variable]
   87 |                 value = self.object[key]
      |           ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:92:11: warning: unused variable '_tag' [-Wunused-variable]
   92 |             item = make_objecttreeitem(f"{key!r}:", value, setfunction)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:107:11: warning: unused variable '_tag' [-Wunused-variable]
  107 |     int: AtomicObjectTreeItem,
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:116:13: warning: unused variable '_tag' [-Wunused-variable]
  116 | def make_objecttreeitem(labeltext, object_, setfunction=None):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem___init__':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:263:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:261:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:260:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:259:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem_GetLabelText':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:32:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   32 |             return "python"
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:30:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   30 |     def GetIconName(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem_GetText':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:36:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   36 |         try:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:34:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   34 |         return self.setfunction is not None
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:33:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   33 |     def IsEditable(self):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:32:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   32 |             return "python"
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem_GetIconName':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:39:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   39 |         except:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py: In function 'ObjectTreeItem_IsEditable':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:45:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   45 |     def GetSubList(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/debugobj.py:43:11: warning: variable '_t4' set but not use
```

## Affected files

- `Lib/idlelib/debugobj.py`
- `Lib/idlelib/statusbar.py`
- `Lib/re/_compiler.py`
- `Lib/sysconfig/__init__.py`
- `Lib/test/subprocessdata/fd_status.py`
- `Lib/test/support/hashlib_helper.py`
- `Lib/test/support/os_helper.py`
- `Lib/turtledemo/clock.py`
- `PC/layout/main.py`
- `Tools/peg_generator/pegen/c_generator.py`
