# SPDX-FileCopyrightText: © 2026 Chinmay Pendharkar
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

N = 127
MASK = (1 << N) - 1


class Harness:
    """Drives the DUT one clock at a time and checks every output against
    an independent model of the window, pattern and threshold.

    The window and pattern have no reset, so they are unknown (X) until
    127 bits have been shifted into each. The score is only checked once
    both are known; detect is also checked whenever it is forced low."""

    def __init__(self, dut):
        self.dut = dut
        self.window = self.pattern = 0
        self.win_known = self.pat_known = 0  # bits shifted in since power-up

    async def reset(self):
        dut = self.dut
        dut.ena.value = 1
        dut.ui_in.value = 0
        dut.uio_in.value = 0
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 3)
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        # The window has no reset and keeps shifting din (0) during reset;
        # the pattern keeps its contents.
        self.window = (self.window << 3) & MASK
        self.win_known += 3
        self.threshold = 0

    def expected_score(self):
        return N - bin((self.window ^ self.pattern) & MASK).count("1")

    async def step(self, din=0, cfg_data=0, cfg_mode=0, cfg_sel=0):
        dut = self.dut
        dut.ui_in.value = din | cfg_data << 1 | cfg_mode << 2 | cfg_sel << 3

        # Outputs registered at this edge come from the pre-edge state.
        known = min(self.win_known, self.pat_known) >= N
        score = self.expected_score() if known else None
        detect = 0 if cfg_mode else (int(score >= self.threshold) if known else None)

        self.window = ((self.window << 1) | din) & MASK
        self.win_known += 1
        if cfg_mode and not cfg_sel:
            self.pattern = ((self.pattern << 1) | cfg_data) & MASK
            self.pat_known += 1
        if cfg_mode and cfg_sel:
            self.threshold = ((self.threshold << 1) | cfg_data) & 0x7F

        await RisingEdge(dut.clk)
        await ReadOnly()
        out = str(dut.uo_out.value)  # MSB first: detect, then score[6:0]
        if score is not None:
            assert out[1:] == f"{score:07b}", f"score {out[1:]}, expected {score:07b}"
        if detect is not None:
            assert out[0] == str(detect), f"detect {out[0]}, expected {detect} (score {score}, thr {self.threshold})"
        assert dut.uio_oe.value.to_unsigned() == 0
        await FallingEdge(dut.clk)
        return score, detect

    async def load_pattern(self, bits):
        for b in bits:
            await self.step(din=random.getrandbits(1), cfg_data=b, cfg_mode=1, cfg_sel=0)

    async def load_threshold(self, t):
        for k in range(6, -1, -1):
            await self.step(din=random.getrandbits(1), cfg_data=(t >> k) & 1, cfg_mode=1, cfg_sel=1)

    async def stream(self, bits):
        """Stream bits, then one extra clock so the last bit's score is out."""
        for b in bits:
            await self.step(din=b)
        return await self.step(din=0)


    async def prime(self):
        """Fill the pattern and window with known random bits."""
        await self.load_pattern(rand_bits())
        for b in rand_bits():
            await self.step(din=b)


def rand_bits(n=N):
    return [random.getrandbits(1) for _ in range(n)]


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())
    h = Harness(dut)
    await h.reset()
    return h


@cocotb.test()
async def test_random_stream(dut):
    """Score matches an independent count on every clock of a random stream."""
    h = await setup(dut)
    await h.load_pattern(rand_bits())
    await h.load_threshold(random.randint(60, 90))
    for b in rand_bits(1000):
        await h.step(din=b)


@cocotb.test()
async def test_exact_match(dut):
    h = await setup(dut)
    p = rand_bits()
    await h.load_pattern(p)
    await h.load_threshold(127)
    assert await h.stream(p) == (127, 1)


@cocotb.test()
async def test_inverse(dut):
    h = await setup(dut)
    p = rand_bits()
    await h.load_pattern(p)
    await h.load_threshold(1)
    assert await h.stream([1 - b for b in p]) == (0, 0)


@cocotb.test()
async def test_threshold_edge(dut):
    """Detect fires when score == threshold and not at threshold + 1."""
    h = await setup(dut)
    p = rand_bits()
    await h.load_pattern(p)
    s = list(p)
    for k in random.sample(range(N), 20):
        s[k] ^= 1  # score of s against p is 107
    for thr, want in ((106, 1), (107, 1), (108, 0)):
        await h.load_threshold(thr)
        assert await h.stream(s) == (107, want)


@cocotb.test()
async def test_reprogram_pattern(dut):
    h = await setup(dut)
    a, b = rand_bits(), rand_bits()
    await h.load_pattern(a)
    await h.load_threshold(127)
    assert await h.stream(a) == (127, 1)
    await h.load_pattern(b)
    score, detect = await h.stream(a)
    assert score < 127 and detect == 0
    assert await h.stream(b) == (127, 1)


@cocotb.test()
async def test_threshold_only_keeps_pattern(dut):
    h = await setup(dut)
    p = rand_bits()
    await h.load_pattern(p)
    await h.load_threshold(100)
    await h.load_threshold(127)
    assert await h.stream(p) == (127, 1)


@cocotb.test()
async def test_no_detect_in_config_mode(dut):
    """Threshold 0 after reset: detect is high in run mode, low in config mode."""
    h = await setup(dut)
    await h.prime()
    assert (await h.step())[1] == 1
    for _ in range(20):
        assert (await h.step(din=random.getrandbits(1), cfg_mode=1, cfg_sel=random.getrandbits(1)))[1] == 0
    assert (await h.step())[1] == 1


@cocotb.test()
async def test_reset_clears_threshold(dut):
    h = await setup(dut)
    await h.load_pattern(rand_bits())
    await h.load_threshold(127)
    for b in rand_bits(50):
        await h.step(din=b)
    score, detect = await h.step()
    assert detect == 0  # threshold 127 with a random window
    await h.reset()
    # Threshold cleared to 0, so detect is high; window and pattern are kept
    # and the harness checks the score against them.
    score, detect = await h.step()
    assert score is not None and detect == 1
