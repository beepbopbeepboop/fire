# COMPILE_FAIL: Tools/clinic/libclinic/block_parser.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py: In function '_alloc_Block':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:70:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   70 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py: In function 'Block___repr___summarize':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:268:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py: In function 'Block___repr__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:108:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  108 |         self.block_start_line_number = self.line_number = 0
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py: In function 'BlockParser___init__':
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:113:1: warning: label 'bb_3' defined but not used [-Wunused-label]
  113 |         self.find_start_re = libclinic.create_regex(before, after,
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:113:1: warning: label 'bb_4' defined but not used [-Wunused-label]
  113 |         self.find_start_re = libclinic.create_regex(before, after,
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:142:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  142 |                 continue
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:140:9: warning: variable '_t50' set but not used [-Wunused-but-set-variable]
  140 |             block = self.parse_verbatim_block()
      |         ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:139:11: warning: variable '_t49' set but not used [-Wunused-but-set-variable]
  139 |                 return return_value
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:138:11: warning: variable '_t48' set but not used [-Wunused-but-set-variable]
  138 |                 self.first_block = False
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:137:11: warning: variable '_t47' set but not used [-Wunused-but-set-variable]
  137 |                 self.dsl_name = None
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:136:7: warning: variable '_t46' set but not used [-Wunused-but-set-variable]
  136 |                     raise
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:135:7: warning: variable '_t45' set but not used [-Wunused-but-set-variable]
  135 |                     exc.lineno = self.line_number
      |       ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:134:11: warning: variable '_t44' set but not used [-Wunused-but-set-variable]
  134 |                     exc.filename = self.language.filename
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:133:11: warning: variable '_t43' set but not used [-Wunused-but-set-variable]
  133 |                 except ClinicError as exc:
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:132:11: warning: variable '_t42' set but not used [-Wunused-but-set-variable]
  132 |                     return_value = self.parse_clinic_block(self.dsl_name)
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/clinic/libclinic/block_parser.py:131:7: warning: variable '_t41' set but not used [-Wunused-but-set-variable]
  131 |                 try:
... (395 more lines)
```

Exit code: 1
Elapsed: 13.98s
