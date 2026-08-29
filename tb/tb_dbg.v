module tb_dbg;
    always @(tb_p3_core.dut.gate.state or tb_p3_core.dut.gate.nonce or tb_p3_core.dut.gate.fault_code or tb_p3_core.rst_n or tb_p3_core.dut.gate.arm_strobe)
        $display("t=%0t rst=%b state=%0d nonce=%h tag_ok=%b fault=%0d rec=%b cfg=%b scorer_busy=%b arm=%b",
                 $time, tb_p3_core.rst_n, tb_p3_core.dut.gate.state, tb_p3_core.dut.gate.nonce, tb_p3_core.dut.gate.tag_ok,
                 tb_p3_core.dut.gate.fault_code, tb_p3_core.dut.gate.recovery_required,
                 tb_p3_core.dut.gate.configuration_valid_hw, tb_p3_core.dut.scorer_busy, tb_p3_core.dut.gate.arm_strobe);
endmodule
