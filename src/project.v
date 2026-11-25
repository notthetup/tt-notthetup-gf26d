/*
 * Copyright (c) 2026 Chinmay Pendharkar
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// 1bit-match: 127-bit bit-stream matched filter.
//
// The window, pattern and threshold are all left-shift registers on clk.
// din passes through a 2-flop synchroniser, then shifts into the window on
// every clock. While cfg_mode is high, cfg_data shifts into the pattern
// (cfg_sel=0) or the threshold (cfg_sel=1, MSB first). Send the pattern in
// the same order it is expected on the stream.
//
// uo[6:0] score  = number of positions where window == pattern (0..127)
// uo[7]   detect = score >= threshold in run mode; in config mode, the bit
//                  shifted out of the selected register (readback)
// uio[0]  seen   = sticky detect, cleared by config mode or reset
// All are registered. A din bit reaches the score 3 clocks after it is sampled.
// The window and pattern have no reset (saves ~3800 um^2 to fit 1x1);
// reset sets the threshold to 127 and clears score, detect and seen.

module tt_um_notthetup_1bit_match (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  localparam N = 127;

  wire din      = ui_in[0];
  wire cfg_data = ui_in[1];
  wire cfg_mode = ui_in[2];
  wire cfg_sel  = ui_in[3];

  reg [1:0]   din_sync;
  reg [N-1:0] window, pattern;
  reg [6:0]   threshold, score;
  reg         detect, seen;

  // Popcount of matching positions as a binary adder tree (heap layout):
  // leaves at node[128..255], root at node[1].
  wire [N-1:0] match = ~(window ^ pattern);
  wire [6:0]   node [1:255];

  genvar i;
  generate
    for (i = 0; i < N; i = i + 1) begin : leaf
      assign node[128+i] = {6'b0, match[i]};
    end
    assign node[255] = 7'd0;  // pad 127 leaves up to 128
    for (i = 1; i < 128; i = i + 1) begin : sum
      assign node[i] = node[2*i] + node[2*i+1];
    end
  endgenerate

  wire [6:0] count = node[1];
  wire       hit   = count >= threshold;

  always @(posedge clk) begin
    din_sync <= {din_sync[0], din};
    window   <= {window[N-2:0], din_sync[1]};
    if (cfg_mode && !cfg_sel) pattern <= {pattern[N-2:0], cfg_data};
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      threshold <= 7'd127;
      score     <= 0;
      detect    <= 0;
      seen      <= 0;
    end else begin
      if (cfg_mode &&  cfg_sel) threshold <= {threshold[5:0], cfg_data};
      score  <= count;
      detect <= cfg_mode ? (cfg_sel ? threshold[6] : pattern[N-1]) : hit;
      seen   <= !cfg_mode && (seen || hit);
    end
  end

  assign uo_out  = {detect, score};
  assign uio_out = {7'b0, seen};
  assign uio_oe  = 8'b0000_0001;

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, ui_in[7:4], uio_in, 1'b0};

endmodule
