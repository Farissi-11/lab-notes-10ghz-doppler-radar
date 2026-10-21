# Lab Notes – 10 GHz Doppler radar, part 1: sampling the IF output with an STM32

An HB100-type 10.525 GHz Doppler module, characterised with a multimeter, then its IF output sampled directly (no amplifier) by the ADC of a NUCLEO-F401RE board. The spectrum and the speed are computed on a PC.

This repository contains the firmware (source and ready-to-flash binary), the PC scripts and the raw measurement, so that every number can be checked and reproduced.

## Results

| Measurement | Value |
|---|---|
| Supply at the module pins | 5.00 V, 30–39 mA |
| +5V to GND, module unpowered | 46.5 Ω |
| Diode test, IF to GND | 240 mV in both directions (balanced two-diode mixer) |
| IF DC level at rest (ADC) | 44–45 mV |
| Mains pickup on the IF line, at rest | 1.94 mV at 50 Hz, 0.73 mV at 150 Hz, 0.10 mV at 250 Hz |
| Noise floor of the spectrum | ≈ 31 µV per 1.22 Hz bin |
| Doppler signal of a moving aluminium sheet, no amplifier | < 1 mV |

Doppler shift at 10.525 GHz: fd = 2·v·f0/c = **70.2 Hz per m/s**.

Main takeaways:

1. **The mains is a free frequency reference.** The first firmware, clocked by the internal RC oscillator, showed the mains lines at 48.7 Hz and 146 Hz: a 2.6 % sample-rate error. Clocking the STM32 from the 8 MHz quartz of the on-board ST-LINK put them exactly at 50.0 and 150.0 Hz.
2. **Without an amplifier, the Doppler signal is buried.** The IF signal of a moving target stays below 1 mV, while the 50 Hz pickup (a 3.5 mV peak-to-peak square wave) reaches 1.9 mV in the spectrum. A target at 0.71 m/s gives exactly 50 Hz of Doppler shift, so the mains cannot simply be filtered out.
3. Part 2 will add a low-noise amplifier between the IF pin and the ADC.

## Measurement chain

| Item | Value |
|---|---|
| Radar | HB100-type module, 10.525 GHz, supplied by a lab power supply at 5.00 V |
| Board | NUCLEO-F401RE (MB1136 rev C), powered and read over USB |
| ADC input | A0 = PA0 (ADC1_IN0), 12 bits, 0–3.3 V, sampling time 144 cycles |
| Sample | sum of 16 conversions (≈ 0.2 mV resolution with the noise) |
| Sample rate | 5 000 samples/s, timed by the Cortex-M4 cycle counter |
| Clock | 8 MHz from the ST-LINK (HSE bypass), PLL to 84 MHz |
| Block | 4 096 samples (0.82 s), then sent to the PC (0.71 s) |
| Link | USART2 → ST-LINK virtual COM port, 115 200 bit/s, 8N1 |

Wiring:

| Radar pin | Goes to |
|---|---|
| +5V | lab power supply + (5.00 V) |
| GND | lab power supply − **and** a GND pin of the NUCLEO (common ground) |
| IF | A0 of the NUCLEO |

⚠️ Never connect the radar +5V (or the lab supply) to the NUCLEO pins: its inputs accept 3.3 V maximum.

## Quick start

**1. Flash the board, no toolchain needed.** Plug the NUCLEO into the PC: a USB drive named `NOD_F401RE` appears. Copy `firmware/radar_nucleo_f401re.bin` onto it. After the copy the board restarts:

- 3 short flashes of the green LED LD2 = quartz clock found;
- 1 long flash = no quartz, internal RC oscillator used (sample rate a few % off);
- then LD2 toggles after each block (every ≈ 1.5 s).

**2. Run the PC script.**

```bash
pip install -r requirements.txt
python host/radar_spectrum.py COM5            # Windows (see the COM port in Device Manager)
python3 host/radar_spectrum.py /dev/ttyACM0   # Linux
python host/radar_spectrum.py --demo          # without the board
```

Keys in the window: `s` saves a PNG and a CSV of the current block, `b` learns the background (5 blocks, nothing moving) and subtracts it, `c` clears it, `q` quits. The console prints one line per block with the DC level and a "movement level" (spectrum energy from 5 to 300 Hz, mains lines excluded).

**3. Recompute the numbers of this note from the saved capture.**

```bash
python host/analyze_capture.py data/if_at_rest_2026-10-21_132718.csv
```

## Frame format (board → PC)

Little-endian, one frame per block:

```
"RDR2" | N (uint16) | FS (uint16, Hz) | full scale (uint32, µV) | N × uint16 samples
```

Voltage of a sample: `mV = value × full_scale_µV / 1000 / 4096`. With 16 conversions per sample, full scale = 3.3 V / 16 = 206 250 µV. `radar_spectrum.py` also reads the older "RDR1" frames (no full-scale field, 0–3.3 V).

## Build the firmware from source

Bare-metal C, no CubeMX or HAL. Needs `arm-none-eabi-gcc` and `make`:

```bash
cd firmware
make        # downloads the CMSIS headers the first time, then builds radar_nucleo_f401re.bin
```

The binary in this repository was built this way.

## Repository content

```
firmware/
  radar_nucleo.c               firmware source (clock, ADC, UART, startup code)
  stm32f401re.ld               linker script (512 KB flash, 96 KB RAM)
  Makefile                     build with arm-none-eabi-gcc
  radar_nucleo_f401re.bin      ready-to-flash binary (drag and drop)
host/
  radar_spectrum.py            live signal, spectrum, Doppler peak and speed
  analyze_capture.py           recomputes the numbers of the note from a CSV
data/
  if_at_rest_2026-10-21_132718.csv   one block at rest (4 096 samples, time_s, if_mV)
```

## Limitations

- No amplifier: the Doppler signal of the test target is below the mains pickup.
- The 50 Hz pickup is most likely a ground loop between the lab supply, the board and the PC; it was not removed in this part.
- One capture at rest is published; the moving-target result is a level comparison, not a clean Doppler line.
- Sampling and sending alternate, so the board "sees" about 54 % of the time.

## License

- Code: MIT (see `LICENSE`).
- Data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- The CMSIS headers downloaded by the Makefile are © STMicroelectronics and Arm, under the Apache-2.0 license; they are not part of this repository.
