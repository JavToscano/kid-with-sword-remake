"""Storage-buffer reads the translator split into words, read whole again (wide_loads, a step of dmsh_build.py).

Ampere reads a storage buffer 64 or 128 bits at a time (LDG.E.64 / .128); the translator splits each into 32-bit LoadGlobal operations, and spirv-cross writes
every word with an address of its own:

    int _3487 = _3483 + 32;  uint _3499 = uint(int(uint(_3487) >> uint(2)));  float _3501 = as_type<float>((*spvDescriptorSet0.fp_s3)._m0[int(_3499)]);
    int _3503 = _3487 + 4;   uint _3505 = uint(int(uint(_3503) >> uint(2)));  float _3507 = as_type<float>((*spvDescriptorSet0.fp_s3)._m0[int(_3505)]);

Metal's front end cannot tell that such words are neighbours (each index is the shift of its own sum, then widened), so they stay separate loads, each with its
own address arithmetic. Splatoon Raiders' material shader (Hoian_UBER) reads its lights this way, 80 bytes a light in a loop over the lights, about 240 words in
all: on an M1 the scene's lit pass took 70 ms, 16 ms with the words read as below (median GPU time of the pass, the opening dialogue scene).

Here the words of one read-only buffer (const device) at byte offsets k, k+4, ... from one value, with no brace between them (one block of straight-line code),
become one read of a packed_uint2/3/4 at the first of them, and each word reads its lane. A packed vector needs only 4-byte alignment, so it may sit wherever
the words could; the shader does not write the buffer through its own binding, and a run ends at any line that may write memory or change a value (a store
through a subscript or a pointer, an atomic, a barrier, an image write, an assignment to an existing variable), so a write through another binding to the
same memory, or a common value that changes, cannot fall between its words: reading the later words earlier gives the same values. A run starts on a 16-byte
step of the common value and holds at most four words, as the original wide reads did; a run whose lowest word is not read first is left alone.
"""
import re

_IDENT = r'_[0-9A-Za-z_]+'
_BUF = r'[a-z]p_s\d+'   # storage buffer bindings: vp_ / fp_ / cp_ / gp_ ... s<n>
_ADD = re.compile(r'^\s*int (' + _IDENT + r') = (' + _IDENT + r') \+ (-?\d+);\s*$')
_IDX = re.compile(r'^\s*uint (' + _IDENT + r') = uint\(int\(uint\((' + _IDENT + r')\) >> uint\(2\)\)\);\s*$')
_LOAD = re.compile(r'\(\*spvDescriptorSet0\.(' + _BUF + r')\)\._m0\[int\((' + _IDENT + r')\)\]')
_RO = re.compile(r'^\s*const device ' + _IDENT + r'\* (' + _BUF + r') \[\[id\(\d+\)\]\];', re.M)
_OP = r'(?:[-+*/%|&^]|<<|>>)?=(?!=)'
_WRITE = re.compile(r'atomic_|_barrier\(|\.write\(|\]\s*' + _OP + r'|^\s*\*|^\s*' + _IDENT + r'\s*' + _OP)   # lines a run does not reach across
_VEC = {2: 'packed_uint2', 3: 'packed_uint3', 4: 'packed_uint4'}


def _root(v, adds):   # (value, byte offset) the sums lead back to
    off = 0
    for _ in range(64):
        if v not in adds: break
        v, k = adds[v]; off += k
    return v, off


