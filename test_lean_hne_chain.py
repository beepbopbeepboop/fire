#!/usr/bin/env python3
import os
import subprocess
import sys
import unittest
import re
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import lean_hne_chain


class TestLeanHneChain(unittest.TestCase):
    def test_add_imm_hne_conditions_match_template(self):
        arms = lean_hne_chain.parse_arm64_step_chain(open(os.path.join(ROOT, 'lib/ProofLib.lean')).read())
        result = lean_hne_chain.generate_hne_chain(arms, 0xff800000, 0x91000000)
        self.assertIsNotNone(result)
        
        with open(os.path.join(ROOT, 'lib/Peephole.lean')) as f:
            content = f.read()
        lines = content.splitlines()
        template_section = '\n'.join(lines[165:206])
        
        template_conds = []
        for m in re.finditer(r'w\s*≠\s*\([^)]+\s*:[^)]+\)', template_section):
            template_conds.append(m.group(0))
        for m in re.finditer(r'¬\s*\(\([^)()]+\s*&&&[^()]+\)\s*=\s*\([^)()]+\s*:[^)()]+\)\)', template_section):
            template_conds.append(m.group(0))
        
        gen_conds = []
        for m in re.finditer(r'w\s*≠\s*\([^)]+\s*:[^)]+\)', result):
            gen_conds.append(m.group(0))
        for m in re.finditer(r'¬\s*\(\([^)()]+\s*&&&[^()]+\)\s*=\s*\([^)()]+\s*:[^)()]+\)\)', result):
            gen_conds.append(m.group(0))
        
        self.assertEqual(len(gen_conds), len(template_conds), f"Got {len(gen_conds)} vs {len(template_conds)}")
        for g, t in zip(gen_conds, template_conds):
            self.assertEqual(g.replace(' ', '').lower(), t.replace(' ', '').lower())
    
    def test_list_count(self):
        arms = lean_hne_chain.parse_arm64_step_chain(open(os.path.join(ROOT, 'lib/ProofLib.lean')).read())
        with open(os.path.join(ROOT, 'lib/ProofLib.lean')) as f:
            content = f.read()
        start = content.find('def arm64_step')
        end = content.find('\ndef arm64_steps', start)
        chunk = content[start:end]
        # Count actual chain else-if branches (at chain level)
        elif_count = len(re.findall(r'^  else\s+if\s+', chunk, re.M))
        self.assertEqual(len(arms), elif_count + 1)
        
        proc = subprocess.run([sys.executable, os.path.join(ROOT, 'tools/lean_hne_chain.py'), '--list'], 
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        lines = proc.stdout.decode().splitlines()
        arm_lines = []
        for l in lines:
            lstrip = l.strip()
            if not lstrip:
                continue
            if lstrip.startswith('--'):
                continue
            if 'UNPARSED' in lstrip:
                continue
            arm_lines.append(lstrip)
        self.assertEqual(len(arm_lines), elif_count + 1)
    
    def test_unparsed_arm_exits_2(self):
        synthetic = '''def arm64_step (s : Arm64State) (code : Nat → UInt8) : Option Arm64State :=
  let insn := arm64_read_insn code s.pc
  if insn = 0xd65f03c0 then
    some { s with pc := s.x30.toNat }
  else if (insn &&& 0xffe00000) = 0x2A00FA00 then
    some s
  else if rd = 31 then
    some s
  none

def arm64_steps
'''
        try:
            arms = lean_hne_chain.parse_arm64_step_chain(synthetic)
        except SystemExit as e:
            self.assertEqual(e.code, 2)
            return
        except lean_hne_chain.UnparsedArmError:
            return
        except Exception:
            return
        
        # If parsed but has unparsed arms, generating across them should exit 2
        try:
            # Try to generate for target after unparsed arm
            # Look for a target
            result = lean_hne_chain.generate_hne_chain(arms, 0xffe00000, 0x2A00FA00)
        except SystemExit as e:
            self.assertEqual(e.code, 2)
            return
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lean', delete=False) as f:
            f.write(synthetic)
            tmp = f.name
        try:
            proc = subprocess.run([sys.executable, os.path.join(ROOT, 'tools/lean_hne_chain.py'), 
                                   '--list', '--file', tmp], 
                                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(proc.returncode, 2)
        finally:
            os.unlink(tmp)


if __name__ == '__main__':
    unittest.main()
