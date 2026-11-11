#!/usr/bin/env python3
"""Reject an accidental AVX-512 requirement in the AVX2/VEX-VNNI backends."""
import json
import re
import subprocess
import sys
from pathlib import Path


def inspect_disassembly(output, path):
    """Inspect the opcode after optional prefixes inserted by GNU branch padding."""
    vnni = 0
    prefixes = {0xf0, 0xf2, 0xf3, 0x2e, 0x36, 0x3e, 0x26, 0x64, 0x65, 0x66, 0x67}
    for line in output.splitlines():
        match = re.match(r'^\s*[0-9a-f]+:\s+((?:[0-9a-f]{2}\s+)+)(.*)$', line)
        if not match:
            continue
        encoding = [int(value, 16) for value in match[1].split()]
        index = 0
        while index < len(encoding) and (encoding[index] in prefixes or 0x40 <= encoding[index] <= 0x4f):
            index += 1
        if index == len(encoding):
            continue
        # Prefix padding must not conceal an EVEX instruction from this gate.
        if encoding[index] == 0x62:
            raise SystemExit(f'Unexpected EVEX instruction in {path}: {line.strip()}')
        if re.search(r'\bvpdpbusd\b', match[2]):
            if encoding[index] != 0xc4:
                raise SystemExit(f'Expected VEX VPDPBUSD in {path}: {line.strip()}')
            vnni += 1
    return vnni


def main():
    if len(sys.argv) < 3:
        raise SystemExit('Usage: vnni_isa_contract.py objdump object...')
    vnni = 0
    for name in sys.argv[2:]:
        path = Path(name)
        output = subprocess.check_output([sys.argv[1], '-d', '-w', '--', str(path)], text=True)
        vnni += inspect_disassembly(output, path)
    if not vnni:
        raise SystemExit('No VEX VPDPBUSD instructions were inspected')
    print(json.dumps({'objects': len(sys.argv) - 2, 'vex_dot_sites': vnni,
                      'evex_instructions': 0, 'avx512_not_required': True}))


if __name__ == '__main__':
    main()
