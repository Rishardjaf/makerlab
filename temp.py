# PITCH GLOVE (Device 1) — thumb = 3V, pins go HIGH when touched
from microbit import *

# ------------ CONFIG ------------
DEV = 1
BASE_NOTE = 60        # C4
OCT_STEP  = 12
Y_THRESH  = (-400, -100, 200, 500)  # y-accel zones
LADDER_ST = [0, 2, 4, 5, 7]        # pentatonic degrees
SMOOTH_ALPHA  = 0.25
PITCH_SEND_MS = 90

# finger pins (match your wiring)
PIN_NH   = pin1   # hold-to-play
PIN_OCTU = pin2   # octave up
PIN_OCTD = pin8   # octave down
PIN_SUS  = pin12  # sustain toggle

# set pull-down so untouched=0, touched=1 (thumb at 3V)
for p in (PIN_NH, PIN_OCTU, PIN_OCTD, PIN_SUS):
    p.set_pull(p.PULL_DOWN)

def send(s): print(s)
def clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v

def y_to_semitone(y):
    a, b, c, d = Y_THRESH
    if y < a:      return LADDER_ST[0]
    elif y < b:    return LADDER_ST[1]
    elif y < c:    return LADDER_ST[2]
    elif y < d:    return LADDER_ST[3]
    else:          return LADDER_ST[4]

# ------------ STATE ------------
octave_offset = 0
sustain_on    = 0
nh = last_nh = last_octu = last_octd = last_sus = 0
smooth_y = accelerometer.get_y()
last_pitch_send = running_time()
last_note_num = None

# simple debounce helper
def edge(curr, prev, min_ms, stamp):
    now = running_time()
    if curr != prev and now - stamp >= min_ms:
        return True, now
    return False, stamp

db_nh = db_octu = db_octd = db_sus = 0  # last change times

# ------------ MAIN ------------
while True:
    nh_now   = PIN_NH.read_digital()   # 1 when touched
    octu_now = PIN_OCTU.read_digital()
    octd_now = PIN_OCTD.read_digital()
    sus_now  = PIN_SUS.read_digital()

    # NH edge with 30ms debounce
    chg, db_nh = edge(nh_now, last_nh, 30, db_nh)
    if chg:
        nh = nh_now
        send("B,{},{},{}".format(DEV, "NH", nh))
        display.show("♪" if nh else " ")
        last_nh = nh_now

    # OCT+ edge
    chg, db_octu = edge(octu_now, last_octu, 40, db_octu)
    if chg and octu_now == 1:
        octave_offset = clamp(octave_offset + OCT_STEP, -24, 36)
        send("B,{},{},{}".format(DEV, "OCT", "+1"))
        display.show("+")

    last_octu = octu_now

    # OCT- edge
    chg, db_octd = edge(octd_now, last_octd, 40, db_octd)
    if chg and octd_now == 1:
        octave_offset = clamp(octave_offset - OCT_STEP, -24, 36)
        send("B,{},{},{}".format(DEV, "OCT", "-1"))
        display.show("-")

    last_octd = octd_now

    # SUS toggle on rising edge
    chg, db_sus = edge(sus_now, last_sus, 80, db_sus)
    if chg and sus_now == 1:
        sustain_on = 0 if sustain_on else 1
        send("B,{},{},{}".format(DEV, "SUS", sustain_on))
        display.show("S" if sustain_on else " ")
    last_sus = sus_now

    # pure acceleration -> pitch
    y = accelerometer.get_y()
    smooth_y = SMOOTH_ALPHA * y + (1 - SMOOTH_ALPHA) * smooth_y
    st = y_to_semitone(smooth_y)
    note_num = clamp(BASE_NOTE + st + octave_offset, 0, 127)

    # throttled pitch messages
    now = running_time()
    if now - last_pitch_send >= PITCH_SEND_MS:
        if (note_num != last_note_num) or nh == 1:
            send("P,{},{}".format(DEV, note_num))
            last_note_num = note_num
        last_pitch_send = now

    sleep(18)
