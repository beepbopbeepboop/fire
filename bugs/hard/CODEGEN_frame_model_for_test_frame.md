# Frame introspection for test_frame.py: research for Sonnet 5.5

Owner direction (2026-10-30): maximal compatibility with Python; eventually fix all bugs. The owner has latitude on how to frame the model, but compiled code must coexist with the C API (external calls such as fopen and write) and its usual limits. Research and ANSWER, do not start a fix.

## The question
Does the compiler get a frame model (option b) or keep test_frame.py refused (option a)?
The surface in question: sys._getframe, f_back, clear, f_generator, gi_frame, tb_frame.

## What to answer
1. What is the smallest frame model that makes these work for generators and ordinary functions, and what does it cost at run time?
2. Which of these can never be exact in compiled C (for example a live f_locals), and what limit should the owner accept?
3. Recommend (a) or (b) and give the first step.

Source context: frame model feature for test_frame.py (bug fixed: generator division-by-zero and method self-capture); not the frame-model feature itself.
