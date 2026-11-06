#!/usr/bin/env python3
"""Raw reads in fours (dmsh_wide.raw_fours): through the offline translator (dmsh_xlate, arch sm86), a compute shader's 128-bit load from an address it
cannot trace (four words at +0, +4, +8 and +12) become one dm_raw4 on the helper's three ulong words, and a store between them leaves them single; on this Mac's GPU dm_raw reads what the
translator's helper reads, and dm_raw4 what four dm_raw reads do, over test_dmsh_raw_last.py's pool table and address walk with two runs that cross a pool's end and
runs whose four addresses are not each 4 past the one before. Needs DMSH_TEST_XLATE (the translator) like the other translator tests."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dmsh_ampere_mem import EXIT, Translated, ctrl, inst   # noqa: E402
import test_dmsh_ampere_mem   # noqa: E402  (RawGlobal by its module, so this file does not run its tests)
from test_dmsh_raw_last import MAC_METAL, RUNNER   # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dmsh_wide   # noqa: E402


# RawGlobal's shader (test_dmsh_ampere_mem.py): an address loaded from storage slot 0, then reads at that address, which no storage buffer holds, and stores of
# what they read back to slot 0. The size field (bits 9-11 of the high word) as in RawGlobal's LDG.E (4: 32 bits) and LDG.E.64 (5); 6 is LDG.E.128
def ldg(rd, offset, size, wait=0b100): return (ctrl(wb=3, wait=wait) | 0x1e0100 | size << 9, 0x0000000004007381 | rd << 16 | offset << 40)   # LDG.E Rd, [R4.64 + offset]
def stg(rs, offset): return (ctrl(wait=0b1000, stall=4) | 0x900, 0x0000000002007386 | rs << 32 | offset << 40)   # STG.E [R2.64 + offset], Rs


@unittest.skipUnless(os.environ.get('DMSH_TEST_XLATE'), 'set DMSH_TEST_XLATE to the offline translator')
class RawFours(Translated):
    def msl(self, code):
        head = tuple(getattr(test_dmsh_ampere_mem.RawGlobal, k) for k in ("ULDC", "ADDR_LO", "ADDR_HI", "LDG_PTR"))
        return self.translate(b''.join(inst(*c) for c in head + code) + inst(*EXIT), nvn2_cs=[3, 1, 0, 0x50, 0])

    FOUR = (ldg(8, 0, 6),) + tuple(stg(8 + k, 8 + 4 * k) for k in range(4))   # LDG.E.128 R8, [R4.64], then R8..R11 to slot 0 words 2..5

    def test_four_adjacent_loads_read_once(self):
        src = self.msl(self.FOUR)
        out, reads, runs = dmsh_wide.raw_fours(src)
        self.assertEqual((reads, runs), (4, 1), out[-3000:])
        self.assertEqual(out.count('dm_raw4(_'), 1)
        self.assertIn('ulong dm_s = 0, dm_n = 0, dm_d = 0;', out)
        self.assertNotRegex(out, r'thread uint& _\d+')   # the seven words are gone with the helper

    def test_a_store_between_ends_a_run(self):   # the 128-bit load's four reads with a store to storage slot 0 after the second: the later words must be read after it
        src = self.msl(self.FOUR)
        second = [m.end() for m in re.finditer(r'(?m)^ +int _\d+ = _\d+\(_\d+, _\d+, \(\*spvDescriptorSet0\.\w+\)(?:, _\d+){7}\);$', src)][1]
        src = src[:second] + '\n    (*spvDescriptorSet0.cp_s0)._m0[6] = 0u;' + src[second:]
        out, reads, runs = dmsh_wide.raw_fours(src)
        self.assertEqual((reads, runs), (4, 0), out[-3000:])
        self.assertEqual(len(re.findall(r'= dm_raw\(_', out)), 4)

    @unittest.skipUnless(shutil.which('xcrun') and sys.platform == 'darwin', 'needs Metal')
    def test_reads_on_gpu(self):
        src = self.msl(self.FOUR)
        old = re.search(r'(?m)^int (_\d+)\(thread const int& _\d+, thread const int& _\d+, ((?:const )?device) (_\d+)& \w+((?:, thread uint& _\d+)+)\)\n', src)
        new = dmsh_wide.raw_fours(src)[0]
        # the translator's helper and the rewrite's, side by side: each step reads its address through the old helper (its own words), through dm_raw (its own
        # words), and four words through dm_raw4, at a, a+4, a+8, a+12 on even steps and a, a+4, a+20, a+12 on odd ones; the step's word goes out when all agree
        both = (new[:new.index('kernel void main0')] + src[old.start():src.index('\n}\n', old.start()) + 3])
        words = len(re.findall(r'thread uint&', old.group(4)))
        kernel = both + f'''
kernel void k({old.group(2)} {old.group(3)}& map [[buffer(0)]], const device uint2* addr [[buffer(1)]], device int* out [[buffer(2)]], uint id [[thread_position_in_grid]])
{{
    uint c[{words}] = {{}};
    ulong s = 0, n = 0, d = 0, s2 = 0, n2 = 0, d2 = 0;
    for (int st = 0; st < 16; st++)
    {{
        uint2 x = addr[id * 16 + st]; ulong a = as_type<ulong>(x);
        int was = {old.group(1)}(int(x.x), int(x.y), map, {", ".join(f"c[{k}]" for k in range(words))});
        int now = dm_raw(int(x.x), int(x.y), map, s2, n2, d2);
        ulong b[4] = {{a, a + 4, a + ((st & 1) ? 20 : 8), a + 12}};
        uint4 v = dm_raw4(int(uint(b[0])), int(uint(b[0] >> 32)), int(uint(b[1])), int(uint(b[1] >> 32)), int(uint(b[2])), int(uint(b[2] >> 32)), int(uint(b[3])), int(uint(b[3] >> 32)), map, s, n, d);
        bool same = was == now && int(v.x) == now;
        for (int k = 1; k < 4; k++) same = same && v[k] == uint(dm_raw(int(uint(b[k])), int(uint(b[k] >> 32)), map, s2, n2, d2));
        out[id * 16 + st] = same ? now : 0x7fffffff;
    }}
}}
'''
        steps = '{0, 16}, {0, 20}}'
        self.assertIn(steps, RUNNER)
        runner = RUNNER.replace(steps, '{-1, 0x10000ff8}, {-1, 0x200040ff8}}')   # A's last two words and B's first two; C's last two and the gap after it
        with tempfile.TemporaryDirectory() as w:
            w = Path(w)
            (w / 'k.metal').write_text(kernel)
            r = subprocess.run(MAC_METAL + [str(w / 'k.metal'), '-o', str(w / 'k.air')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-3000:])
            subprocess.run(['xcrun', '-sdk', 'macosx', 'metallib', str(w / 'k.air'), '-o', str(w / 'k.metallib')], check=True)
            (w / 'r.m').write_text(runner)
            subprocess.run(['clang', '-fobjc-arc', '-framework', 'Metal', '-framework', 'Foundation', str(w / 'r.m'), '-o', str(w / 'r')], check=True, capture_output=True)
            out = subprocess.run([str(w / 'r'), str(w / 'k.metallib')], capture_output=True, text=True)
            self.assertIn('bad 0 of 1024', out.stdout, out.stdout + out.stderr)


if __name__ == '__main__':
    unittest.main()
