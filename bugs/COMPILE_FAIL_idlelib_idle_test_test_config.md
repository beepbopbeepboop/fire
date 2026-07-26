# COMPILE_FAIL: Lib/idlelib/idle_test/test_config.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py: In function '_mojo_dispatch_getattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:188:11: warning: unused variable '_tag' [-Wunused-variable]
  188 |         if __name__ != '__main__':
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py: In function '_mojo_dispatch_setattr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:193:11: warning: unused variable '_tag' [-Wunused-variable]
  193 |             config_path = os.path.join(idle_dir, '../config-%s.def' % ctype)
      |           ^ ~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py: In function '_mojo_dispatch_fields':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:198:11: warning: unused variable '_tag' [-Wunused-variable]
  198 |         config._warn = Func()
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py: In function '_mojo_dispatch_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:213:11: warning: unused variable '_tag' [-Wunused-variable]
  213 |         for ctype in conf.config_types:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py: In function '_mojo_generic_elem_repr':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:222:13: warning: unused variable '_tag' [-Wunused-variable]
  222 |     def test_get_user_cfg_dir_unix(self):
      |             ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py: In function 'IdleConfParserTest_test_get':
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:133:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  133 |         # Configparser raises DuplicateError, IdleParser not.
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:131:10: warning: variable '_t90' set but not used [-Wunused-but-set-variable]
  131 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:130:11: warning: variable '_t89' set but not used [-Wunused-but-set-variable]
  130 |         self.assertEqual(parser.sections(), [])
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:129:10: warning: variable '_t88' set but not used [-Wunused-but-set-variable]
  129 |         parser = self.new_parser()
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:128:11: warning: variable '_t87' set but not used [-Wunused-but-set-variable]
  128 |     def test_add_section(self):
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:127:10: warning: variable '_t86' set but not used [-Wunused-but-set-variable]
  127 | 
      |          ^   
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:126:11: warning: variable '_t85' set but not used [-Wunused-but-set-variable]
  126 |         self.assertFalse(parser.RemoveOption('Not', 'Exist'))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:125:10: warning: variable '_t84' set but not used [-Wunused-but-set-variable]
  125 |         self.assertFalse(parser.RemoveOption('Foo', 'bar'))
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:124:11: warning: variable '_t83' set but not used [-Wunused-but-set-variable]
  124 |         self.assertTrue(parser.RemoveOption('Foo', 'bar'))
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Lib/idlelib/idle_test/test_config.py:123:11: warning: variable '_t82' set but not used [-Wunused-but-set-variable]
... (7841 more lines)
```

Exit code: 1
Elapsed: 12.62s
