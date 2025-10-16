from microbit import *

# Force the REPL/prints back to USB (undo any prior uart.init(tx=...,rx=...))
uart.init(115200)

i = 0
while True:
    i += 1
    display.show(Image.HEART)
    print("PING,", i)
    sleep(1000)
    display.clear()
    sleep(100)
