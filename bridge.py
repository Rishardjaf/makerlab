# bridge.py — Micro:bit text -> MIDI via pygame.midi (no compiler needed)
import sys, re, threading, time
import pygame.midi as pm
import serial
from serial.tools import list_ports

LOOPMIDI_NAME = "theremin port"   # name of your loopMIDI virtual IN
BAUD = 115200
COM_PORTS = ["COM14"]  # e.g. ["COM7","COM9"]; leave [] to auto-detect micro:bit ports

NOTE_BASE = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}
def note_name_to_number(name):
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", name.strip())
    if not m: return 60
    letter, acc, octv = m.groups()
    pc = NOTE_BASE[letter.upper()]
    if acc == '#': pc += 1
    elif acc == 'b': pc -= 1
    return max(0, min(127, 12*(int(octv)+1) + pc))  # C-1=0, C4=60

def find_loopmidi_device(name_hint):
    pm.init()
    count = pm.get_count()
    best = None
    for dev_id in range(count):
        interf, name, is_input, is_output, opened = pm.get_device_info(dev_id)
        if is_output and (name_hint.lower() in name.decode().lower()):
            best = dev_id
            break
    if best is None:
        names = [pm.get_device_info(i)[1].decode() for i in range(count)]
        raise RuntimeError(f"Could not find MIDI out like '{name_hint}'. Found: {names}")
    return pm.Output(best)

midi_out = find_loopmidi_device(LOOPMIDI_NAME)
last_note_for_device = {}

def send_note_on(note, vel):
    midi_out.note_on(note, max(1, min(127, vel)))

def send_note_off(note):
    midi_out.note_off(note, 0)

def handle_line(line):
    # Expect "N,<device_id>,<note>,<vel>,<gate>"
    # Example: N,1,C5,100,1
    try:
        if not line.startswith("N,"):
            return
        _, dev, note_name, vel_str, gate_str = line.strip().split(",")
        dev_id = int(dev)
        vel = int(vel_str); gate = int(gate_str)
        note = note_name_to_number(note_name)

        if gate == 1 and vel > 0:
            prev = last_note_for_device.get(dev_id)
            if prev is not None:
                send_note_off(prev)
            send_note_on(note, vel)
            last_note_for_device[dev_id] = note
        else:
            prev = last_note_for_device.get(dev_id)
            if prev is not None:
                send_note_off(prev)
                last_note_for_device[dev_id] = None
    except Exception as e:
        print("Parse error:", e, "for line:", line)

def reader_thread(port_name):
    try:
        with serial.Serial(port_name, BAUD, timeout=0.1) as ser:
            print(f"[{port_name}] open")
            buf = b""
            while True:
                data = ser.read(1024)
                if not data: 
                    continue
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode('utf-8', errors='ignore').strip()
                    if text:
                        handle_line(text)
    except Exception as e:
        print(f"[{port_name}] error:", e)

def find_microbit_ports():
    ports = []
    for p in list_ports.comports():
        name = (p.manufacturer or "") + " " + (p.description or "")
        if "mbed" in name.lower() or "micro:bit" in name.lower() or "daplink" in name.lower():
            ports.append(p.device)
    return ports

if __name__ == "__main__":
    ports = COM_PORTS or find_microbit_ports()
    if not ports:
        print("No micro:bit ports found. Plug them in and re-run.")
        sys.exit(1)
    print("Using ports:", ports)
    threads = []
    for pn in ports:
        t = threading.Thread(target=reader_thread, args=(pn,), daemon=True)
        t.start()
        threads.append(t)
    print("Bridge running. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting."); midi_out.close(); pm.quit()
