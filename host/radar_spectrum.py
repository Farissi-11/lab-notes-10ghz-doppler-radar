#!/usr/bin/env python3
"""
Lab Notes - 10 GHz radar, part 1: live signal, spectrum and speed.

Reads the blocks sent by the board (radar IF on an ADC input), then:
  - removes the DC part (~45 mV),
  - computes the spectrum (FFT),
  - finds the Doppler peak and converts it to speed: v = f / 70.2 (m/s).

Install once :  pip install -r requirements.txt
Run         :  python host/radar_spectrum.py COM5            (Windows, see Device Manager)
               python3 host/radar_spectrum.py /dev/ttyACM0  (Linux)
Test without the board:  python host/radar_spectrum.py --demo
Keys in the window:  s = save PNG + CSV of the current block,  q = quit
                     b = learn the background (5 blocks, nothing moving):
                         fixed lines such as the 50 Hz mains hum are then
                         subtracted before looking for the Doppler peak
                     c = clear the background
The console prints one line per block with the "movement level": the energy
of the spectrum between 5 and 300 Hz, mains lines (50, 100, 150 ... Hz) left
out. Compare it at rest and while something moves in front of the radar.
"""
import sys, struct, datetime
import numpy as np
import matplotlib.pyplot as plt

F0 = 10.525e9                   # radar frequency (Hz)
C = 299_792_458.0               # speed of light (m/s)
HZ_PER_MPS = 2 * F0 / C         # 70.2 Hz of Doppler shift per m/s
VREF_MV = 3300.0                # ADC full scale for "RDR1" frames (NUCLEO, 0-3.3 V)
FMIN, FMAX = 3.0, 1000.0        # where we look for the Doppler peak (Hz)
F_VIEW = 300.0                  # x-axis of the spectrum (Hz) -> 0..4.3 m/s
MIN_SNR = 8.0                   # peak must be 8x above the median noise
# frames: "RDR1" + N + FS + N x uint16 (full scale 3.3 V)
#         "RDR2" + N + FS + full scale in uV (uint32) + N x uint16

# --- look (single series per chart, recessive grid, text in ink colours) ---
SERIES = "#2563EB"
INK, MUTED, GRID = "#111827", "#6B7280", "#E5E7EB"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "axes.titlecolor": INK,
    "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlelocation": "left",
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": "white",
})


# ---------------------------------------------------------------- sources
def serial_blocks(port):
    import serial
    ser = serial.Serial(port, 115200, timeout=3)
    ser.reset_input_buffer()
    while True:
        sync = b""
        while sync not in (b"RDR1", b"RDR2"):       # wait for a frame header
            b = ser.read(1)
            if not b:
                print("no data: check the COM port, the USB cable and the code")
                break
            sync = (sync + b)[-4:]
        if sync not in (b"RDR1", b"RDR2"):
            continue
        n, fs = struct.unpack("<HH", ser.read(4))
        full_mv = VREF_MV
        if sync == b"RDR2":
            full_mv = struct.unpack("<I", ser.read(4))[0] / 1000.0
        raw = ser.read(2 * n)
        if len(raw) == 2 * n:
            yield fs, np.frombuffer(raw, dtype="<u2").astype(float), full_mv


def demo_blocks():
    """Fake radar: 42 mV DC + a Doppler tone that drifts, 12-bit ADC."""
    fs, n, k = 5000, 4096, 0
    rng = np.random.default_rng(1)
    while True:
        t = np.arange(n) / fs
        f = 35 + 15 * np.sin(k / 3)                 # 35 +/- 15 Hz -> ~0.5 m/s
        mv = 42 + 3.5 * np.sin(2 * np.pi * f * t) + rng.normal(0, 0.4, n)
        yield fs, np.clip(np.round(mv / VREF_MV * 4095), 0, 4095), VREF_MV
        k += 1


# ---------------------------------------------------------------- analysis
def analyse(fs, adc, full_mv=VREF_MV, bg=None):
    mv = adc * full_mv / 4096.0
    dc = mv.mean()
    x = mv - dc                                     # remove the 42 mV
    n = len(x)
    w = np.hanning(n)
    spec = np.abs(np.fft.rfft(x * w)) * 2 / w.sum() # amplitude in mV
    f = np.fft.rfftfreq(n, 1 / fs)
    band = (f >= FMIN) & (f <= FMAX)
    det = spec if bg is None or len(bg) != len(spec) else np.clip(spec - bg, 0, None)
    i = np.argmax(np.where(band, det, 0))
    # sub-bin refinement (parabola on the 3 points around the peak)
    if 0 < i < len(spec) - 1:
        a, b, c = np.log(det[i - 1:i + 2] + 1e-12)
        i_f = i + 0.5 * (a - c) / (a - 2 * b + c)
    else:
        i_f = i
    fpk = i_f * fs / n
    snr = det[i] / (np.median(spec[band]) + 1e-12)
    # movement level: spectrum energy 5-300 Hz without the mains lines (+/- 3 Hz)
    mains = np.abs(f - 50.0 * np.round(f / 50.0)) <= 3.0
    sel = (f >= 5.0) & (f <= 300.0) & ~mains
    level = float(np.sqrt(np.sum(spec[sel] ** 2)))
    return dict(t=np.arange(n) / fs, x=x, dc=dc, f=f, spec=spec, fpk=fpk,
                apk=spec[i], snr=snr, ok=snr >= MIN_SNR, level=level)


