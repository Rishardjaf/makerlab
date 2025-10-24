"""
protocol_regex.py
-----------------
Strict patterns for the glove protocol + a tiny validator.

Message format: ASCII, comma-separated, NO SPACES, one message per line, newline-terminated.
<dev> is the device id (1 = note hand, 2 = volume/FX hand).

TYPES
=====
A) BUTTONS
   B,<dev>,NH,<0|1>        # Note Hold (momentary)
   B,<dev>,VH,<0|1>        # Volume/FX Hold (momentary)
   B,<dev>,SUS,<0|1>       # Sustain toggle (1=on, 0=off)
   B,<dev>,OCT,<+/-N>      # Octave step (edge), e.g. +1 or -1
   B,<dev>,PANIC,1         # Sustain off for that device (releases sustained notes)

B) VALUES
   P,<dev>,<note>          # Pitch only (note name like C4/F#5/Db3 OR MIDI 0..127)
   V,<dev>,<0-127>         # Volume (0..127). Also velocity for future notes.
   E,<dev>,<PARAM>,<0-127> # FX macro while VH=1  (PARAM in {CUT,RESO,REV,DEL,MOD,PAN})
"""

import re

# ---- atoms ----
NUM_0_127 = r'(?:12[0-7]|1[01]\d|\d{1,2})'        # 0..127 with no leading spaces
DEV       = r'(?P<dev>\d{1,3})'
NOTE_NAME = r'(?:[A-Ga-g][#b]?-?\d+)'             # C4, F#5, Db3, etc.
NOTE_ANY  = rf'(?P<note>(?:{NOTE_NAME}|{NUM_0_127}))'

# ---- compiled patterns ----
RE_B_NH   = re.compile(rf'^B,{DEV},NH,(?P<state>[01])$')
RE_B_VH   = re.compile(rf'^B,{DEV},VH,(?P<state>[01])$')
RE_B_SUS  = re.compile(rf'^B,{DEV},SUS,(?P<state>[01])$')
RE_B_OCT  = re.compile(rf'^B,{DEV},OCT,(?P<delta>[+-]?\d{{1,2}})$')
RE_B_PAN  = re.compile(rf'^B,{DEV},PANIC,1$')

RE_P      = re.compile(rf'^P,{DEV},{NOTE_ANY}$')
RE_V      = re.compile(rf'^V,{DEV},(?P<val>{NUM_0_127})$')
RE_E      = re.compile(rf'^E,{DEV},(?P<param>CUT|RESO|REV|DEL|MOD|PAN),(?P<val>{NUM_0_127})$')

ALL = [
    ("B_NH",  RE_B_NH),
    ("B_VH",  RE_B_VH),
    ("B_SUS", RE_B_SUS),
    ("B_OCT", RE_B_OCT),
    ("B_PAN", RE_B_PAN),
    ("P",     RE_P),
    ("V",     RE_V),
    ("E",     RE_E),
]

def classify(line: str):
    """Return (name, match_groups) or (None, None)."""
    for name, rx in ALL:
        m = rx.match(line)
        if m:
            return name, m.groupdict()
    return None, None

if __name__ == "__main__":
    # sample lines (you can replace with your own)
    samples = [
        "B,1,NH,1",
        "B,1,NH,0",
        "B,2,VH,1",
        "B,1,SUS,1",
        "B,1,SUS,0",
        "B,1,OCT,+1",
        "B,1,OCT,-1",
        "B,1,PANIC,1",
        "P,1,C5",
        "P,1,73",
        "V,2,96",
        "E,2,CUT,74",
        "E,2,PAN,64",
        "E,2,RESO,40",
    ]
    for s in samples:
        kind, groups = classify(s)
        print(f"{s:18} -> {kind} {groups}")
