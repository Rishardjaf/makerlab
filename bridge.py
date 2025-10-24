import re, sys, time, threading
import pygame.midi as pm
import serial
from serial.tools import list_ports

# =========================
# Config (easy to tweak)
# =========================
LOOPMIDI_NAME   = "theremin port"
BAUD            = 115200
LOG_EVERY_LINE  = True    # set False to reduce console spam
DEADBAND_CC     = 2       # min CC change to send
OCT_MIN, OCT_MAX = -24, 36  # semitone clamp for octave offset (±2 to +3 octaves)

CC_MAP = {  # effect name -> CC number
    "CUT": 74,   # filter cutoff
    "RESO": 71,  # resonance
    "PAN": 10,   # pan
    "REV": 91,   # reverb send
    "DEL": 94,   # delay send
    "MOD": 1,    # modulation wheel
}
DEFAULT_VELOCITY = 96

# =========================
# Regex (strict & readable)
# =========================
NUM_0_127 = r'(?:12[0-7]|1[01]\d|\d{1,2})'
DEV       = r'(?P<dev>\d{1,3})'
NOTE_NAME = r'(?:[A-Ga-g][#b]?-?\d+)'
NOTE_ANY  = rf'(?P<note>(?:{NOTE_NAME}|{NUM_0_127}))'

RE_B_NH   = re.compile(rf'^B,{DEV},NH,(?P<state>[01])$')
RE_B_VH   = re.compile(rf'^B,{DEV},VH,(?P<state>[01])$')
RE_B_SUS  = re.compile(rf'^B,{DEV},SUS,(?P<state>[01])$')
RE_B_OCT  = re.compile(rf'^B,{DEV},OCT,(?P<delta>[+-]?\d{{1,2}})$')
RE_B_PAN  = re.compile(rf'^B,{DEV},PANIC,1$')

RE_P      = re.compile(rf'^P,{DEV},{NOTE_ANY}$')
RE_V      = re.compile(rf'^V,{DEV},(?P<val>{NUM_0_127})$')
RE_E      = re.compile(rf'^E,{DEV},(?P<param>CUT|RESO|REV|DEL|MOD|PAN),(?P<val>{NUM_0_127})$')

# =========================
# MIDI out (pygame.midi)
# =========================
def open_loopmidi(name_hint):
    pm.init()
    outs = []
    for i in range(pm.get_count()):
        interf, name, is_in, is_out, opened = pm.get_device_info(i)
        if is_out:
            outs.append((i, name.decode()))
    for i, n in outs:
        if name_hint.lower() in n.lower():
            print(f"[MIDI] using: {n} (id={i})")
            return pm.Output(i)
    raise RuntimeError(f"Could not find MIDI out like '{name_hint}'. Found: {[n for _,n in outs]}")

midi = open_loopmidi(LOOPMIDI_NAME)

def midi_note_on(note, vel):
    vel = max(1, min(127, vel))
    note = max(0, min(127, note))
    midi.note_on(note, vel)

def midi_note_off(note):
    note = max(0, min(127, note))
    midi.note_off(note, 0)

def midi_cc(cc, val):
    val = max(0, min(127, val))
    midi.write_short(0xB0, cc & 0x7F, val)

# =========================
# Utilities
# =========================
NOTE_BASE = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}
def note_name_to_number(name):
    # Accept C4, F#5, Db3 or raw "0..127"
    m = re.fullmatch(r'([A-Ga-g])([#b]?)(-?\d+)', name)
    if m:
        letter, acc, octv = m.groups()
        pc = NOTE_BASE[letter.upper()]
        if acc == '#': pc += 1
        elif acc == 'b': pc -= 1
        num = 12*(int(octv)+1) + pc  # C-1=0
        return max(0, min(127, num))
    try:
        return max(0, min(127, int(name)))
    except:
        return 60  # default C4

def clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v

# =========================
# Per-device state
# =========================
class DevState:
    def __init__(self):
        self.note_hold = 0
        self.vol_hold  = 0
        self.sustain_on = 0
        self.octave_offset = 0   # semitones
        self.last_volume = DEFAULT_VELOCITY
        self.current_note = None       # sounding due to NH
        self.sustained_note = None     # sounding due to SUS
        self.last_cc_vals = {}         # for deadband

    def cc_send(self, cc, val):
        prev = self.last_cc_vals.get(cc)
        if prev is None or abs(val - prev) >= DEADBAND_CC:
            midi_cc(cc, val)
            self.last_cc_vals[cc] = val

DEVICES = {}  # dev_id:int -> DevState
def S(dev_id):  # get state
    st = DEVICES.get(dev_id)
    if st is None:
        st = DevState()
        DEVICES[dev_id] = st
    return st

