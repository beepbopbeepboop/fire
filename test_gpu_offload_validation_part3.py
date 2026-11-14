"""Pinning regression for GPU offload validation modular part 3 disposition.

Both cases are BLOCKED on missing MAX-style GPU host runtime / device-passable
infrastructure:
- enqueue_function_device_passable_closure_arg_error.mojo
- enqueue_function_device_passable_closure_arg_layout_error.mojo

Required (not present in this tree): max.gpu.host.DeviceContext with
compile_function producing compiled-kernel metadata, enqueue_function argument
validation, DevicePassable/device_type/DeviceTypeEncoder device encoding/layout
support, and closure capture type/layout representation. The exact
contract/hooks/blocker were recorded in the now-deleted part 3 doc; this test
pins the disposition remains recorded in the parent triage.
"""

import pathlib
import unittest

PARENT = pathlib.Path(__file__).resolve().parent / "bugs/hard/GPU_offload_validation_modular.md"


class TestGPUOffloadValidationPart3(unittest.TestCase):
    def test_part3_cases_dispositioned_blocked(self):
        self.assertTrue(PARENT.exists(), PARENT)
        text = PARENT.read_text()
        # scope cases remain in parent triage
        self.assertIn("enqueue_function_device_passable_closure_arg_error.mojo", text)
        self.assertIn("enqueue_function_device_passable_closure_arg_layout_error.mojo", text)
        # disposition recorded: blocked on named runtime/device-passable hooks
        self.assertIn("part3 dispositioned", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("max.gpu.host", text)
        self.assertIn("DeviceContext", text)
        self.assertIn("compile_function", text)
        self.assertIn("DevicePassable", text)
        self.assertIn("device encoding/layout support", text)
        self.assertIn("test_gpu_offload_validation_part3.py", text)


if __name__ == "__main__":
    unittest.main()
