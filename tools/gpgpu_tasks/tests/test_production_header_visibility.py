"""Header visibility must survive independent compilation and IP packaging."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
FLOW = ROOT / 'tools/hardware/vivado'


def test_every_production_macro_consumer_includes_constants_explicitly():
    rtl = ROOT / 'hardware/rtl/gpgpu'
    match = re.search(r'set PRODUCTION_RTL_SOURCES\s*\{([^}]+)\}',
                      (FLOW / 'production_sources.tcl').read_text())
    assert match is not None
    manifest = match.group(1).split()
    macros = set(re.findall(r'^`define\s+(\w+)', (rtl / 'constants.svh').read_text(), re.M))
    missing = []
    for relative in manifest:
        if relative.endswith('.sv'):
            source = (rtl / relative).read_text()
            uses = set(re.findall(r'`(\w+)', source)) & macros
            if uses and not re.search(r'^\s*`include\s+"constants\.svh"', source, re.M):
                missing.append((relative, sorted(uses)))
    assert not missing, f'Production files rely on global include/compile order: {missing}'