def wide_loads(msl):
    if ' >> uint(2)' not in msl: return msl
    ro = set(_RO.findall(msl))
    if not ro: return msl
    lines = msl.split('\n')
    adds, idx = {}, {}
    for ln in lines:
        m = _ADD.match(ln)
        if m: adds[m.group(1)] = (m.group(2), int(m.group(3))); continue
        m = _IDX.match(ln)
        if m: idx[m.group(1)] = m.group(2)
    words, block = {}, 0   # (block, buffer, value) → {byte offset: (line, match)}
    for i, ln in enumerate(lines):
        if '{' in ln or '}' in ln or _WRITE.search(ln): block += 1; continue
        ms = list(_LOAD.finditer(ln))
        if len(ms) != 1 or ms[0].group(1) not in ro or ms[0].group(2) not in idx: continue
        v, off = _root(idx[ms[0].group(2)], adds)
        if off % 4 == 0: words.setdefault((block, ms[0].group(1), v), {}).setdefault(off, (i, ms[0]))
    edits, n = {}, 0
    for (_, buf, _), by_off in words.items():
        for base in sorted({off - off % 16 for off in by_off}):
            run = []
            while len(run) < 4 and base + 4 * len(run) in by_off: run.append(by_off[base + 4 * len(run)])
            if len(run) < 2 or any(i < run[0][0] for i, _ in run): continue
            name, vec = f'_dmw{n}', _VEC[len(run)]; n += 1
            decl = f'{vec} {name} = *(const device {vec}*)&(*spvDescriptorSet0.{buf})._m0[int({run[0][1].group(2)})];'
            for w, (i, m) in enumerate(run): edits.setdefault(i, []).append((m.start(), m.end(), f'{name}.{"xyzw"[w]}', decl if w == 0 else None))
    for i, es in edits.items():
        ln, pre = lines[i], []
        for s, e, rep, decl in sorted(es, reverse=True):
            ln = ln[:s] + rep + ln[e:]
            if decl: pre.append(decl)
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = ''.join(indent + d + '\n' for d in pre) + ln
    return '\n'.join(lines)


# Raw reads in fours on the kept entry. The translator's scalar helper (GlobalToStorage.TryGenerateRawStorageOp) keeps the entry it found last in seven
# private words and compares each address with that entry's range in 32-bit halves. Here it becomes dm_raw with three ulong words (the entry's start, its
# length and its delta: an address inside is one subtract and one compare; on a miss the hint and the search are the helper's), and four reads at +0, +4,
# +8 and +12 from one address become one dm_raw4: one range check, then one 16-byte load when the host address is aligned, four word loads when not. The
# four addresses are compared at run time too (each 4 past the one before), and a run that is not, leaves the kept entry or reaches past its end reads word
# by word through dm_raw, so dm_raw4 returns what the four reads did. A run ends at a brace, at a line that may write memory (_WRITE) and at a call of any
# other function, so reading the later words at the first one's place reads the same values. Ocarina of Time's Hyrule Castle Town: 35 vertex shaders of its
# main pass (253 raw reads a vertex, 232 of them in fours) took that pass from 6.8 to 5.2 ms of GPU time, the frame from 17.7 to 15.5-16.0 ms
_RAW7 = re.compile(r'static inline __attribute__\(\(always_inline\)\)\nint (_\d+)\(thread const int& _\d+, thread const int& _\d+, ((?:const )?device) (_\d+)& (\w+)'
                   r'((?:, thread uint& _\d+){7})\)\n\{\n.*?\n\}\n', re.S)
_RAW7_TAIL = re.compile(r'uint (_\d+) = \*\(reinterpret_cast<(?:const )?device uint\*>\(as_type<ulong>\(uint2\(uint\(_\d+\), uint\(_\d+\)\)\)\)\);\n\s*float (_\d+) = '
                        r'as_type<float>\(\1\);\n\s*return as_type<int>\(\2\);\n    \}\n    _\d+ = false;\n    return 0;\n\}\n$')
_RAW7_MARKS = ('& 4095;', ' * 8;', ' + 7;', ' + 6;', '< 2097152u;', '= 0 + 4;', ' >> uint(1)', ' + 2;', ' + 3;', ' + 4;', ' + 5;')
_ENTRY = re.compile(r'(?ms)^(?:vertex|fragment|kernel) [^\n]*\(.*?^\}')
_CALL_ANY = re.compile(r'\b(_\d+|dm_\w+)\s*\(')


