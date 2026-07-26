# COMPILE_FAIL: Lib/idlelib/search.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py: In function '_alloc_SearchDialog':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:42:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   42 |     instance to search again using the user entries and preferences
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py: In function '_setup_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:255:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py: In function 'find_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:39:11: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   39 |     """Repeat the search for the last pattern and preferences.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:37:11: warning: variable 'pat' set but not used [-Wunused-but-set-variable]
   37 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:35:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   35 |     pat = text.get("sel.first", "sel.last")
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:30:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   30 |     Module-level function to access the singleton SearchDialog
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py: In function 'find_again_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:43:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   43 |     from the last dialog.  If there was no prior search, open the
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:41:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   41 |     Module-level function to access the singleton SearchDialog
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py: In function 'find_selection_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:54:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   54 |     selection, perform the search without displaying the dialog.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:52:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   52 |     Module-level function to access the singleton SearchDialog
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py: In function 'SearchDialog_create_widgets':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 |         self.find_again(self.text)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:73:11: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   73 |         if not self.engine.getprog():
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:72:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   72 |         "Handle the Find Next button as the default command."
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:71:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   71 |     def default_command(self, event=None):
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/search.py:70:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   70 | 
      |           ^  
... (619 more lines)
```

Exit code: 1
Elapsed: 10.40s
