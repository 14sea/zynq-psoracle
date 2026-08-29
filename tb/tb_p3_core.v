`timescale 1ns/1ps
// Integration bench: AXI-Lite master -> p3_core (register file + gate + scorer) with six
// LUT6 models. Every negative of p3_architecture §6 L1 and every positive, in one run.
module tb_p3_core;
    `include "arm_fixture.vh"
    reg clk = 0; always #10 clk = ~clk;
    reg rst_n = 0;
    reg [15:0] awaddr = 0, araddr = 0; reg awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    reg [31:0] wdata = 0; wire awready, wready, bvalid, arready, rvalid; wire [1:0] bresp, rresp; wire [31:0] rdata;
    wire [5:0] vector; wire [5:0] lut_q;
    // LUT6 models: O = INIT[{I5..I0}], vector[0] = I0. Continuous assigns from scalar regs —
    // an always @* over a memory array is not reliably sensitive to its elements in iverilog.
    reg [63:0] init0, init1, init2, init3, init4, init5;
    assign lut_q = {init5[vector], init4[vector], init3[vector], init2[vector], init1[vector], init0[vector]};

    p3_core #(.KEY(KEY_A), .NONCE_SEED(SEED)) dut (
        .clk(clk), .rst_n(rst_n),
        .s_awaddr(awaddr), .s_awvalid(awvalid), .s_awready(awready),
        .s_wdata(wdata), .s_wstrb(4'hF), .s_wvalid(wvalid), .s_wready(wready),
        .s_bresp(bresp), .s_bvalid(bvalid), .s_bready(bready),
        .s_araddr(araddr), .s_arvalid(arvalid), .s_arready(arready),
        .s_rdata(rdata), .s_rresp(rresp), .s_rvalid(rvalid), .s_rready(rready),
        .vector(vector), .lut_q(lut_q));

    integer fails = 0;
    task check(input cond, input [255:0] what); begin
        if (!cond) begin fails = fails + 1; $display("FAIL: %0s   [rdata=%h rresp=%b bresp=%b t=%0t]", what, last_rdata, last_rresp, last_bresp, $time); end
    end endtask

    reg [1:0] last_bresp, last_rresp; reg [31:0] last_rdata;
    task wr(input [15:0] a, input [31:0] d); begin
        @(negedge clk); awaddr = a; wdata = d; awvalid = 1; wvalid = 1;
        while (!(awready && wready)) @(negedge clk);
        @(negedge clk); awvalid = 0; wvalid = 0;
        while (!bvalid) @(negedge clk);
        last_bresp = bresp; @(negedge clk);
    end endtask
    task rd(input [15:0] a); begin
        @(negedge clk); araddr = a; arvalid = 1;
        while (!arready) @(negedge clk);
        @(negedge clk); arvalid = 0;
        while (!rvalid) @(negedge clk);
        last_rdata = rdata; last_rresp = rresp; @(negedge clk);
    end endtask
    task stage(input [767:0] p); integer i; begin
        for (i = 0; i < 24; i = i + 1) wr(16'h2100 + 4*i, p[(23-i)*32 +: 32]);
    end endtask
    task arm; begin wr(16'h2000, 32'h40); end endtask
    task wait_gate; begin repeat (5) @(negedge clk); rd(16'h2004); while (last_rdata[0]) rd(16'h2004); end endtask
    task wait_scorer; begin rd(16'h2004); while (last_rdata[3]) rd(16'h2004); end endtask
    task reset; begin
        @(negedge clk); awvalid = 0; wvalid = 0; arvalid = 0;
        rst_n = 0; repeat (3) @(negedge clk); rst_n = 1; repeat (2) @(negedge clk);
    end endtask
    task expect_nonce(input [63:0] n, input [255:0] what); begin
        rd(16'h202C); check(last_rdata == n[31:0], what); rd(16'h2030); check(last_rdata == n[63:32], what);
    end endtask
    task expect_status(input v, input f, input tagok, input rec, input [3:0] fcode, input [255:0] what); begin
        rd(16'h2004);
        check(last_rdata[2] == v && last_rdata[1] == f && last_rdata[6] == tagok && last_rdata[7] == rec
              && last_rdata[8] == 1'b1 && last_rdata[31:27] == 0, what);
        rd(16'h2008); check(last_rdata[3:0] == fcode, what);
    end endtask
    integer i; reg [31:0] hb0;
    initial begin
        init0 = INIT0; init1 = INIT1; init2 = INIT2; init3 = INIT3; init4 = INIT4; init5 = INIT5;
        reset;
        // liveness + heartbeat + SLVERR on undecoded
        rd(16'h2004); check(last_rdata != 0 && last_rdata[8] == 1, "alive bit");
        rd(16'h2028); hb0 = last_rdata; rd(16'h2028); check(last_rdata > hb0, "heartbeat advances");
        rd(16'h200C); check(last_rresp == 2'b10, "undecoded read is SLVERR");
        rd(16'h2100); check(last_rresp == 2'b10, "staging is write-only");
        wr(16'h2010, 32'h1); check(last_bresp == 2'b10, "score regs not writable");
        expect_nonce(N0, "nonce = seed after reset");
        // 1. VALID1: verifies, sweeps, arms, scores TRAIN_COUNT for every LUT
        stage(VALID1); arm; wait_gate; expect_status(1, 0, 1, 0, 0, "VALID1 armed");
        rd(16'h2200); check(last_rdata == C1[255:224], "hw_commit = C1");
        rd(16'h2240); check(last_rdata == INIT0[63:32], "readout table0 hi"); rd(16'h2244); check(last_rdata == INIT0[31:0], "readout table0 lo");
        wait_scorer; rd(16'h2004); check(last_rdata[4] == 1, "scorer done");
        for (i = 0; i < 6; i = i + 1) begin rd(16'h2010 + 4*i); check(last_rdata == 40, "score = TRAIN_COUNT"); end
        expect_nonce(N1, "nonce stepped after VALID1");
        // 2. REPLAY of VALID1 on the stepped nonce -> AUTH fault, latch cleared
        stage(VALID1); arm; wait_gate; expect_status(0, 1, 0, 1, 13, "replay -> F_ARM_AUTH");
        rd(16'h2004); check(last_rdata[5] == 0, "scorer disarmed after fault");
        // 3. a VALID2 after the fault is refused (recovery required; nonce unchanged)
        stage(VALID2); arm; wait_gate; expect_status(0, 1, 0, 1, 13, "ARM after fault refused");
        expect_nonce(N2, "nonce not consumed by a refused ARM");
        // 4. fresh reset: VALID1 then VALID2 (second candidate on n1)
        reset; stage(VALID1); arm; wait_gate; wait_scorer; expect_status(1, 0, 1, 0, 0, "VALID1 again");
        stage(VALID2); arm; wait_gate; expect_status(1, 0, 1, 0, 0, "VALID2 on stepped nonce armed");
        rd(16'h2200); check(last_rdata == C2[255:224], "hw_commit = C2");
        wait_scorer;
        // 5. UNSIGNED (tag zero) -> AUTH
        reset; stage(UNSIGNED); arm; wait_gate; expect_status(0, 1, 0, 1, 13, "unsigned -> F_ARM_AUTH");
        // 6. WRONG_COMMIT (tag for another candidate) -> AUTH
        reset; stage(WRONG_COMMIT); arm; wait_gate; expect_status(0, 1, 0, 1, 13, "wrong commit -> F_ARM_AUTH");
        // 7. WRONG_TABLE (correctly signed, fabric differs) -> tag_ok but F_ARM_TABLE, never armed
        reset; stage(WRONG_TABLE); arm; wait_gate; expect_status(0, 1, 1, 1, 15, "wrong table -> F_ARM_TABLE");
        rd(16'h2004); check(last_rdata[5] == 0 && last_rdata[4] == 0, "no score after table mismatch");
        // 8. a fabric that differs from the base (candidate never landed) with a valid signature
        reset; init0 = INIT0 ^ 64'h4; stage(VALID1); arm; wait_gate; expect_status(0, 1, 1, 1, 15, "candidate not in fabric -> F_ARM_TABLE");
        init0 = INIT0;
        if (fails == 0) $display("TB_PASS"); else $display("TB_FAIL (%0d)", fails);
        $finish;
    end
endmodule
