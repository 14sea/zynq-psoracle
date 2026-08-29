`timescale 1ns/1ps
// Drives p3_siphash with vectors the Python reference produced; every tag must match.
module tb_p3_siphash;
    reg clk = 0; always #10 clk = ~clk;
    reg rst_n = 0;
    integer fd, n, pass, fail, r;
    reg [127:0] key; reg [639:0] msg; reg [63:0] nonce; reg [127:0] want;
    // the key is a PARAMETER: one DUT per vector would need one module per key, so the
    // bench instantiates with a fixed key and checks only vectors for that key, then
    // re-checks the generic path with a second instance keyed differently.
    localparam [127:0] KEY_A = 128'h0f0e0d0c0b0a09080706050403020100;   // bytes 00..0f LE
    localparam [127:0] KEY_B = 128'h1f1e1d1c1b1a19181716151413121110;   // bytes 10..1f LE
    reg start_a = 0, start_b = 0; wire busy_a, done_a, busy_b, done_b; wire [127:0] tag_a, tag_b;
    p3_siphash #(.KEY(KEY_A), .MSG_WORDS(20)) dut_a (.clk(clk), .rst_n(rst_n), .start(start_a),
        .msg(msg), .nonce(nonce), .busy(busy_a), .done(done_a), .tag(tag_a));
    p3_siphash #(.KEY(KEY_B), .MSG_WORDS(20)) dut_b (.clk(clk), .rst_n(rst_n), .start(start_b),
        .msg(msg), .nonce(nonce), .busy(busy_b), .done(done_b), .tag(tag_b));
    initial begin
        pass = 0; fail = 0;
        #25 rst_n = 1;
        fd = $fopen("tb/siphash_vectors.txt", "r");
        if (fd == 0) begin $display("FAIL: no vectors"); $finish; end
        n = 0;
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%h %h %h %h\n", key, msg, nonce, want);
            if (r == 4) begin
                if (key == KEY_A) begin
                    @(negedge clk); start_a = 1; @(negedge clk); start_a = 0;
                    wait(done_a); @(negedge clk);
                    if (tag_a === want) pass = pass + 1;
                    else begin fail = fail + 1; $display("FAIL A vec %0d: got %h want %h", n, tag_a, want); end
                end else if (key == KEY_B) begin
                    @(negedge clk); start_b = 1; @(negedge clk); start_b = 0;
                    wait(done_b); @(negedge clk);
                    if (tag_b === want) pass = pass + 1;
                    else begin fail = fail + 1; $display("FAIL B vec %0d: got %h want %h", n, tag_b, want); end
                end
                n = n + 1;
            end
        end
        $display("siphash: %0d vectors read, %0d checked, pass=%0d fail=%0d", n, pass + fail, pass, fail);
        if (fail == 0 && pass == n && n >= 40) $display("TB_PASS"); else $display("TB_FAIL");
        $finish;
    end
endmodule
