#!/usr/bin/env python3
"""Build U2W v1.10 Switch 2 BLE custom firmware from TC32 C/ASM sources."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / "patches"
BUILD = PATCHES / "build"

sys.path.insert(0, str(ROOT / "tools"))
from u2w_boot import (  # noqa: E402
    APP_START,
    PATCH_SECTIONS,
    load_stock_image,
    sha256,
    validate_and_fix_image,
)

RELOCATED_SECTIONS = {".hook_profile_leds": 0x07D4, ".elite_stack_top": 0x00D4}

ELITE_HOOK_STOCK = {
    ".elite_stack_top": "00 80 84 00",
    ".hook_elite_notify": "0a 90 36 9a",
    ".elite_name_ptr": "68 b4 01 00",
    ".elite_pnp_ptr": "4c b5 01 00",
    ".elite_rumble_ptr": "35 d5 00 00",
    ".elite_map_ptr": "d8 b4 01 00",
}

# Exact stock-v1.10 bytes at the five Home Ring call sites. These guards are
# mandatory: a different base image or a changed function layout must fail closed.
HOME_RING_HOOK_STOCK = {
    ".hook_home_ring_blink_off": "0f 0b 1a 48 20 a1 8a 03 1a 40 d7 87",
    ".hook_home_ring_blink_on":  "08 0b 19 48 20 a2 0a 03 12 f6 12 fe 1a 40 c7 87",
    ".hook_home_ring_solid_off": "1b f4 19 fc",
    ".hook_home_ring_solid_on":  "1b f4 1a fc",
    ".hook_home_ring_init":     "10 a2 0a 03 12 f6 12 fe 1a 40",
}
HOME_RING_INIT_CONT_ADDR = 0x0F726
HOME_RING_INIT_CONT_STOCK = bytes.fromhex("00 6d")  # stock tpop {pc}

STOCK_SYMS = {
    "stock_ll_init_slave": 0x161BC,
    "stock_matrix_set_all_columns": 0x0ED74,
    "stock_matrix_set_column": 0x0ECD0,
    "stock_matrix_read_rows": 0x0ED8C,
    "stock_delay_us": 0x01B1C,
    "stock_att_set_table": 0x17908,
    "stock_smp_init": 0x19FC8,
    "stock_ll_reg_ltk_cb": 0x16240,
    "stock_ll_set_adv_data": 0x158B4,
    "stock_ll_set_scan_rsp": 0x15938,
    "stock_gatt_exchange_mtu": 0x187F0,
    "stock_gatt_notify": 0x188D0,
    "stock_ll_ltk_reply": 0x1729C,
    "stock_ll_ltk_neg_reply": 0x172D8,
    "stock_disconn_check": 0x10E94,
    "stock_gatt_init": 0x0D75C,
    "stock_bond_count": 0x1A018,
    "stock_conn_param_update": 0x18CAC,
    "stock_batt_notify": 0x0E1CC,
    "stock_start_pairing": 0x0FC0C,
    "stock_noop": 0x0FCE0,
    "stock_input_report": 0x0E248,
    "stock_ble_app_loop": 0x0D6A0,
    "stock_24g_init": 0x0FF94,
    "stock_profile_led_slot": 0x0DA74,
    "stock_is_non_ble": 0x0EEF8,
    "stock_set_rumble": 0x12220,
    "gpio_set_func": 0x129CC,  # Stock U2W v1.10 GPIO mux helper, used by PWM5 setup.
    "stock_ble_rumble": 0x0D534,
    "stock_hid_name": 0x1B468,
    "stock_hid_map": 0x1B4D8,
    "stock_hid_pnp": 0x1B54C,
    "stock_get_imu": 0x0E1F0,
    "stock_get_battery_pct": 0x0DF24,
    "stock_flash_erase_sector": 0x12774,
    "stock_flash_enable_writes": 0x0E690,
    "stock_flash_protect": 0x0E610,
    "stock_l2cap_rx": 0x18F74,
}


def find_tc32_bin() -> Path:
    env = os.environ.get("TC32_BIN")
    if env:
        p = Path(env)
        if (p / "tc32-elf-gcc").is_file():
            return p
    which = shutil.which("tc32-elf-gcc")
    if which:
        return Path(which).resolve().parent
    default = Path.home() / ".local" / "opt" / "tc32" / "bin"
    if (default / "tc32-elf-gcc").is_file():
        return default
    sys.exit(
        "tc32-elf-gcc not found. Install the TC32 toolchain and put it on PATH "
        "or set TC32_BIN=/path/to/tc32/bin."
    )


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, text=True, capture_output=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        res.check_returncode()
    return res.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="path to stock U2W v1.10 .dat or raw 0x23800 app backup",
    )
    parser.add_argument("--bond-diagnostics", action="store_true")
    parser.add_argument(
        "--export-patch",
        type=Path,
        help="write a redistribution-safe JSON patch (original TC32 bytes only)",
    )
    args = parser.parse_args()
    build = BUILD / "bond-diagnostics" if args.bond_diagnostics else BUILD
    defines = ["-DS2_BOND_DIAGNOSTICS"] if args.bond_diagnostics else []
    sections = (
        PATCH_SECTIONS
        if args.bond_diagnostics
        else [s for s in PATCH_SECTIONS if s[0] != ".hook_profile_leds"]
    )
    tc32_bin = find_tc32_bin()

    build.mkdir(parents=True, exist_ok=True)
    gcc = str(tc32_bin / "tc32-elf-gcc")
    ld = str(tc32_bin / "tc32-elf-ld")
    objcopy = str(tc32_bin / "tc32-elf-objcopy")
    objdump = str(tc32_bin / "tc32-elf-objdump")
    readelf = str(tc32_bin / "tc32-elf-readelf")

    objs: list[str] = []
    for src in ("csa2.c", "s2_gatt.c", "s2_proto.c", "elite.c"):
        obj = build / (Path(src).stem + ".o")
        run([
            gcc, "-std=gnu99", "-Os", "-Wall", "-Werror", "-ffreestanding", "-fno-builtin",
            "-fno-jump-tables", "-ffunction-sections", "-fdata-sections", *defines,
            "-c", str(PATCHES / src), "-o", str(obj),
        ])
        objs.append(str(obj))

    hooks_o = build / "hooks.o"
    run([gcc, "-x", "assembler-with-cpp", *defines, "-c", str(PATCHES / "hooks.s"), "-o", str(hooks_o)])
    objs.append(str(hooks_o))

    home_ring_o = build / "home_ring.o"
    run([gcc, "-x", "assembler-with-cpp", "-c", str(PATCHES / "home_ring.s"), "-o", str(home_ring_o)])
    objs.append(str(home_ring_o))

    elf = build / "patch.elf"
    ld_cmd = [ld, "-N", "-T", str(PATCHES / "link.ld"), "--no-check-sections"]
    for name, addr in STOCK_SYMS.items():
        ld_cmd += ["--defsym", f"{name}={addr:#x}"]
    ld_cmd += objs + ["-o", str(elf)]
    run(ld_cmd)

    sec_hdrs = run([readelf, "-SW", str(elf)])
    alloc_addrs = {}
    for line in sec_hdrs.splitlines():
        match = re.match(
            r"^\s*\[\s*\d+\]\s+(\.\S+)\s+\S+\s+([\da-f]+)\s+[\da-f]+\s+"
            r"([\da-f]+)\s+[\da-f]+\s+(\S+)",
            line,
        )
        if match:
            name, addr, size, flags = match.groups()
            if "A" in flags and int(size, 16):
                alloc_addrs[name] = int(addr, 16)
    expected_addrs = {name: RELOCATED_SECTIONS.get(name, addr) for name, addr, _ in sections}
    if alloc_addrs != expected_addrs:
        raise RuntimeError(f"ELF section addresses differ from image layout: {alloc_addrs}")

    (build / "patch.dis").write_text(run([objdump, "-d", str(elf)]))

    stock = load_stock_image(args.base)
    buf = bytearray(stock)
    patch_sections = []

    for sec, flash_addr, max_len in sections:
        bin_path = build / f"{sec.lstrip('.')}.bin"
        run([objcopy, "-O", "binary", "-j", sec, str(elf), str(bin_path)])
        blob = bin_path.read_bytes()
        if not blob:
            raise RuntimeError(f"section {sec} is empty")
        if len(blob) > max_len:
            raise RuntimeError(f"section {sec} size {len(blob)} > max {max_len}")
        img_off = flash_addr - APP_START
        if sec in (".cave", ".cave_elite") and any(b != 0 for b in buf[img_off : img_off + len(blob)]):
            raise RuntimeError(f"cave at {flash_addr:#x} is not all zeros in stock!")
        if sec in ELITE_HOOK_STOCK:
            expected = bytes.fromhex(ELITE_HOOK_STOCK[sec])
            if len(blob) != len(expected) or buf[img_off : img_off + len(expected)] != expected:
                raise RuntimeError(f"stock bytes differ at {sec} ({flash_addr:#x})")
        if sec in HOME_RING_HOOK_STOCK:
            expected = bytes.fromhex(HOME_RING_HOOK_STOCK[sec])
            if len(blob) != len(expected):
                raise RuntimeError(
                    f"Home Ring hook {sec} assembled to {len(blob)} bytes; expected exactly {len(expected)}"
                )
            if buf[img_off : img_off + len(expected)] != expected:
                raise RuntimeError(
                    f"stock bytes differ at Home Ring hook {sec} ({flash_addr:#x}); refusing to patch"
                )
        buf[img_off : img_off + len(blob)] = blob
        patch_sections.append({
            "name": sec,
            "flash_addr": flash_addr,
            "data_hex": blob.hex(),
        })
        print(f"patched {sec:30s} @ flash {flash_addr:#07x} ({len(blob):4d} bytes)")

    # The init hook must return to the original stock epilogue. This guard is
    # outside the overwritten hook and catches accidental hook-length drift.
    guard_off = HOME_RING_INIT_CONT_ADDR - APP_START
    if stock[guard_off : guard_off + len(HOME_RING_INIT_CONT_STOCK)] != HOME_RING_INIT_CONT_STOCK:
        raise RuntimeError(
            f"stock bytes after Home Ring init hook differ at {HOME_RING_INIT_CONT_ADDR:#x}; refusing to patch"
        )

    patched = validate_and_fix_image(buf, stock, fix_sums=True)
    out_path = build / "u2w-1.10-switch2-ble.image.bin"
    out_path.write_bytes(patched)

    if args.export_patch:
        args.export_patch.parent.mkdir(parents=True, exist_ok=True)
        patch_doc = {
            "format": "u2w-telink-patch-v1",
            "target_model": "8BitDo Ultimate 2 Wireless (PID 0x6012)",
            "base_version": "1.10",
            "base_image_sha256": sha256(stock),
            "patched_image_sha256": sha256(patched),
            "sections": patch_sections,
        }
        args.export_patch.write_text(json.dumps(patch_doc, indent=2) + "\n")
        print(f"wrote patch {args.export_patch}")

    print(f"wrote {out_path} (SHA-256 {sha256(patched)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
