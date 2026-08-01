# Phase 0 — prove the network

Firmware for the project fair. Same machine code as week 10; the only change is
that the board **joins** a network instead of hosting one, and answers to
`plotter.local`.

Phase 0 is finished when the laptop can plot a `.gcode` through `plotter.local`
with no USB cable attached. Nothing else gets built until that works.

## Flash it

```bash
cp secrets.example.h secrets.h
```

Fill in the SSID and password, then open `firmware.ino` in the Arduino IDE and
upload to the Xiao ESP32-C3. `secrets.h` is gitignored.

## What the serial monitor should say

At 115200 baud, one of two things:

```
joining <ssid> ....
connected, IP 192.168.1.47
http://plotter.local
```

or, if the network wasn't there:

```
joining <ssid> ........................
no network, falling back to the access point
AP up, IP 192.168.4.1
http://plotter.local
```

**Write down the IP either way.** It's the fallback for when mDNS is filtered.

## The four tests

Do these on the network you'll actually use at the fair, not on your home wifi.

### 1. The board joins at all

Serial says `connected`, not `falling back`.

If it never joins: the ESP32-C3 is **2.4GHz only** and cannot see a 5GHz
network. On an iPhone hotspot, turn on *Maximize Compatibility*.

### 2. The laptop reaches it by name

Open `http://plotter.local` — you should get the week 10 control page. Home the
machine and draw the test circle from it.

If the page won't load by name but the raw IP works, multicast is being
filtered. Not fatal: everything downstream takes the address from config, so
paste the IP there instead.

### 3. Client isolation — the one that can kill the design

From the laptop, with **no USB cable**:

```bash
ping -c 3 plotter.local
```

Then serve anything from the laptop and load it on the iPad:

```bash
python3 -m http.server 5050
```

Open `http://<your-laptop>.local:5050` on the iPad. (`scutil --get LocalHostName`
prints the name.)

If either direction fails while both devices are clearly on the network, the
router is isolating clients. **No amount of code fixes this** — the laptop
can't reach the plotter and the iPad can't reach the laptop. Change the router
setting if you control it, or change networks.

### 4. Plot something end to end

On `http://plotter.local`: home, then upload a `.gcode` from
`../../src/output/` (`me.gcode` is a good one), then press *draw file*.

Unplug the USB cable first. If it draws, phase 0 is done.

## If it comes up as the access point instead

That's the fallback working, not a failure — the machine is still reachable at
`192.168.4.1` by joining `esp-captive`. But phase 0 isn't passed until it joins
the real network, because the whole architecture depends on the laptop being on
a network that also has internet.
