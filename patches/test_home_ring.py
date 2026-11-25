#!/usr/bin/env python3
"""Static pre-build checks for the Home Ring 1% integration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
asm = (ROOT / "patches/home_ring.s").read_text()
hooks = (ROOT / "patches/hooks.s").read_text()
linker = (ROOT / "patches/link.ld").read_text()
build = (ROOT / "patches/build.py").read_text()
boot = (ROOT / "tools/u2w_boot.py").read_text()

checks = {
    "helper is in dedicated cave subsection": '.section .cave.home_ring, "ax"' in asm,
    "PWM5 ON compare is 1% at period 10000": "home_ring_duty_on:      .word 0x27100064" in asm,
    "PWM5 OFF compare is zero": "home_ring_duty_zero:    .word 0x27100000" in asm,
    "PB5 pin constant is present": "home_ring_pin:          .word 0x120" in asm,
    "all five hook stubs exist": all(x in hooks for x in (
        "_hook_home_ring_blink_off", "_hook_home_ring_blink_on",
        "_hook_home_ring_solid_off", "_hook_home_ring_solid_on",
        "_hook_home_ring_init")),
    "helper is linked into main cave": "*(.cave.home_ring)" in linker,
    "five hook sections are linked at their stock sites": all(x in linker for x in (
        ". = 0x0000f54a", ". = 0x0000f566", ". = 0x0000f5ca",
        ". = 0x0000f5ea", ". = 0x0000f71c")),
    "build validates exact stock call-site bytes": "HOME_RING_HOOK_STOCK" in build,
    "build validates original init epilogue": "HOME_RING_INIT_CONT_STOCK" in build,
    "patch schema accepts all five new sections": all(x in boot for x in (
        ".hook_home_ring_blink_off", ".hook_home_ring_blink_on",
        ".hook_home_ring_solid_off", ".hook_home_ring_solid_on",
        ".hook_home_ring_init")),
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(("PASS" if ok else "FAIL") + ": " + name)
if failed:
    raise SystemExit(f"{len(failed)} Home Ring static check(s) failed")
print(f"All {len(checks)} Home Ring static checks passed. This is not a hardware test.")
