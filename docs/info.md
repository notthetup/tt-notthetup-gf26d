## How it works

1bit-match looks for a known 127-bit pattern in a stream of bits. On every clock it compares the last 127 bits it received with the pattern and outputs the number of positions that agree, from 0 to 127. A perfect match scores 127 and a perfectly inverted match scores 0. When the score reaches a threshold you set, `detect` goes high.

The pattern and the threshold are programmable. You shift them in serially on one data pin, and you can read the old values back as the new ones go in.

### Pins

| Pin | Name | Direction | Function |
|---|---|---|---|
| `ui[0]` | `din` | in | Stream bit, sampled on every clock |
| `ui[1]` | `cfg_data` | in | Configuration bit |
| `ui[2]` | `cfg_mode` | in | 0 = run, 1 = configure |
| `ui[3]` | `cfg_sel` | in | When configuring, 0 = pattern, 1 = threshold |
| `uo[6:0]` | `score` | out | Number of matching positions, 0 to 127 |
| `uo[7]` | `detect` | out | Run mode: `score` >= threshold. Config mode: readback bit |
| `uio[0]` | `seen` | out | Sticky `detect`, cleared by config mode or reset |

All other pins are unused. The design runs on the project clock at up to 10 MHz.

### Inside

There are three shift registers, all clocked by the project clock and all shifting left.

The window holds the last 127 stream bits. `din` passes through a two-flop synchroniser and then shifts into the window on every clock, whatever the mode. The synchroniser means `din` can come from a source that is not tied to the project clock, such as a comparator.

The pattern holds 127 bits. It shifts in `cfg_data` on each clock where `cfg_mode` = 1 and `cfg_sel` = 0, and holds otherwise.

The threshold holds 7 bits. It shifts in `cfg_data`, MSB first, on each clock where `cfg_mode` = 1 and `cfg_sel` = 1, and holds otherwise.

An adder tree counts the positions where the window and pattern agree. That count is registered as `score`, and compared with the threshold to give `detect`.

### Loading the pattern and threshold

Set `cfg_mode` = 1 and `cfg_sel` = 0, then clock in the 127 pattern bits in the order you expect them to arrive on `din`. The window and pattern shift the same way, so a pattern sent in stream order lines up with the window without any reversal. To set the threshold, use `cfg_sel` = 1 and clock in 7 bits, MSB first.

Each register keeps only the last bits shifted into it. Sending too many bits is harmless, and you can reload the threshold without touching the pattern, or the other way round.

### Readback

In config mode `uo[7]` stops showing `detect`. Instead, on each clock it shows the bit that just fell off the end of the selected register. Loading a new pattern therefore shifts the old pattern out on `uo[7]`, in the order it was sent. The threshold works the same way. To check what is stored without changing it, shift the value out and send the same value back in.

### Scoring and detection

`score` is valid on every clock in run mode once the window holds 127 stream bits. `detect` is high on any clock where `score` >= threshold, so a threshold of 0 detects everything and a threshold of 127 detects only an exact match.

`detect` lasts one clock per qualifying score. At 10 MHz that is 100 ns, which is too short for a slow host to catch. `seen` on `uio[0]` solves this. It goes high with the first detection and stays high until the next config-mode clock or reset.

### Timing

All outputs are registered. A `din` bit reaches `score` 3 clocks after it is sampled: 2 clocks in the synchroniser and 1 in the output register. After you stream a full pattern, clock 3 more times before reading the score for it.

### Reset and power-up

Reset sets the threshold to 127 and clears `score`, `detect` and `seen`. It does not touch the window, the pattern or the synchroniser. Leaving out reset on those 256 flops saved enough area to fit the design in one tile.

So after power-up the pattern is random until you load it, and the score means nothing until the window has received 127 stream bits. Load the pattern before trusting `detect`.

## How to test

These examples use the MicroPython SDK on the Tiny Tapeout demo board, with the RP2040 driving the inputs (`ASIC_RP_CONTROL` mode). Stop the auto clock and step it by hand, so every input change happens between clock edges:

```python
tt.clock_project_stop()

def step(din=0, cfg_data=0, cfg_mode=0, cfg_sel=0):
    tt.ui_in.value = din | cfg_data << 1 | cfg_mode << 2 | cfg_sel << 3
    tt.clock_project_once()
    return int(tt.uo_out.value)
```

### Detect a pattern

```python
import random
pattern = [random.getrandbits(1) for _ in range(127)]   # in stream order

for b in pattern:                         # load the pattern
    step(cfg_data=b, cfg_mode=1, cfg_sel=0)

for b in pattern:                         # stream it back
    step(din=b)
for _ in range(3):                        # 3 clocks of latency
    out = step()
print(out & 0x7F, out >> 7)               # 127 1
```

The threshold is 127 after reset, so only an exact match detects. To change it, for example to 100:

```python
for k in range(6, -1, -1):
    step(cfg_data=(100 >> k) & 1, cfg_mode=1, cfg_sel=1)
```

With a threshold of 100, flip up to 27 bits of the streamed pattern and `detect` still goes high. Flip 28 and it does not.

### Read back the pattern

```python
old = [step(cfg_data=b, cfg_mode=1, cfg_sel=0) >> 7 for b in pattern]
print(old == pattern)                     # True
```

### Run the clock freely

Once the pattern and threshold are loaded, you can start the clock with `tt.clock_project_PWM(freq)` and drive `din` from another source. Watch `seen` on `uio[0]` for detections, and enter config mode for one clock to clear it.

## External hardware

None. The demo board's RP2040 can drive every input and read every output. For a live stream, a logic signal at the demo board's input level, such as a comparator output, can drive `din` on `ui[0]`.
