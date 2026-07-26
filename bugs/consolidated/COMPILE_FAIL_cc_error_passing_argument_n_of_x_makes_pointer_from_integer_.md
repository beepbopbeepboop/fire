# COMPILE_FAIL: CC ERROR: passing argument N of 'X' makes pointer from integer without a cast [-Wint-conversion]

**12 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py: In function '_alloc_ContentManager':
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:51:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   51 |                 return self.set_handlers[full_path]
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py: In function 'ContentManager___init__':
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:275:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:273:14: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:272:14: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:271:14: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:270:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py: In function 'ContentManager_add_get_handler':
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:22:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   22 |         if maintype in self.get_handlers:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:20:11: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   20 |             return self.get_handlers[content_type](msg, *args, **kw)
      |           ^ ~
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:19:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   19 |         if content_type in self.get_handlers:
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:18:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   18 |         content_type = msg.get_content_type()
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:17:14: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   17 |     def get_content(self, msg, *args, **kw):
      |              ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py: In function 'ContentManager_get_content':
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:28:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   28 |     def add_set_handler(self, typekey, handler):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:33:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   33 |             # XXX: is this error a good idea or not?  We can remove it later,
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:26:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   26 |         raise KeyError(content_type)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:28:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   28 |     def add_set_handler(self, typekey, handler):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:23:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   23 |             return self.get_handlers[maintype](msg, *args, **kw)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:25:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   25 |             return self.get_handlers[''](msg, *args, **kw)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:42:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   42 |         for typ in type(obj).__mro__:
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/contentmanager.py:40:11: warning: variable '_t19' set but not used [-Wunused-but-set-variable]
   40 |     def _find_set_handler(self, msg, obj):
      |           ^~~~
/Users/mrs/net/Pyth
```

## Affected files

- `Lib/email/contentmanager.py`
- `Lib/importlib/resources/abc.py`
- `Lib/importlib/resources/simple.py`
- `Lib/string/__init__.py`
- `Lib/test/libregrtest/refleak.py`
- `Lib/test/test_unicodedata.py`
- `Lib/test/test_zoneinfo/data/update_test_data.py`
- `Platforms/emscripten/__main__.py`
- `Tools/build/compute-changes.py`
- `Tools/build/smelly.py`
- `Tools/clinic/libclinic/formatting.py`
- `Tools/lockbench/lockbench.py`