# ---------------------------------------------------------------- display
def main():
    args = sys.argv[1:]
    demo = "--demo" in args
    once = None
    if "--once" in args:                            # save one frame and exit
        once = args[args.index("--once") + 1]
    ports = [a for a in args if not a.startswith("--") and a != once]
    if not demo and not ports:
        print(__doc__); sys.exit(1)
    blocks = demo_blocks() if demo else serial_blocks(ports[0])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.6),
                                   gridspec_kw=dict(height_ratios=[1, 1.4]))
    fig.subplots_adjust(left=0.08, right=0.97, top=0.90, bottom=0.09, hspace=0.62)
    fig.suptitle("10 GHz Doppler radar  ·  IF output sampled directly, no amplifier",
                 x=0.08, ha="left", fontsize=13, fontweight="bold", color=INK)
    l1, = ax1.plot([], [], color=SERIES, lw=1.2)
    ax1.set_title("IF signal, DC removed")
    ax1.set_xlabel("Time (s)"); ax1.set_ylabel("mV")
    l3, = ax2.plot([], [], color="#9CA3AF", lw=1.4, ls="--", label="background (learned)")
    l2, = ax2.plot([], [], color=SERIES, lw=1.8)
    pk, = ax2.plot([], [], "o", ms=8, color=SERIES, mec="white", mew=2)
    ax2.set_title("Spectrum")
    ax2.set_xlabel("Doppler frequency (Hz)"); ax2.set_ylabel("Amplitude (mV)")
    ax2.set_xlim(0, F_VIEW)
    top = ax2.secondary_xaxis("top", functions=(lambda f: f / HZ_PER_MPS,
                                                lambda v: v * HZ_PER_MPS))
    top.set_xlabel("Speed (m/s)", color=MUTED); top.tick_params(colors=MUTED)
    info = ax2.text(0.99, 0.93, "", transform=ax2.transAxes, ha="right", va="top",
                    fontsize=12, color=INK, fontweight="bold")
    note = ax1.text(1.0, 1.04, "", transform=ax1.transAxes, ha="right", va="bottom",
                    fontsize=10, color=MUTED)
    state = {"r": None, "quit": False, "bg": None, "learn": 0, "acc": []}

    def save():
        r = state["r"]
        if r is None:
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fig.savefig(f"radar_{stamp}.png", dpi=200)
        np.savetxt(f"radar_{stamp}.csv", np.column_stack([r["t"], r["x"] + r["dc"]]),
                   delimiter=",", header="time_s,if_mV", comments="", fmt="%.6f")
        print(f"saved radar_{stamp}.png and .csv")

    def on_key(ev):
        if ev.key == "s": save()
        if ev.key == "q": state["quit"] = True
        if ev.key == "b":
            state["learn"], state["acc"] = 5, []
            print("learning the background: keep everything still for 5 blocks...")
        if ev.key == "c":
            state["bg"] = None; print("background cleared")
    fig.canvas.mpl_connect("key_press_event", on_key)
    if once is None:
        plt.ion(); plt.show()

    print("block  DC (mV)  movement level (mV)  peak")
    for k, (fs, adc, full_mv) in enumerate(blocks, 1):
        r = analyse(fs, adc, full_mv, state["bg"])
        state["r"] = r
        pk_txt = f"{r['fpk']:.1f} Hz = {r['fpk'] / HZ_PER_MPS:.2f} m/s" if r["ok"] else "-"
        print(f"{k:5d}  {r['dc']:7.1f}  {r['level']:19.3f}  {pk_txt}", flush=True)
        if state["learn"] > 0:                       # averaging the background
            state["acc"].append(r["spec"]); state["learn"] -= 1
            if state["learn"] == 0:
                state["bg"] = np.mean(state["acc"], axis=0)
                print("background learned: fixed lines will be subtracted")
        if state["bg"] is not None and len(state["bg"]) == len(r["f"]):
            l3.set_data(r["f"], state["bg"])
        else:
            l3.set_data([], [])
        l1.set_data(r["t"], r["x"])
        ax1.set_xlim(0, r["t"][-1])
        lim = max(0.1, 1.15 * np.abs(r["x"]).max())
        ax1.set_ylim(-lim, lim)
        tag = "  ·  learning background..." if state["learn"] else ("  ·  background subtracted" if state["bg"] is not None else "")
        note.set_text(f"DC level {r['dc']:.1f} mV (removed)  ·  movement level {r['level']:.2f} mV{tag}")
        l2.set_data(r["f"], r["spec"])
        ax2.set_ylim(0, max(0.02, 1.2 * r["spec"][r["f"] >= FMIN].max()))
        if r["ok"]:
            v = r["fpk"] / HZ_PER_MPS
            pk.set_data([r["fpk"]], [r["apk"]])
            info.set_text(f"Peak {r['fpk']:.1f} Hz  →  {v:.2f} m/s  ({v * 3.6:.1f} km/h)")
        else:
            pk.set_data([], [])
            info.set_text("No movement detected")
        if once:
            fig.savefig(once, dpi=150); print("saved", once); return
        fig.canvas.draw_idle(); plt.pause(0.05)
        if state["quit"] or not plt.fignum_exists(fig.number):
            break


if __name__ == "__main__":
    main()
