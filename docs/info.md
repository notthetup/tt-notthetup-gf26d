<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

1bit-match is a digital matched filter for a bit stream. It compares the most recent 127 input bits with a programmable 127-bit pattern and outputs, on every clock, the number of positions that match (0 to 127). An exact match scores 127 and an exact inversion scores 0. `detect` goes high when the score is greater than or equal to a programmable 7-bit threshold.

Everything runs on the project clock. There are three shift registers:

- **window** (127 bits): shifts `din` in on every clock, in both run and config mode, after a 2-flop synchroniser so `din` may come from a source that is not synchronised to the clock.
- **pattern** (127 bits): shifts `cfg_data` in on every clock while `cfg_mode` = 1 and `cfg_sel` = 0.
- **threshold** (7 bits): shifts `cfg_data` in, MSB first, on every clock while `cfg_mode` = 1 and `cfg_sel` = 1.

The pattern and the window shift the same way, so you program the pattern by sending it in the same order you expect it on `din`. The first pattern bit sent lines up with the oldest bit in the window. Each register keeps only the last bits shifted in, so sending extra bits is harmless, and the pattern and threshold can be loaded independently.

All outputs are registered. A `din` bit reaches the score 3 clocks after it is sampled: 2 clocks through the synchroniser and 1 for the output register. The score is always live, so it is meaningless in config mode and until the window holds 127 stream bits after power-up.

`seen` on `uio[0]` is a sticky copy of `detect`: it goes high with the first detection and stays high until the next config-mode clock or reset. Use it when the clock runs too fast to catch the one-clock `detect` pulse.

In config mode, `uo[7]` reads back instead of detecting: each clock it shows the bit shifted out of the selected register, so loading a new pattern or threshold shifts out the old one in the order it was sent (like SPI MISO).

Reset sets the threshold to 127 (exact match only) and clears the score, `detect` and `seen`. The window and pattern have no reset, to save area: the window refills itself within 127 clocks, and the pattern must be loaded after power-up.

| Pin | Name | Function |
|---|---|---|
| `ui[0]` | `din` | Stream input bit, sampled every clock |
| `ui[1]` | `cfg_data` | Configuration data bit |
| `ui[2]` | `cfg_mode` | 1 = config mode (shift `cfg_data`, `uo[7]` reads back), 0 = run |
| `ui[3]` | `cfg_sel` | In config mode: 0 = pattern, 1 = threshold |
| `uo[6:0]` | `score` | Number of matching positions, 0 to 127 |
| `uo[7]` | `detect` | Run mode: `score` >= threshold. Config mode: readback bit |
| `uio[0]` | `seen` | Sticky `detect`, cleared by config mode or reset |

## How to test

On the demo board, stop the auto clock and step it from MicroPython while the RP2040 drives the inputs (`ASIC_RP_CONTROL` mode):

```python
tt.clock_project_stop()

def step(din=0, cfg_data=0, cfg_mode=0, cfg_sel=0):
    tt.ui_in.value = din | cfg_data << 1 | cfg_mode << 2 | cfg_sel << 3
    tt.clock_project_once()

pattern = [...]                     # 127 bits, in stream order
for b in pattern:
    step(cfg_data=b, cfg_mode=1, cfg_sel=0)
# threshold is 127 after reset; to change it, shift 7 bits MSB first:
# for k in range(6, -1, -1): step(cfg_data=(100 >> k) & 1, cfg_mode=1, cfg_sel=1)

for b in pattern:                   # stream the pattern itself
    step(din=b)
for _ in range(3):                  # 3 clocks of latency
    step()
print(int(tt.uo_out.value) & 0x7F, int(tt.uo_out.value) >> 7)   # 127 1
```

After loading, you can also run the clock with `tt.clock_project_PWM(freq)` and feed `din` from another source, and watch `seen` on `uio[0]` for detections.

## External hardware

None required. The RP2040 on the demo board can drive all inputs and read the outputs.
