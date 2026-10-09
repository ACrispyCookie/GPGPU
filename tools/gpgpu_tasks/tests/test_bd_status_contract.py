"""Check the portable BD against the merged host status ABI and LED ports."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]

class StatusContractTest(unittest.TestCase):
    def test_export_rejects_legacy_ports_before_writing_template(self):
        text = (ROOT / 'tools/hardware/vivado/export_block_design.tcl').read_text()
        self.assertIn('foreach legacy_port {o_loading_0 o_dumping_0}', text)
        self.assertIn('get_bd_ports -quiet $legacy_port', text)
        self.assertIn('Refusing to export legacy status interface', text)
        self.assertLess(text.index('foreach legacy_port'), text.index('write_bd_tcl -force'))

    def test_template_matches_status_and_led_contract(self):
        text = (ROOT / 'tools/hardware/vivado/create_block_design.tcl').read_text()
        self.assertNotIn('o_dumping', text)
        self.assertNotIn('o_loading', text)
        ports = re.findall(r'create_bd_port -dir O (\w+)', text)
        self.assertEqual(set(ports), {'o_idle_0', 'o_running_0'})
        self.assertIn('CONFIG.NUM_PORTS {4} $ilconcat_0', text)
        self.assertRegex(text, r'CONFIG.C_GPIO_WIDTH \{4\}.*?')
        status = text[text.index('# Create instance: axi_gpio_status'):text.index('# Create instance: ilslice_0')]
        self.assertIn('CONFIG.C_GPIO_WIDTH {4}', status)
        nets = re.findall(r'connect_bd_net -net \S+\s+(.*?)(?=\n  connect_bd_|\n\s*#|\Z)', text, re.S)
        for index, signal in enumerate(('o_idle', 'o_running', 'o_host_busy', 'o_host_done')):
            net = next(n for n in nets if f'[get_bd_pins GPGPU_0/{signal}]' in n)
            self.assertIn(f'[get_bd_pins ilconcat_0/In{index}]', net)
            if index < 2:
                self.assertIn(f'[get_bd_ports {signal}_0]', net)

if __name__ == '__main__':
    unittest.main()
