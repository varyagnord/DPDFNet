"""Regression cases for padded VEX and concealed EVEX encodings."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('isa', Path(__file__).with_name('vnni_isa_contract.py'))
isa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isa)


class OpcodeContracts(unittest.TestCase):
    def test_plain_vex_dot(self):
        self.assertEqual(isa.inspect_disassembly(' 152: c4 e2 7d 50 08 vpdpbusd (%rax),%ymm0,%ymm1', 'plain'), 1)

    def test_actual_gnu_branch_padding(self):
        self.assertEqual(isa.inspect_disassembly(' 152: 2e 2e c4 e2 7d 50 08 cs cs {vex} vpdpbusd (%rax),%ymm0,%ymm1', 'padded'), 1)

    def test_plain_evex_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, 'Unexpected EVEX'):
            isa.inspect_disassembly(' 100: 62 f2 7d 28 50 08 vpdpbusd (%rax),%ymm0,%ymm1', 'evex')

    def test_prefixes_cannot_hide_evex(self):
        with self.assertRaisesRegex(SystemExit, 'Unexpected EVEX'):
            isa.inspect_disassembly(' 100: 2e 2e 62 f2 7d 28 50 08 cs cs vpdpbusd (%rax),%ymm0,%ymm1', 'padded-evex')

    def test_displacement_byte_is_not_opcode(self):
        self.assertEqual(isa.inspect_disassembly(' 100: 48 8b 40 62 mov 0x62(%rax),%rax', 'displacement'), 0)

    def test_dot_mnemonic_requires_vex_encoding(self):
        with self.assertRaisesRegex(SystemExit, 'Expected VEX'):
            isa.inspect_disassembly(' 100: 0f 38 50 08 vpdpbusd (%rax),%ymm0,%ymm1', 'bad-dot')


if __name__ == '__main__':
    unittest.main()