def _raw_fours_helpers(qual, typ):
    return f'''static inline __attribute__((always_inline))
int dm_raw(int lo, int hi, {qual} {typ}& t, thread ulong& s, thread ulong& n, thread ulong& d)
{{
    ulong a = as_type<ulong>(uint2(uint(lo), uint(hi)));
    if (a - s >= n)
    {{
        uint chunk = (uint(hi) << 11) | (uint(lo) >> 21);
        uint h = (chunk & 4095u) * 8u;
        uint idx = t._m0[h + 7u];
        if (!(idx != 0u && t._m0[h + 6u] == chunk && uint(hi) < 2097152u))
        {{
            uint i = 0u;
            for (uint step = t._m0[4] >> 1; step != 0u; step >>= 1)
            {{
                uint m = i + step;
                i = as_type<ulong>(uint2(t._m0[m * 8u], t._m0[m * 8u + 1u])) <= a ? m : i;
            }}
            idx = i;
        }}
        uint b = idx * 8u;
        ulong st = as_type<ulong>(uint2(t._m0[b], t._m0[b + 1u]));
        ulong en = as_type<ulong>(uint2(t._m0[b + 2u], t._m0[b + 3u]));
        if (!(a < en)) return 0;
        s = st; n = en - st; d = as_type<ulong>(uint2(t._m0[b + 4u], t._m0[b + 5u]));
    }}
    return as_type<int>(*reinterpret_cast<const device uint*>(a + d));
}}

static inline __attribute__((always_inline))
uint4 dm_raw4(int lo0, int hi0, int lo1, int hi1, int lo2, int hi2, int lo3, int hi3, {qual} {typ}& t, thread ulong& s, thread ulong& n, thread ulong& d)
{{
    ulong a = as_type<ulong>(uint2(uint(lo0), uint(hi0)));
    ulong r = a - s;
    if (as_type<ulong>(uint2(uint(lo1), uint(hi1))) == a + 4 && as_type<ulong>(uint2(uint(lo2), uint(hi2))) == a + 8 && as_type<ulong>(uint2(uint(lo3), uint(hi3))) == a + 12 &&
        r < n && n - r >= 16)
    {{
        ulong h = a + d;
        if ((h & 15) == 0) return *reinterpret_cast<const device uint4*>(h);
        const device uint* p = reinterpret_cast<const device uint*>(h);
        return uint4(p[0], p[1], p[2], p[3]);
    }}
    uint4 v;
    v.x = uint(dm_raw(lo0, hi0, t, s, n, d));
    v.y = uint(dm_raw(lo1, hi1, t, s, n, d));
    v.z = uint(dm_raw(lo2, hi2, t, s, n, d));
    v.w = uint(dm_raw(lo3, hi3, t, s, n, d));
    return v;
}}
'''


