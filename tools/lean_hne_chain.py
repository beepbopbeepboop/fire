#!/usr/bin/env python3
"""Generator for hne_ negation chains in arm64_step lemmas."""
import argparse
import re
import sys


RET_WORD = 0xd65f03c0


class UnparsedArmError(Exception):
    def __init__(self, line_num=None, line=None):
        self.line_num = line_num
        self.line = line
        msg = f"-- UNPARSED arm at line {line_num}: {line.strip()}" if line_num is not None and line is not None else "Unparsed arm"
        super().__init__(msg)


def find_arm64_step_chain(content):
    start = content.find('def arm64_step')
    if start == -1:
        raise ValueError("Could not find def arm64_step")
    end = content.find('\ndef arm64_steps', start)
    if end == -1:
        end = len(content)
    return content[start:end]


def find_arm64_step_range(source):
    return find_arm64_step_chain(source)


def parse_arm64_step_chain(content):
    chain = find_arm64_step_chain(content)
    arms = parse_arms(chain)
    for arm in arms:
        if isinstance(arm, dict) and (arm.get('unparsed') or arm.get('type') in ('unparsed', 'compound')):
            raise UnparsedArmError(arm.get('idx') or arm.get('line'), arm.get('raw') or arm.get('cond'))
    return arms


def parse_arms(chain_source):
    arms = []
    pattern = re.compile(r'^  (else\s+)?if\s+', re.M)
    matches = list(pattern.finditer(chain_source))
    for idx, m in enumerate(matches):
        then_match = re.search(r'\bthen\b', chain_source[m.end():])
        if not then_match:
            arms.append({
                'idx': idx,
                'cond': None,
                'unparsed': True,
                'raw': chain_source[m.start():m.start() + 200],
                'type': 'unparsed',
                'line': idx
            })
            continue
        cond = chain_source[m.end():m.end() + then_match.start()].strip()
        arm = parse_condition(cond, 0, chain_source[m.start():m.end() + then_match.end()])
        if arm is None:
            arms.append({
                'idx': idx,
                'cond': cond,
                'unparsed': True,
                'raw': chain_source[m.start():m.end() + then_match.end()],
                'type': 'compound',
                'line': idx
            })
        else:
            arm['idx'] = idx
            arm['cond'] = cond
            arm['unparsed'] = False
            arm['raw'] = chain_source[m.start():m.end() + then_match.end()]
            arms.append(arm)
    return arms


def parse_condition(cond_text, line_num=0, full_line=''):
    cond_text = cond_text.strip()
    
    m_eq = re.match(r'^insn\s*=\s*(0x[0-9a-fA-F]+|\d+)$', cond_text)
    if m_eq:
        val = parse_int(m_eq.group(1))
        return {
            'type': 'eq',
            'value': val,
            'mask': None,
            'line': line_num,
            'raw': full_line.strip() if full_line else cond_text
        }
    
    m_mask = re.match(r'^\(insn\s*&&&\s*(0x[0-9a-fA-F]+|\d+)\)\s*=\s*(0x[0-9a-fA-F]+|\d+)$', cond_text)
    if m_mask:
        mask = parse_int(m_mask.group(1))
        value = parse_int(m_mask.group(2))
        return {
            'type': 'mask',
            'mask': mask,
            'value': value,
            'line': line_num,
            'raw': full_line.strip() if full_line else cond_text
        }
    
    return None


def parse_int(s):
    s = str(s).strip()
    if s.startswith('0x') or s.startswith('0X'):
        return int(s, 16)
    return int(s)


def fmt_hex(x):
    if isinstance(x, str):
        x_clean = x.strip().lower()
        if x_clean.startswith('0x'):
            x_clean = x_clean[2:]
        try:
            # try to parse
            x = int(x_clean, 16)
        except Exception:
            return x.strip()
    if isinstance(x, int) and x < 0:
        x = x & ((1 << 64) - 1)
    if isinstance(x, int):
        s = hex(x)[2:].lower()
        return f'0x{s}'
    return str(x)


def is_ret_arm(arm):
    if isinstance(arm, dict):
        if arm.get('unparsed'):
            return False
        if arm.get('type') == 'eq' and arm.get('value') == RET_WORD:
            return True
        cond = arm.get('cond', '')
        if cond and re.search(r'insn\s*=\s*0x[dD]65f03c0', str(cond)):
            return True
    return False


def classify_arm(arm):
    if isinstance(arm, dict):
        if arm.get('unparsed') or arm.get('type') in ('unparsed', 'compound'):
            return 'compound'
        if arm.get('type') == 'eq':
            return 'eq'
        if arm.get('type') == 'mask':
            cond = arm.get('cond', '')
            if re.match(r'^\(insn\s*&&&\s*0x[0-9a-fA-F]+\)\s*=\s*0x[0-9a-fA-F]+\s*$', str(cond)):
                return 'simple'
        cond = arm.get('cond', '')
        if cond and re.match(r'^\(insn\s*&&&\s*0x[0-9a-fA-F]+\)\s*=\s*0x[0-9a-fA-F]+\s*$', str(cond)):
            return 'simple'
    return 'compound'


