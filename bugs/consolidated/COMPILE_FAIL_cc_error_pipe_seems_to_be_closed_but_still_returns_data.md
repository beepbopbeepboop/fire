# COMPILE_FAIL: CC ERROR: pipe seems to be closed, but still returns data')

**1 files** affected in the Python-3.14.6 full source tree scan (2026-07-16).

## Example error (full stderr from one affected file)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:72:11: warning: unused variable '_tag' [-Wunused-variable]
   72 |             buf = os.read(rd, MSG_LEN)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:77:11: warning: unused variable '_tag' [-Wunused-variable]
   77 |             p.unregister( rd )
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:82:11: warning: unused variable '_tag' [-Wunused-variable]
   82 |     def test_poll_unit_tests(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:97:11: warning: unused variable '_tag' [-Wunused-variable]
   97 |             self.assertEqual(r[0][0], fd)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:106:13: warning: unused variable '_tag' [-Wunused-variable]
  106 | 
      |             ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py: In function 'PollTests_test_poll1':
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:81:1: warning: label 'bb_13' defined but not used [-Wunused-label]
   81 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:73:1: warning: label 'bb_12' defined but not used [-Wunused-label]
   73 |             self.assertEqual(len(buf), MSG_LEN)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:74:1: warning: label 'bb_11' defined but not used [-Wunused-label]
   74 |             bufs.append(buf)
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:66:1: warning: label 'bb_10' defined but not used [-Wunused-label]
   66 | 
      | ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:81:1: warning: label 'bb_9' defined but not used [-Wunused-label]
   81 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:66:1: warning: label 'bb_8' defined but not used [-Wunused-label]
   66 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:60:1: warning: label 'bb_7' defined but not used [-Wunused-label]
   60 |             ready = p.poll()
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:58:1: warning: label 'bb_5' defined but not used [-Wunused-label]
   58 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:63:1: warning: label 'bb_6' defined but not used [-Wunused-label]
   63 |                 raise RuntimeError("no pipes ready for writing")
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:55:1: warning: label 'bb_4' defined but not used [-Wunused-label]
   55 |             w2r[wr] = rd
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:51:1: warning: label 'bb_3' defined but not used [-Wunused-label]
   51 |             p.register(wr, select.POLLOUT)
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:156:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  156 |     def test_poll3(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:154:11: warning: variable '_t105' set but not used [-Wunused-but-set-variable]
  154 |                 self.fail('Unexpected return value from select.poll: %s' % fdlist)
      |           ^    
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:153:14: warning: variable '_t104' set but not used [-Wunused-but-set-variable]
  153 |             else:
      |              ^~~~ 
/Users/mrs/net/Python-3.14.6/Lib/test/test_poll.py:152:11: warning: variable '_t103' set but not used [-Wunused-but-set-variable]
  152 |                
```

## Affected files

- `Lib/test/test_poll.py`
