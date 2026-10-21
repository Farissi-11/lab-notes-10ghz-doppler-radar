#!/usr/bin/env python3
"""Recompute the numbers of the Lab Note from a saved capture (CSV: time_s, if_mV).

Usage:  python host/analyze_capture.py data/if_at_rest_2026-10-21_132718.csv
Prints the DC level, the mains lines (50, 150, 250 Hz) and the noise floor
of the spectrum (Hann window, same method as radar_spectrum.py).
"""
import sys, csv
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "data/if_at_rest_2026-10-21_132718.csv"
rows = list(csv.reader(open(path)))[1:]
t = np.array([float(r[0]) for r in rows])
mv = np.array([float(r[1]) for r in rows])
fs = 1.0 / np.median(np.diff(t))
x = mv - mv.mean()
w = np.hanning(len(x))
spec = np.abs(np.fft.rfft(x * w)) * 2 / w.sum()            # amplitude in mV
f = np.fft.rfftfreq(len(x), 1 / fs)

def line(f0):
    sel = np.abs(f - f0) <= 2.0
    k = np.argmax(np.where(sel, spec, 0))
    return f[k], spec[k]

mains = np.abs(f - 50 * np.round(f / 50)) <= 3.0
band = (f >= 5) & (f <= 300) & ~mains
print(f"file          : {path}")
print(f"samples       : {len(x)} at {fs:.0f} samples/s ({len(x) / fs:.2f} s), bin {fs / len(x):.2f} Hz")
print(f"DC level      : {mv.mean():.1f} mV")
for f0 in (50, 150, 250):
    fk, a = line(f0)
    print(f"line {f0:3d} Hz   : {a:.2f} mV at {fk:.1f} Hz")
print(f"noise floor   : {np.median(spec[band]) * 1000:.0f} uV per bin (median, 5-300 Hz, mains lines excluded)")
