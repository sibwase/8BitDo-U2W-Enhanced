#!/usr/bin/env python3
"""Shared USB boot-mode (2dc8:3208) HID protocol and image helpers for U2W v1.10.

Contains no proprietary 8BitDo firmware bytes — only protocol constants,
pinned SHA-256 verification hashes, and Telink-only patch validation.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

try:
    import hid
except ImportError:
    hid = None  # type: ignore[assignment]

# Pinned stock 8BitDo Ultimate 2 Wireless v1.10 hashes (PID 0x6012)
STOCK_DAT_SHA256 = "968edee528c23d56e2059288f90c109fa5135f060de5b403e72d0b6c50f5eb87"
STOCK_IMAGE_SHA256 = "43d8cd222586f8a118d867cb60b0711dee504aed1354d548958d0e985dac30e7"
BOOTLOADER_SHA256 = "faab5fff75e88556749d15980f84926592fc04329da2866e9af36919af529fa5"

VID = 0x2DC8
BOOT_PID = 0x3208
LOGICAL_PID = 0x6012
VERSION = 110

CLASS = 0x05
CMD_WRITE = 0x0003
CMD_ERASE = 0x0004
CMD_READ = 0x0005
CMD_IDENTIFY = 0x0008

REPORT_SIZE = 64
HEADER = 18
READ_CHUNK = 46
WRITE_CHUNK = 32

APP_START = 0x5000
IMAGE_SIZE = 0x23800
APP_END = APP_START + IMAGE_SIZE
SECTOR_SIZE = 0x1000
ERASE_END = (APP_END + SECTOR_SIZE - 1) & -SECTOR_SIZE
METADATA_START = 0x31000
METADATA_LEN = 0x34
PENDING_UPDATE_MAGIC = 0xAEB14D6C
WRAPPER_SIZE = 28
ERASED_SECTOR = b"\xff" * SECTOR_SIZE

CAVE_FLASH_START = 0x0A040
CAVE_FLASH_END = 0x0D000

# Authoritative Telink patch section layout shared by patches/build.py and apply_patch_file().
PATCH_SECTIONS: list[tuple[str, int, int]] = [
    (".hook_profile_leds", 0x057D4, 4),
    (".elite_stack_top", 0x050D4, 4),
    (".cave", CAVE_FLASH_START, CAVE_FLASH_END - CAVE_FLASH_START),
    (".hook_conn_mtu", 0x0D48A, 4),
    (".hook_conn_param", 0x0D496, 4),
    (".hook_disconn", 0x0D4EA, 4),
    (".hook_bt_mac_init", 0x0D570, 4),
    (".hook_ble_init", 0x0D58E, 4),
    (".hook_gatt_init", 0x0D59A, 4),
    (".hook_smp_init", 0x0D5AA, 4),
    (".hook_adv_data", 0x0D5B2, 4),
    (".hook_scan_rsp", 0x0D5BA, 4),
    (".hook_bond_count", 0x0D5BE, 4),
    (".hook_batt_notify", 0x0D6D4, 4),
    (".hook_input_report", 0x0D6DA, 4),
    (".hook_ble_app_loop", 0x0D74C, 4),
    (".hook_24g_init", 0x0D9EC, 4),
    (".hook_start_pairing", 0x0E174, 4),
    (".hook_elite_notify", 0x0E460, 4),
    (".hook_home_ring_blink_off", 0x0F54A, 12),
    (".hook_home_ring_blink_on", 0x0F566, 16),
    (".hook_home_ring_solid_off", 0x0F5CA, 4),
    (".hook_home_ring_solid_on", 0x0F5EA, 4),
    (".hook_home_ring_init", 0x0F71C, 10),
    (".hook_pair_mac_inc", 0x0FAB0, 4),
    (".hook_conn_interval", 0x15B5C, 4),
    (".hook_phy_update", 0x16D0C, 4),
    (".elite_name_ptr", 0x1B61C, 4),
    (".elite_pnp_ptr", 0x1B724, 4),
    (".elite_rumble_ptr", 0x1B8F0, 4),
    (".elite_map_ptr", 0x1B934, 4),
    (".cave_elite", 0x1C75C, 0x300),
]
PATCH_SECTION_MAP: dict[str, tuple[int, int]] = {
    name: (addr, max_len) for name, addr, max_len in PATCH_SECTIONS
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xA001) if (crc & 1) else (crc >> 1)
    return crc


def u16(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 2], "little")


def load_stock_image(path: Path) -> bytes:
    """Load and verify a stock U2W v1.10 image from either a .dat or raw 0x23800 .bin."""
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    data = path.read_bytes()
    if len(data) == WRAPPER_SIZE + IMAGE_SIZE:
        if sha256(data) != STOCK_DAT_SHA256:
            raise ValueError(f"{path}: .dat does not match pinned U2W v1.10 SHA-256")
        if struct.unpack_from("<4I", data) != (VERSION, APP_START, IMAGE_SIZE, LOGICAL_PID):
            raise ValueError(f"{path}: .dat header does not match U2W v1.10 layout")
        image = data[WRAPPER_SIZE:]
    elif len(data) == IMAGE_SIZE:
        image = data
    else:
        raise ValueError(
            f"{path}: expected {IMAGE_SIZE} bytes (raw app) or {WRAPPER_SIZE + IMAGE_SIZE} "
            f"bytes (.dat), got {len(data)}"
        )
    if sha256(image) != STOCK_IMAGE_SHA256:
        raise ValueError(f"{path}: app image SHA-256 does not match stock U2W v1.10")
    return image


def validate_and_fix_image(
    candidate: bytearray, stock: bytes, *, fix_sums: bool
) -> bytes:
    if len(candidate) != IMAGE_SIZE:
        raise ValueError(f"image size {len(candidate):#x} != {IMAGE_SIZE:#x}")
    if candidate[0x08:0x0C] != b"KNLT":
        raise ValueError("missing KNLT magic at +0x08")
    ver = struct.unpack_from("<H", candidate, 0x02)[0]
    if ver in (0, 0xFFFF):
        raise ValueError(f"invalid version word {ver:#06x} at +0x02")
    load_size = struct.unpack_from("<H", candidate, 0x0C)[0] * 16
    if load_size > 0x7200:
        raise ValueError(f"load size {load_size:#x} exceeds 0x7200")
    pid = struct.unpack_from("<H", candidate, 0x1C)[0]
    if pid != LOGICAL_PID:
        raise ValueError(f"PID {pid:#06x} at +0x1c != {LOGICAL_PID:#06x}")
    if candidate[0x1E] != stock[0x1E]:
        raise ValueError("sum-enable flag at +0x1e must remain unchanged")

    n = struct.unpack_from("<I", candidate, 0x18)[0]
    stock_n = struct.unpack_from("<I", stock, 0x18)[0]
    if n != stock_n:
        raise ValueError(f"code length N={n:#x} differs from stock {stock_n:#x}")

    d = n + 4
    m = struct.unpack_from("<I", stock, n + 0x18)[0]
    if candidate[d : d + m + 4] != stock[d : d + m + 4]:
        raise ValueError("RISC-V peer image / data sum differs from stock (refusing)")

    calc_crc = zlib.crc32(candidate[: n - 4]) ^ 0xFFFFFFFF
    calc_sum = sum(candidate[: n - 4]) & 0xFFFFFFFF
    stored_crc = struct.unpack_from("<I", candidate, n - 4)[0]
    stored_sum = struct.unpack_from("<I", candidate, n)[0]

    if fix_sums:
        struct.pack_into("<I", candidate, n - 4, calc_crc)
        struct.pack_into("<I", candidate, n, calc_sum)
    else:
        if stored_crc != calc_crc:
            raise ValueError(
                f"CRC-32 mismatch at +{n - 4:#x}: stored {stored_crc:#010x} != {calc_crc:#010x}"
            )
        if stored_sum != calc_sum:
            raise ValueError(
                f"code sum mismatch at +{n:#x}: stored {stored_sum:#010x} != {calc_sum:#010x}"
            )
    return bytes(candidate)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Atomically write bytes to path with owner-only permissions by default."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        os.chmod(tmp_path, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def validate_update_metadata(meta: bytes) -> None:
    """Ensure bootloader update metadata at [0x31000, 0x31034) has no pending staged update."""
    if len(meta) != METADATA_LEN:
        raise ValueError(f"update metadata length {len(meta)} != {METADATA_LEN}")
    if meta == b"\xff" * METADATA_LEN:
        return  # Factory-erased metadata: no staged update.
    stored_crc = u16(meta, 0x30)
    calc_crc = crc16_modbus(meta[:0x30])
    if stored_crc != calc_crc:
        raise ValueError(
            f"update metadata CRC-16 mismatch ({stored_crc:#06x} != {calc_crc:#06x})"
        )
    pending = struct.unpack_from("<I", meta, 0x18)[0]
    if pending == PENDING_UPDATE_MAGIC:
        raise ValueError(
            "a staged firmware update is pending in [0x31000, 0x31034) and would "
            "overwrite the app on reboot; boot normally once to let it complete first"
        )
    if pending != 0:
        raise ValueError(f"unexpected non-idle update metadata pending flag {pending:#010x}")


def drain_hid_input(dev, report_size: int = REPORT_SIZE, max_packets: int = 64) -> None:
    """Drain queued HID input reports without blocking on cython-hidapi or ctypes hid."""
    if hasattr(dev, "set_nonblocking"):
        dev.set_nonblocking(1)
        try:
            for _ in range(max_packets):
                if not dev.read(report_size):
                    break
        finally:
            dev.set_nonblocking(0)
    else:
        for _ in range(max_packets):
            if not dev.read(report_size, 1):
                break


def apply_patch_file(stock: bytes, patch_path: Path) -> bytes:
    """Apply a redistribution-safe u2w-telink-patch-v1 JSON file onto stock v1.10."""
    doc = json.loads(patch_path.read_text())
    if doc.get("format") != "u2w-telink-patch-v1":
        raise ValueError(f"unsupported patch format: {doc.get('format')!r}")
    if doc.get("base_image_sha256") != sha256(stock):
        raise ValueError("stock image SHA-256 does not match patch base_image_sha256")
    expected = doc.get("patched_image_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("patch file is missing a valid 64-char patched_image_sha256")

    sections = doc.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("patch file has no sections")

    buf = bytearray(stock)
    seen_names: set[str] = set()
    placed_ranges: list[tuple[int, int, str]] = []
    for sec in sections:
        name = sec["name"]
        if name not in PATCH_SECTION_MAP:
            raise ValueError(f"unexpected patch section {name!r}")
        if name in seen_names:
            raise ValueError(f"duplicate patch section {name!r}")
        seen_names.add(name)

        exp_addr, max_len = PATCH_SECTION_MAP[name]
        flash_addr = int(sec["flash_addr"])
        if flash_addr != exp_addr:
            raise ValueError(
                f"section {name} address {flash_addr:#x} != expected {exp_addr:#x}"
            )
        blob = bytes.fromhex(sec["data_hex"])
        if not blob or len(blob) > max_len:
            raise ValueError(f"section {name} size {len(blob)} outside 1..{max_len}")

        img_off = flash_addr - APP_START
        img_end = img_off + len(blob)
        if img_off < 0 or img_end > IMAGE_SIZE:
            raise ValueError(f"section {name} out of bounds at {flash_addr:#x}")
        for prev_start, prev_end, prev_name in placed_ranges:
            if img_off < prev_end and prev_start < img_end:
                raise ValueError(f"section {name} overlaps {prev_name}")
        placed_ranges.append((img_off, img_end, name))

        if name in (".cave", ".cave_elite") and any(b != 0 for b in buf[img_off:img_end]):
            raise ValueError(f"cave at {flash_addr:#x} is not all zeros in stock")
        buf[img_off:img_end] = blob

    patched = validate_and_fix_image(buf, stock, fix_sums=True)
    if sha256(patched) != expected:
        raise ValueError(
            f"patched image SHA-256 {sha256(patched)} != expected {expected}"
        )
    return patched


def expected_sector_bytes(image: bytes, addr: int) -> bytes:
    off = addr - APP_START
    prog_len = min(SECTOR_SIZE, APP_END - addr)
    return image[off : off + prog_len] + ERASED_SECTOR[prog_len:]


def build_boot_packet(
    cmd: int,
    addr: int = 0,
    length: int = 0,
    total_len: int | None = None,
    payload: bytes = b"",
) -> bytes:
    if cmd not in (CMD_IDENTIFY, CMD_READ, CMD_ERASE, CMD_WRITE):
        raise ValueError(f"unsupported command: {cmd:#06x}")
    if len(payload) > READ_CHUNK:
        raise ValueError(f"payload too long: {len(payload)}")
    if total_len is None:
        total_len = length
    crc = crc16_modbus(payload) if payload else 0

    pkt = bytearray(REPORT_SIZE + 1)
    pkt[0] = 0x00
    fields = memoryview(pkt)[1:]
    fields[0] = CLASS
    fields[1:3] = cmd.to_bytes(2, "little")
    fields[3:5] = (0).to_bytes(2, "little")
    fields[5:7] = length.to_bytes(2, "little")
    fields[7:9] = crc.to_bytes(2, "little")
    fields[9:13] = total_len.to_bytes(4, "little")
    fields[13:17] = addr.to_bytes(4, "little")
    fields[17 : 17 + len(payload)] = payload
    return bytes(pkt)


def parse_boot_reply(
    reply: bytes, echo: int, *, addr: int = 0, length: int = 0
) -> bytes:
    size = 2 if echo == CMD_IDENTIFY else (length if echo == CMD_READ else 0)
    end = HEADER + size
    if len(reply) < end:
        raise ValueError(f"short reply ({len(reply)} bytes, need {end})")
    if not reply.startswith(bytes((0x00, CLASS))):
        raise ValueError(f"unexpected reply prefix {reply[:4].hex(' ')}")
    status = u16(reply, 2)
    got = u16(reply, 4)
    if status != 0:
        raise ValueError(f"device status {status:#06x} for cmd {echo:#06x}")
    if got != echo:
        raise ValueError(f"reply echoed {got:#06x}, expected {echo:#06x}")
    if echo == CMD_READ:
        got_addr = int.from_bytes(reply[14:18], "little")
        got_len = u16(reply, 6)
        if (got_addr, got_len) != (addr, length):
            raise ValueError(
                f"read reply for {got_addr:#010x}+{got_len}, expected {addr:#010x}+{length}"
            )
    return reply[HEADER:end]


class BootPad:
    def __init__(self, dev_info: dict, *, timeout_ms: int = 2000, retries: int = 3):
        if hid is None:
            sys.exit("python hidapi is required: pip install hidapi")
        self.info = dev_info
        self.timeout_ms = timeout_ms
        self.retries = retries
        if hasattr(hid, "device"):
            self.dev = hid.device()
            self.dev.open_path(dev_info["path"])
        else:
            self.dev = hid.Device(path=dev_info["path"])

    def close(self) -> None:
        try:
            self.dev.close()
        except Exception:
            pass

    def flush(self) -> None:
        drain_hid_input(self.dev, REPORT_SIZE)

    def command(
        self,
        cmd: int,
        addr: int = 0,
        length: int = 0,
        *,
        total_len: int | None = None,
        payload: bytes = b"",
        timeout_ms: int | None = None,
    ) -> bytes:
        pkt = build_boot_packet(
            cmd, addr=addr, length=length, total_len=total_len, payload=payload
        )
        wait_ms = self.timeout_ms if timeout_ms is None else timeout_ms
        last: Exception | None = None
        for attempt in range(self.retries):
            self.flush()
            written = self.dev.write(pkt)
            if written != len(pkt):
                last = RuntimeError(f"hid_write returned {written}, expected {len(pkt)}")
                continue
            deadline = time.monotonic() + wait_ms / 1000.0
            while time.monotonic() < deadline:
                reply = bytes(self.dev.read(REPORT_SIZE, 50))
                if not reply:
                    continue
                try:
                    return parse_boot_reply(reply, cmd, addr=addr, length=length)
                except ValueError as exc:
                    last = exc
            if attempt + 1 < self.retries:
                time.sleep(0.05)
        raise RuntimeError(f"cmd {cmd:#06x} at {addr:#010x} failed: {last or 'timeout'}")

    def identify(self) -> int:
        data = self.command(CMD_IDENTIFY, length=4)
        return u16(data, 0)

    def read_range(self, start: int, length: int, *, label: str = "") -> bytes:
        out = bytearray()
        done = 0
        while done < length:
            want = min(READ_CHUNK, length - done)
            out += self.command(CMD_READ, addr=start + done, length=want)
            done += want
            if label and (done % (READ_CHUNK * 32) < READ_CHUNK or done == length):
                print(
                    f"\r{label}: {done}/{length} bytes",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
        if label:
            print(file=sys.stderr)
        return bytes(out)

    def erase_sector(self, addr: int) -> None:
        if not (APP_START <= addr < ERASE_END) or addr % SECTOR_SIZE != 0:
            raise ValueError(f"refusing to erase out-of-bounds sector {addr:#010x}")
        self.command(
            CMD_ERASE,
            addr=addr,
            length=0,
            total_len=SECTOR_SIZE,
            timeout_ms=10000,
        )

    def write_chunk(self, addr: int, data: bytes) -> None:
        if not (APP_START <= addr and addr + len(data) <= APP_END):
            raise ValueError(
                f"refusing to write out-of-bounds range [{addr:#010x}, {addr + len(data):#010x})"
            )
        if not (1 <= len(data) <= WRITE_CHUNK):
            raise ValueError(f"bad write chunk size {len(data)}")
        self.command(
            CMD_WRITE,
            addr=addr,
            length=len(data),
            total_len=len(data),
            payload=data,
            timeout_ms=2000,
        )


def find_boot_device(path: str | None) -> dict:
    if hid is None:
        sys.exit("python hidapi is required: pip install hidapi")
    devs = [d for d in hid.enumerate(VID) if d["product_id"] == BOOT_PID]
    if path is not None:
        want = path.encode()
        devs = [d for d in devs if d["path"] == want]
    if not devs:
        sys.exit(
            "no 2dc8:3208 bootloader found. Turn the controller off, hold LB + RB, "
            "and plug in USB while holding both buttons."
        )
    if len(devs) > 1:
        lines = [f"  path={d['path']} if={d.get('interface_number')}" for d in devs]
        sys.exit("multiple 2dc8:3208 devices found; pass --path:\n" + "\n".join(lines))
    return devs[0]
