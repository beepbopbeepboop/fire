#!/usr/bin/env python3
"""Regression pin for CODEGEN_rebound_container_param_is_the_box_red_on_master.

A parameter the body rebinds to a container of another kind is the box
(int64_t), not the first container guess. Same-kind rebinds stay the
original container pointer.
"""
import sys, os
sys.path.insert(0, '.')
import test_gimple

if __name__ == '__main__':
    test_gimple.test_rebound_container_param_is_the_box()
