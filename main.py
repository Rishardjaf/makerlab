# MICRO:BIT – LEFT-HAND INCREMENTAL KNOBS (Device 2)
# Thumb -> 3V (use a 1–10k series resistor for safety)
# Pins (HIGH when touched):
#   P1: Volume  (hold) -> V,2,val      (CC11 via bridge)
#   P2: Reverb  (hold) -> E,2,REV,val  (CC91)
#   P8: Delay   (hold) -> E,2,DEL,val  (CC94)
#   P12: Mod    (hold) -> E,2,MOD,val  (CC1)  <-- replaces panic
#
# While a pin is held, ANY clockwise/anticlockwise twist nudges the value
# relative to the current value. Values clamp at 0..127 (no wrap-around).
# Anti-clockwise = increase (set INVERT=True to flip).

from microbit import *
import math

DEV = 2

# ---------- TUNING ----------
SEND_MS   = 120     # how often to send while held (ms)
SMOOTH_A  = 0.25    # EMA on value 0..127 (higher = snappier)
DEADBAND  = 2       # only send if value changed by >= this
INVERT    = False   # False: anti-clockwise increases; True: flip direction

# Sensitivity: degrees needed to sweep the whole 0..127 (per hold)
# e.g. 180 -> big turns; 90 -> smaller turns = more sensitive.
GAIN_DEG_PER_FULL = 180.0

DEFAULT_VOL = 96    # initial velocity for pitch glove (bridge uses this)

# Pins (HIGH when touched to 3V)
PIN_VOL = pin1
PIN_REV = pin2
PIN_DEL = pin8
PIN_MOD = pin12
for p in (PIN_VOL, PIN_REV, PIN_DEL, PIN_MOD):
    p.set_pull(p.PULL_DOWN)

def send(s): print(s)
def clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v

# --- Angle helpers ---
def roll_degrees():
    # micro:bit axes: x=left/right, y=forward/back, z=up/down
    y = accelerometer.get_y()
    z = accelerometer.get_z()
    ang = math.degrees(math.atan2(y, z))  # -180..+180
    return ang

def wrap_deg(d):
    while d > 180: d -= 360
    while d < -180: d += 360
    return d

# --- Per-control incremental state ---
class IncCtrl:
    def __init__(self, name, start_val):
        self.name = name
        self.active = 0
        self.last_angle = 0.0    # previous sampled angle while active
        self.val = start_val     # current 0..127 value
        self.smooth_val = None   # EMA state
        self.last_sent = None    # last value we emitted

    def on_press(self):
        self.active = 1
        self.last_angle = roll_degrees()
        if self.smooth_val is None:
            self.smooth_val = self.val
        display.show(self.name[0])  # 'V','R','D','M'

    def on_release(self):
        self.active = 0
        display.clear()

    def tick(self):
        # incremental: add small change from angle delta since last sample
        cur = roll_degrees()
        delta_deg = wrap_deg(cur - self.last_angle)
        if INVERT:
            delta_deg = -delta_deg

        # map degrees to value change
        # e.g., if GAIN_DEG_PER_FULL = 180, then 180° => +/-127
        step = (delta_deg / GAIN_DEG_PER_FULL) * 127.0
        # accumulate into value and clamp
        self.val = int(round(clamp(self.val + step, 0, 127)))

        # smoothing in value domain
        if self.smooth_val is None:
            self.smooth_val = self.val
        else:
            self.smooth_val = int(round(SMOOTH_A * self.val + (1.0 - SMOOTH_A) * self.smooth_val))

        # update last_angle to current so small nudges always work
        self.last_angle = cur
        return self.smooth_val

# initial defaults
ctrl_vol = IncCtrl("VOL", DEFAULT_VOL)
ctrl_rev = IncCtrl("REV", 0)
ctrl_del = IncCtrl("DEL", 0)
ctrl_mod = IncCtrl("MOD", 0)

last_vh = 0
last_send = running_time()

# Seed bridge with initial velocity (for future notes)
send("V,{},{}".format(DEV, DEFAULT_VOL))
display.show(Image.HEART)
sleep(300)
display.clear()

while True:
    # Read holds (HIGH when touched)
    h_vol = 1 if PIN_VOL.read_digital() else 0
    h_rev = 1 if PIN_REV.read_digital() else 0
    h_del = 1 if PIN_DEL.read_digital() else 0
    h_mod = 1 if PIN_MOD.read_digital() else 0

    # Edge handling per control
    if h_vol and not ctrl_vol.active: ctrl_vol.on_press()
    if (not h_vol) and ctrl_vol.active: ctrl_vol.on_release()

    if h_rev and not ctrl_rev.active: ctrl_rev.on_press()
    if (not h_rev) and ctrl_rev.active: ctrl_rev.on_release()

    if h_del and not ctrl_del.active: ctrl_del.on_press()
    if (not h_del) and ctrl_del.active: ctrl_del.on_release()

    if h_mod and not ctrl_mod.active: ctrl_mod.on_press()
    if (not h_mod) and ctrl_mod.active: ctrl_mod.on_release()

    # Overall VH = any control held (good for the bridge’s gating/UX)
    vh = 1 if (h_vol or h_rev or h_del or h_mod) else 0
    if vh != last_vh:
        send("B,{},VH,{}".format(DEV, vh))
        display.show("H" if vh else " ")
        last_vh = vh

    if vh == 0:
        sleep(15)
        continue

    # Rate-limited sending
    now = running_time()
    if now - last_send >= SEND_MS:
        if ctrl_vol.active:
            v = ctrl_vol.tick()
            if ctrl_vol.last_sent is None or abs(v - ctrl_vol.last_sent) >= DEADBAND:
                send("V,{},{}".format(DEV, v))           # CC11
                ctrl_vol.last_sent = v

        if ctrl_rev.active:
            v = ctrl_rev.tick()
            if ctrl_rev.last_sent is None or abs(v - ctrl_rev.last_sent) >= DEADBAND:
                send("E,{},REV,{}".format(DEV, v))       # CC91
                ctrl_rev.last_sent = v

        if ctrl_del.active:
            v = ctrl_del.tick()
            if ctrl_del.last_sent is None or abs(v - ctrl_del.last_sent) >= DEADBAND:
                send("E,{},DEL,{}".format(DEV, v))       # CC94
                ctrl_del.last_sent = v

        if ctrl_mod.active:
            v = ctrl_mod.tick()
            if ctrl_mod.last_sent is None or abs(v - ctrl_mod.last_sent) >= DEADBAND:
                send("E,{},MOD,{}".format(DEV, v))       # CC1 (mod wheel)
                ctrl_mod.last_sent = v

        last_send = now

    sleep(15)
