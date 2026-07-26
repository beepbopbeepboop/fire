# COMPILE_FAIL: Tools/peg_generator/pegen/python_generator.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/peg_generator/pegen/python_generator.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

```
Linking failed: Undefined symbols for architecture arm64:
  "_PythonCallMakerVisitor_visit_Gather_lambda_7", referenced from:
      _PythonCallMakerVisitor_visit_Gather in python_generator.o
  "_PythonCallMakerVisitor_visit_Gather_lambda_8", referenced from:
      _PythonCallMakerVisitor_visit_Gather in python_generator.o
  "_PythonCallMakerVisitor_visit_Repeat0_lambda_3", referenced from:
      _PythonCallMakerVisitor_visit_Repeat0 in python_generator.o
  "_PythonCallMakerVisitor_visit_Repeat0_lambda_4", referenced from:
      _PythonCallMakerVisitor_visit_Repeat0 in python_generator.o
  "_PythonCallMakerVisitor_visit_Repeat1_lambda_5", referenced from:
      _PythonCallMakerVisitor_visit_Repeat1 in python_generator.o
  "_PythonCallMakerVisitor_visit_Repeat1_lambda_6", referenced from:
      _PythonCallMakerVisitor_visit_Repeat1 in python_generator.o
  "_PythonCallMakerVisitor_visit_Rhs_lambda_1", referenced from:
      _PythonCallMakerVisitor_visit_Rhs in python_generator.o
  "_PythonCallMakerVisitor_visit_Rhs_lambda_2", referenced from:
      _PythonCallMakerVisitor_visit_Rhs in python_generator.o
ld: symbol(s) not found for architecture arm64
collect2: error: ld returned 1 exit status

```

Exit code: 1
Elapsed: 16.80s
