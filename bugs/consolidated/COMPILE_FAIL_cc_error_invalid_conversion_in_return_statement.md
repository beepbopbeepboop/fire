# COMPILE_FAIL: CC ERROR: invalid conversion in return statement

**2 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py: In function '_alloc_AddressList':
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:58:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   58 |     """Convert date to extended time tuple.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py: In function 'parsedate_tz_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:336:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  336 |         This method just skips all the route stuff and returns the addrspec.
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py: In function '_parsedate_tz_79c856':
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:439:10: warning: variable '_t368' set but not used [-Wunused-but-set-variable]
  439 |         if self.field[self.pos] != beginchar:
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:428:10: warning: unused variable '_t357' [-Wunused-variable]
  428 | 
      |          ^    
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:377:10: warning: unused variable '_t309' [-Wunused-variable]
  377 |                 preserve_ws = False
      |          ^    
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:352:10: warning: variable '_t284' set but not used [-Wunused-but-set-variable]
  352 |             elif self.field[self.pos] == '@':
      |          ^  ~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:344:10: warning: variable '_t276' set but not used [-Wunused-but-set-variable]
  344 |         adlist = ''
      |          ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:339:10: warning: variable '_t271' set but not used [-Wunused-but-set-variable]
  339 |             return
      |          ^  ~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:316:10: warning: variable '_t249' set but not used [-Wunused-but-set-variable]
  316 |             if self.commentlist:
      |          ^  ~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:308:7: warning: variable '_t241' set but not used [-Wunused-but-set-variable]
  308 |                     self.pos += 1
      |       ^    
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:275:7: warning: variable '_t209' set but not used [-Wunused-but-set-variable]
  275 |         """Parse the next address."""
      |       ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:255:10: warning: variable '_t191' set but not used [-Wunused-but-set-variable]
  255 |                 self.commentlist.append(self.getcomment())
      |          ^    
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:247:7: warning: variable '_t183' set but not used [-Wunused-but-set-variable]
  247 |         """Skip white space and extract comments."""
      |       ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:178:7: warning: variable '_t116' set but not used [-Wunused-but-set-variable]
  178 |         tzoffset = tzsign * ( (tzoffset//100)*3600 + (tzoffset % 100)*60)
      |       ^ ~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:167:11: warning: variable '_t105' set but not used [-Wunused-but-set-variable]
  167 |         except ValueError:
      |           ^~~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:161:10: warning: variable '_t99' set but not used [-Wunused-but-set-variable]
  161 |     tz = tz.upper()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:152:10: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
  152 |     # the time module.
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:129:10: warning: variable '_t69' set but not used [-Wunused-but-set-variable]
  129 |         tm = tm[0].split('.')
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/email/_parseaddr.py:106:11: warning: variable '_t47' set but not used [-Wunuse
```

## Affected files

- `Lib/email/_parseaddr.py`
- `Tools/peg_generator/pegen/sccutils.py`