# =========================
# Handlers
# =========================
def handle_button(line):
    m = (RE_B_NH.match(line) or RE_B_VH.match(line) or RE_B_SUS.match(line) or
         RE_B_OCT.match(line) or RE_B_PAN.match(line))
    if not m: return False
    dev = int(m.group('dev')); st = S(dev)

    if RE_B_NH.match(line):
        state = int(m.group('state'))
        if LOG_EVERY_LINE: print(f"[B] dev{dev} NH={state}")
        prev = st.note_hold
        st.note_hold = state
        if prev == 1 and state == 0 and st.sustain_on == 0:
            # releasing NH -> stop non-sustained current note
            if st.current_note is not None:
                midi_note_off(st.current_note); st.current_note = None
        # if pressing NH and we already have a pitch waiting, we’ll trigger on next P

    elif RE_B_VH.match(line):
        state = int(m.group('state'))
        if LOG_EVERY_LINE: print(f"[B] dev{dev} VH={state}")
        st.vol_hold = state

    elif RE_B_SUS.match(line):
        state = int(m.group('state'))
        if LOG_EVERY_LINE: print(f"[B] dev{dev} SUS={state}")
        if state == 1:
            st.sustain_on = 1
            # if a current note exists, promote it to sustained
            if st.current_note is not None:
                st.sustained_note = st.current_note
        else:
            st.sustain_on = 0
            # sustain OFF -> stop sustained
            if st.sustained_note is not None:
                midi_note_off(st.sustained_note)
                st.sustained_note = None

    elif RE_B_OCT.match(line):
        delta = int(m.group('delta'))
        st.octave_offset = clamp(st.octave_offset + 12*delta, OCT_MIN, OCT_MAX)
        if LOG_EVERY_LINE: print(f"[B] dev{dev} OCT offset={st.octave_offset}")

    elif RE_B_PAN.match(line):
        # PANIC = sustain off ONLY (your requirement)
        if LOG_EVERY_LINE: print(f"[B] dev{dev} PANIC -> sustain off only")
        st.sustain_on = 0
        if st.sustained_note is not None:
            midi_note_off(st.sustained_note)
            st.sustained_note = None

    return True

def handle_pitch(line):
    m = RE_P.match(line)
    if not m: return False
    dev = int(m.group('dev')); st = S(dev)
    note = note_name_to_number(m.group('note'))
    note = clamp(note + st.octave_offset, 0, 127)

    if LOG_EVERY_LINE: print(f"[P] dev{dev} pitch={note} NH={st.note_hold} SUS={st.sustain_on}")

    if st.note_hold == 1:
        # with sustain on: replace sustained note if different
        if st.sustain_on:
            if st.sustained_note != note:
                if st.sustained_note is not None:
                    midi_note_off(st.sustained_note)
                midi_note_on(note, st.last_volume)
                st.sustained_note = note
            st.current_note = None  # current is irrelevant while sustaining
        else:
            # no sustain: retrigger if changed
            if st.current_note != note:
                if st.current_note is not None:
                    midi_note_off(st.current_note)
                midi_note_on(note, st.last_volume)
                st.current_note = note
    else:
        # NH not held: just remember; no sound
        pass

    return True

def handle_volume(line):
    m = RE_V.match(line)
    if not m: return False
    dev = int(m.group('dev')); st = S(dev)
    val = int(m.group('val'))
    st.last_volume = val
    if LOG_EVERY_LINE: print(f"[V] dev{dev} vol={val} VH={st.vol_hold}")
    # while VH held, send as expression (CC11) with deadband
    if st.vol_hold == 1:
        st.cc_send(11, val)  # CC11 Expression
    return True

def handle_effect(line):
    m = RE_E.match(line)
    if not m: return False
    dev = int(m.group('dev')); st = S(dev)
    param = m.group('param'); val = int(m.group('val'))
    if LOG_EVERY_LINE: print(f"[E] dev{dev} {param}={val} VH={st.vol_hold}")
    if st.vol_hold == 1:
        cc = CC_MAP.get(param)
        if cc is not None:
            st.cc_send(cc, val)
    return True

# =========================
# Serial readers
# =========================
def find_microbit_ports():
    hits = []
    for p in list_ports.comports():
        label = f"{p.manufacturer or ''} {p.description or ''}".lower()
        if "mbed" in label or "micro:bit" in label or "daplink" in label:
            hits.append(p.device)
    return hits

def reader_thread(port_name):
    try:
        with serial.Serial(port_name, BAUD, timeout=0.2) as ser:
            print(f"[SER] open {port_name} @ {BAUD}")
            buf = b""
            while True:
                data = ser.read(1024)
                if not data:
                    continue
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode('utf-8', errors='ignore').strip("\r").strip()
                    if not text: continue
                    if LOG_EVERY_LINE: print("[RX]", text)
                    # dispatch
                    if handle_button(text): continue
                    if handle_pitch(text):  continue
                    if handle_volume(text): continue
                    if handle_effect(text): continue
                    if LOG_EVERY_LINE: print("[SKIP] Unmatched:", text)
    except Exception as e:
        print(f"[SER] {port_name} error:", e)

def main():
    ports=["COM14","COM17"]  # find_microbit_ports()
    # ports = find_microbit_ports()
    # if not ports:
    #     print("[ERR] No micro:bit ports found. Plug them in and re-run.")
    #     sys.exit(1)
    # print("[SER] opening:", ports)
    threads = []
    for pn in ports:
        t = threading.Thread(target=reader_thread, args=(pn,), daemon=True)
        t.start()
        threads.append(t)
    print("[BRIDGE] running. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[BRIDGE] exiting.")
        try:
            midi.close()
        finally:
            pm.quit()

if __name__ == "__main__":
    main()
