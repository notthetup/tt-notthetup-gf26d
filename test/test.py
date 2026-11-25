# SPDX-FileCopyrightText: © 2026 Chinmay Pendharkar
# SPDX-License-Identifier: Apache-2.0

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

N = 127
MASK = (1 << N) - 1
SYNC = 2  # din synchroniser stages


class Harness:
    """Drives the DUT one clock at a time and checks every output against
    an independent model of the synchroniser, window, pattern and threshold.

    The synchroniser, window and pattern have no reset, so they start unknown
    (X). Unknown model values are None, and outputs that depend on them are
    not checked until enough known bits have been shifted in."""

    def __init__(self, dut):
        self.dut = dut
        self.sync = [None] * SYNC
        self.window = self.pattern = 0
        self.win_known = self.pat_known = 0  # consecutive known bits shifted in

    def shift_din(self, din):
        b = self.sync[-1]
        self.sync = [din] + self.sync[:-1]
        if b is None:
            self.win_known = 0
        else:
            self.window = ((self.window << 1) | b) & MASK
            self.win_known += 1

    async def reset(self):
        dut = self.dut
        dut.ena.value = 1
        dut.ui_in.value = 0
        dut.uio_in.value = 0
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 3)
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        for _ in range(3):  # din (0) keeps moving through sync and window
            self.shift_din(0)
        self.threshold = 127
        self.seen = 0

    def expected_score(self):
        if min(self.win_known, self.pat_known) < N:
            return None
        return N - bin((self.window ^ self.pattern) & MASK).count("1")

    async def step(self, din=0, cfg_data=0, cfg_mode=0, cfg_sel=0):
        dut = self.dut
        dut.ui_in.value = din | cfg_data << 1 | cfg_mode << 2 | cfg_sel << 3

        # Outputs registered at this edge come from the pre-edge state.
        score = self.expected_score()
        hit = None if score is None else int(score >= self.threshold)
        if not cfg_mode:
            uo7 = hit
        elif cfg_sel:
            uo7 = (self.threshold >> 6) & 1
        else:
            uo7 = (self.pattern >> (N - 1)) & 1 if self.pat_known >= N else None
        if cfg_mode:
            self.seen = 0
        elif self.seen != 1:
            self.seen = hit

        self.shift_din(din)
        if cfg_mode and not cfg_sel:
            self.pattern = ((self.pattern << 1) | cfg_data) & MASK
            self.pat_known += 1
        if cfg_mode and cfg_sel:
            self.threshold = ((self.threshold << 1) | cfg_data) & 0x7F

        await RisingEdge(dut.clk)
        await ReadOnly()
        out = str(dut.uo_out.value)  # MSB first: uo[7], then score[6:0]
        if score is not None:
            assert out[1:] == f"{score:07b}", f"score {out[1:]}, expected {score:07b}"
        if uo7 is not None:
            assert out[0] == str(uo7), f"uo[7] {out[0]}, expected {uo7} (mode {cfg_mode}, score {score}, thr {self.threshold})"
        if self.seen is not None:
            assert str(dut.uio_out.value)[-1] == str(self.seen), f"seen {dut.uio_out.value}, expected {self.seen}"
        assert dut.uio_oe.value.to_unsigned() == 1
        await FallingEdge(dut.clk)
        return score, uo7

    async def load_pattern(self, bits):
        """Shift in a pattern; returns the bits read back from uo[7]."""
        return [(await self.step(din=random.getrandbits(1), cfg_data=b, cfg_mode=1, cfg_sel=0))[1] for b in bits]

    async def load_threshold(self, t):
        """Shift in a threshold MSB first; returns the old threshold read back."""
        old = 0
        for k in range(6, -1, -1):
            old = old << 1 | (await self.step(din=random.getrandbits(1), cfg_data=(t >> k) & 1, cfg_mode=1, cfg_sel=1))[1]
        return old

    async def stream(self, bits):
        """Stream bits, then flush the synchroniser and return the score and
        detect for the window holding exactly these bits."""
        for b in bits:
            await self.step(din=b)
        for _ in range(SYNC):
            await self.step(din=0)
        return await self.step(din=0)

    async def prime(self):
        """Fill the pattern and window with known random bits."""
        await self.load_pattern(rand_bits())
        await self.stream(rand_bits())


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
    assert await h.stream(p) == (127, 1)  # threshold 127 from reset


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
async def test_readback(dut):
    """In config mode uo[7] shifts out the old contents of the selected register."""
    h = await setup(dut)
    p, q = rand_bits(), rand_bits()
    await h.load_pattern(p)
    assert await h.load_pattern(q) == p
    assert await h.load_threshold(0b1010011) == 127  # reset value
    assert await h.load_threshold(5) == 0b1010011
    assert await h.load_pattern(p) == q


@cocotb.test()
async def test_seen_is_sticky(dut):
    """seen latches a detection until config mode clears it."""
    h = await setup(dut)
    p = rand_bits()
    await h.load_pattern(p)
    assert h.seen == 0
    assert await h.stream(p) == (127, 1)
    assert h.seen == 1
    for b in rand_bits(200):
        await h.step(din=b)
    assert h.seen == 1  # random stream: detect is low again, seen holds
    await h.step(cfg_mode=1, cfg_sel=1)  # a config clock (shifts a 0 into the threshold)
    assert h.seen == 0


@cocotb.test()
async def test_reset_sets_threshold(dut):
    h = await setup(dut)
    await h.prime()
    await h.load_threshold(5)
    for b in rand_bits(50):
        await h.step(din=b)
    await h.reset()
    # Threshold back to 127: a random window no longer detects. Window and
    # pattern are kept, and the harness checks the score against them.
    score, detect = await h.step()
    assert score is not None and detect == 0 and h.seen == 0
