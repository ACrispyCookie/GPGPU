"""Guard ownership boundaries of the MMIO/CSR/lifecycle sibling split."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "hw/gpgpu/control"


def source(path):
    assert path.is_file(), f"Missing required control module: {path.name}"
    text = path.read_text()
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)


class ControlOwnershipTests(unittest.TestCase):
    def test_controller_is_renamed_to_mmio(self):
        self.assertFalse((CONTROL / "GPGPUController.sv").exists())
        self.assertRegex(source(CONTROL / "GPGPUMMIO.sv"), r"module\s+GPGPUMMIO\b")

    def test_mmio_has_no_individual_register_or_execution_side_effects(self):
        text = source(CONTROL / "GPGPUMMIO.sv")
        self.assertNotRegex(text, r"`REG_\w+|irq_enable|completion_pending|acknowledge_done|write_irq_enable")
        self.assertNotRegex(text, r"\bGPGPURegs\b|\bo_start\b|\bo_stop\b|\bo_clear_stopped\b|SP_PER_SM")
        for field in ("o_csr_write_fire", "i_csr_rdata", "i_csr_status"):
            self.assertIn(field, text)
        self.assertIn("MemoryInterface.master", text)

    def test_registers_own_all_csrs_without_a_second_transaction_protocol(self):
        text = source(CONTROL / "GPGPURegs.sv")
        for name in ("REG_INFO", "REG_CONTROL", "REG_STATUS", "REG_IRQ_ENABLE", "REG_IRQ_STATUS"):
            self.assertIn("`" + name, text)
        self.assertIn("irq_enable", text)
        self.assertIn("completion_pending", text)
        self.assertNotRegex(text, r"\w*(?:req_valid|req_ready|rsp_valid|rsp_ready)\w*|current_state|next_state")
        self.assertNotRegex(text, r"i_core_complete|`CORE_(?:IDLE|RESET|RUNNING)|MemoryInterface")
        self.assertIn("i_complete_pulse", text)

    def test_device_instantiates_siblings_and_preserves_public_ports(self):
        text = source(ROOT / "hw/gpgpu/GPGPUDevice.sv")
        for name in ("GPGPUMMIO", "GPGPURegs", "GPGPUState"):
            self.assertRegex(text, rf"\b{name}\b")
        self.assertNotRegex(text, r"`REG_\w+")
        header = text[:text.index(");")]
        actual = set(re.findall(r"\b[io]_\w+\b|\bclk\b|\brst_n\b", header))
        self.assertEqual(actual, {
            "clk", "rst_n", "i_req_valid", "o_req_ready", "i_req_write",
            "i_req_addr", "i_req_wdata", "i_req_wstrb", "o_rsp_valid",
            "i_rsp_ready", "o_rsp_rdata", "o_rsp_status", "o_irq",
        })

    def test_state_owns_completion_and_keeps_fsm_block_style(self):
        text = source(CONTROL / "GPGPUState.sv")
        for field in ("o_idle", "o_running", "o_stopped", "o_complete_pulse"):
            self.assertIn(field, text)
        self.assertEqual(len(re.findall(r"always_ff\s*@\(posedge clk\)", text)), 2)
        self.assertEqual(len(re.findall(r"always_comb\s+begin", text)), 2)
        self.assertNotRegex(text, r"irq_enable|completion_pending|`REG_\w+")


if __name__ == "__main__":
    unittest.main()