def _raw_fours_entry(body, call, words, table):
    """One entry point: its seven words as three, its reads through dm_raw and its runs of four through dm_raw4; None when it is not as expected"""
    lines = body.split('\n')
    decl = [f'    uint {w} = 0u;' for w in words]
    at = [i for i in range(len(lines) - 6) if lines[i:i + 7] == decl]
    if len(at) != 1: return None
    defs, calls = {}, []
    for i, ln in enumerate(lines):
        m = re.fullmatch(r'\s*(?:int|uint|float|bool) (_\d+) = (.+);', ln)
        if m: defs.setdefault(m.group(1), (i, m.group(2)))
        c = call.fullmatch(ln)
        if c: calls.append((i, c))
    def alias(v, before):   # a later word's address copy (made after the run's first read) as the value it copies, defined before that read
        while v in defs and defs[v][0] >= before and re.fullmatch(r'_\d+', defs[v][1]): v = defs[v][1]
        return v
    def root(v):
        off = 0
        for _ in range(16):
            e = defs.get(v, (0, ''))[1]
            a = re.fullmatch(r'(_\d+)', e) or re.fullmatch(r'(_\d+) \+ (-?\d+)', e) or re.fullmatch(r'as_type<int>\((_\d+)\)(?: \+ (-?\d+))?', e)
            if not a: break
            v = a.group(1)
            if a.re.groups > 1 and a.group(2): off += int(a.group(2))
        return v, off
    out = {i: f'{c["ind"]}int {c["out"]} = dm_raw({c["lo"]}, {c["hi"]}, {c["tab"]}, dm_s, dm_n, dm_d);' for i, c in calls}
    k, nv = 0, 0
    while k + 3 < len(calls):
        run = calls[k:k + 4]
        r0 = root(run[0][1]['lo'])
        ok = all(root(c['lo']) == (r0[0], r0[1] + 4 * j) and c['ind'] == run[0][1]['ind'] for j, (_, c) in enumerate(run))
        between = lines[run[0][0] + 1:run[3][0]]
        ok = ok and not any('{' in ln or '}' in ln or _WRITE.search(ln) or any(m.group(1) != 'dm_raw' and not call.fullmatch(ln) for m in _CALL_ANY.finditer(ln)) for ln in between)
        args = [alias(v, run[0][0]) for _, c in run for v in (c['lo'], c['hi'])]
        ok = ok and all(a in defs and defs[a][0] < run[0][0] for a in args[2:])
        if not ok: k += 1; continue
        v = f'dm_q{nv}'; nv += 1
        c0 = run[0][1]
        out[run[0][0]] = f'{c0["ind"]}uint4 {v} = dm_raw4({", ".join(args)}, {c0["tab"]}, dm_s, dm_n, dm_d);\n{c0["ind"]}int {c0["out"]} = as_type<int>({v}.x);'
        for (i, c), comp in zip(run[1:], 'yzw'): out[i] = f'{c["ind"]}int {c["out"]} = as_type<int>({v}.{comp});'
        k += 4
    for i, ln in out.items(): lines[i] = ln
    lines[at[0]:at[0] + 7] = ['    ulong dm_s = 0, dm_n = 0, dm_d = 0;']
    return '\n'.join(lines), len(calls), nv


def raw_fours(msl):
    """→ (msl, reads, runs of four): the scalar raw helper as dm_raw and its runs of four adjacent reads as dm_raw4 (see above); msl as it was, 0, 0 when the
    helper is not the expected one or a call or its words are not where expected"""
    hm = list(_RAW7.finditer(msl))
    if len(hm) != 1: return msl, 0, 0
    hm = hm[0]; name, qual, typ, table = hm.group(1), hm.group(2), hm.group(3), hm.group(4)
    words = re.findall(r'thread uint& (_\d+)', hm.group(5))
    helper = hm.group(0)
    if not _RAW7_TAIL.search(helper) or helper.count(table + '._m0[') != 11 or any(m not in helper for m in _RAW7_MARKS) or 'atomic' in helper or 'extract_bits' in helper: return msl, 0, 0
    call = re.compile(r'(?P<ind> +)int (?P<out>_\d+) = ' + name + r'\((?P<lo>_\d+), (?P<hi>_\d+), (?P<tab>\(\*spvDescriptorSet0\.' + re.escape(table) + r'\)), ' + ', '.join(words) + r'\);')
    reads = runs = 0; pieces, last = [], 0
    for e in _ENTRY.finditer(msl):
        if name + '(' not in e.group(0): continue
        got = _raw_fours_entry(e.group(0), call, words, table)
        if not got or name + '(' in got[0]: return msl, 0, 0
        pieces += [msl[last:e.start()], got[0]]; last = e.end(); reads += got[1]; runs += got[2]
    out = ''.join(pieces) + msl[last:]
    out = out.replace(helper, _raw_fours_helpers(qual, typ))
    if name + '(' in out or any(re.search(r'\b' + w + r'\b', out) for w in words): return msl, 0, 0
    return out, reads, runs