def extract_mask_value(arm):
    if isinstance(arm, dict):
        if arm.get('unparsed'):
            return None, None
        if arm.get('type') == 'mask':
            return fmt_hex(arm['mask']), fmt_hex(arm['value'])
        cond = arm.get('cond', '')
        if cond:
            m = re.match(r'^\(insn\s*&&&\s*(0x[0-9a-fA-F]+)\)\s*=\s*(0x[0-9a-fA-F]+)\s*$', str(cond))
            if m:
                return m.group(1), m.group(2)
    return None, None


def generate_hne_chain(arms, target_mask, target_value=None):
    target_mask_clean = fmt_hex(target_mask).lower()
    if target_value is not None:
        target_value_clean = fmt_hex(target_value).lower()
    else:
        raise ValueError("need target value")
    
    target_idx = -1
    for i, arm in enumerate(arms):
        if isinstance(arm, dict):
            if arm.get('unparsed') or arm.get('type') in ('unparsed', 'compound'):
                continue
            if arm.get('type') == 'mask':
                if fmt_hex(arm['mask']).lower() == target_mask_clean and fmt_hex(arm['value']).lower() == target_value_clean:
                    target_idx = i
                    break
    
    if target_idx == -1:
        raise ValueError(f"Target arm not found: {target_mask} = {target_value}")
    
    hne_lines = []
    rw_parts = []
    
    for i in range(target_idx):
        arm = arms[i]
        if isinstance(arm, dict):
            if arm.get('unparsed') or arm.get('type') in ('unparsed', 'compound'):
                msg = f"-- UNPARSED arm at line {arm.get('idx', arm.get('line', i))}: {arm.get('cond') or str(arm.get('raw',''))[:80]}"
                print(msg, file=sys.stderr)
                sys.exit(2)
            if is_ret_arm(arm):
                hne_lines.append(f"  have hne_ret : w ≠ ({fmt_hex(arm.get('value', RET_WORD))} : UInt32) := by")
                hne_lines.append(f"    intro t")
                hne_lines.append(f"    rw [t] at h")
                hne_lines.append(f"    exact absurd h (by decide)")
                rw_parts.append('if_neg hne_ret')
                continue
            if arm.get('type') == 'mask':
                mask_s = fmt_hex(arm['mask'])
                val_s = fmt_hex(arm['value'])
                name = f'hne_{i}'
                hne_lines.append(f"  have {name} : ¬ ((w &&& {mask_s}) = ({val_s} : UInt32)) := by intro t; bv_decide")
                rw_parts.append(f'if_neg {name}')
                continue
    
    hne_lines.append(f"  unfold arm64_step")
    hne_lines.append(f"  rw [hpc, hread]")
    rw_line = f"  rw [" + ", ".join(rw_parts) + f", if_pos h, if_neg hrd]"
    hne_lines.append(rw_line)
    return '\n'.join(hne_lines)


generate_chain = generate_hne_chain


def list_arms(arms):
    for i, arm in enumerate(arms):
        if isinstance(arm, dict):
            if arm.get('unparsed') or arm.get('type') in ('unparsed', 'compound'):
                print(f"{i}: UNPARSED - {arm.get('cond') or str(arm.get('raw',''))[:60]}")
                continue
            if is_ret_arm(arm):
                print(f"{i}: eq insn = {fmt_hex(arm.get('value', RET_WORD))} (line {arm.get('line', arm.get('idx',''))})")
                continue
            if arm.get('type') == 'mask':
                print(f"{i}: (insn &&& {fmt_hex(arm['mask'])}) = {fmt_hex(arm['value'])} (line {arm.get('line', arm.get('idx',''))})")
                continue
            print(f"{i}: {arm}")
        else:
            print(f"{i}: {arm}")


def main():
    parser = argparse.ArgumentParser(description='Generate hne chain for arm64_step')
    parser.add_argument('--mask', type=str, help='Target mask')
    parser.add_argument('--value', type=str, help='Target value')
    parser.add_argument('--list', action='store_true', help='List all arms')
    parser.add_argument('--file', type=str, help='ProofLib file to parse')
    parser.add_argument('--prooflib', type=str, help='Path to ProofLib.lean')
    args = parser.parse_args()
    
    filepath = args.file if args.file else (args.prooflib if args.prooflib else 'lib/ProofLib.lean')
    try:
        with open(filepath) as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        sys.exit(1)
    
    try:
        arms = parse_arm64_step_chain(content)
    except UnparsedArmError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error parsing: {e}", file=sys.stderr)
        sys.exit(1)
    
    if args.list:
        list_arms(arms)
        return
    
    if args.mask is None or args.value is None:
        parser.print_help()
        sys.exit(1)
    
    try:
        target_mask = parse_int(args.mask)
        target_value = parse_int(args.value)
        result = generate_hne_chain(arms, target_mask, target_value)
        if result is None:
            sys.exit(1)
        print(result)
    except UnparsedArmError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
