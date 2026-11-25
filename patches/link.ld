/* Linker script for U2W v1.10 Switch 2 BLE TC32 patches */

SECTIONS
{
    /* Reserve 160 bytes above the initial supervisor stack for the GAP/HID
     * values that the shared stock ATT table reads in either HID mode. */
    elite_map_ram = 0x00847f60;
    elite_pnp_ram = elite_map_ram + 116;
    elite_name_ram = elite_map_ram + 124;
    .elite_stack_top 0x000000d4 : { LONG(elite_map_ram) }

    .cave_elite 0x0001c75c : {
        *elite.o(.text .text.*)
        . = ALIGN(4);
        *elite.o(.rodata .rodata.*)
    }

    /* In relocated code: replace the profile LED index lookup for UART command 4. */
    . = 0x000007d4;
    .hook_profile_leds : { *(.hook_profile_leds) }

    /* 12 KiB zero cave inside bootloader-covered Telink flash [0x5000, 0x1ca60) */
    . = 0x0000a040;
    .cave : {
        *(.cave.home_ring)
        *(.cave.init)
        *(.cave.csa2)
        *(.cave.interval)
        *(.cave.phy_update)
        *(.text .text.*)
        . = ALIGN(4);
        *(.rodata .rodata.*)
    }

    /* Connect callback hooks (0xd448) */
    . = 0x0000d48a;
    .hook_conn_mtu : { *(.hook_conn_mtu) }
    . = 0x0000d496;
    .hook_conn_param : { *(.hook_conn_param) }

    /* Disconnect callback hook (0xd4e0) */
    . = 0x0000d4ea;
    .hook_disconn : { *(.hook_disconn) }

    /* Cold BLE startup hooks (0xd558) */
    . = 0x0000d570;
    .hook_bt_mac_init : { *(.hook_bt_mac_init) }
    . = 0x0000d58e;
    .hook_ble_init : { *(.hook_ble_init) }
    . = 0x0000d59a;
    .hook_gatt_init : { *(.hook_gatt_init) }
    . = 0x0000d5aa;
    .hook_smp_init : { *(.hook_smp_init) }
    . = 0x0000d5b2;
    .hook_adv_data : { *(.hook_adv_data) }
    . = 0x0000d5ba;
    .hook_scan_rsp : { *(.hook_scan_rsp) }
    . = 0x0000d5be;
    .hook_bond_count : { *(.hook_bond_count) }

    /* BLE main loop hooks (0xd6a0) */
    . = 0x0000d6d4;
    .hook_batt_notify : { *(.hook_batt_notify) }
    . = 0x0000d6da;
    .hook_input_report : { *(.hook_input_report) }
    . = 0x0000d74c;
    .hook_ble_app_loop : { *(.hook_ble_app_loop) }

    /* Non-BLE (2.4G / USB) startup hook (replaces tjl 0xff94 at 0xd9ec). */
    . = 0x0000d9ec;
    .hook_24g_init : { *(.hook_24g_init) }

    /* Pair button advertising hook (stock pairing entry at 0xe168). */
    . = 0x0000e174;
    .hook_start_pairing : { *(.hook_start_pairing) }

    .hook_elite_notify 0x0000e460 : { *(.hook_elite_notify) }

    /* Home Ring: five stock-v1.10 call sites, guarded byte-for-byte in build.py. */
    . = 0x0000f54a;
    .hook_home_ring_blink_off : { *(.hook_home_ring_blink_off) }
    . = 0x0000f566;
    .hook_home_ring_blink_on : { *(.hook_home_ring_blink_on) }
    . = 0x0000f5ca;
    .hook_home_ring_solid_off : { *(.hook_home_ring_solid_off) }
    . = 0x0000f5ea;
    .hook_home_ring_solid_on : { *(.hook_home_ring_solid_on) }
    . = 0x0000f71c;
    .hook_home_ring_init : { *(.hook_home_ring_init) }

    /* Suppress global Pair MAC increment at 0xfab0 (replaced by per-slot mac_gen). */
    . = 0x0000fab0;
    .hook_pair_mac_inc : { *(.hook_pair_mac_inc) }

    /* CONNECT_IND interval guard (replaces two instructions at 0x15b5c). */
    . = 0x00015b5c;
    .hook_conn_interval : { *(.hook_conn_interval) }

    /* Validated LL PHY control dispatch, after optional RX decryption. */
    . = 0x00016d0c;
    .hook_phy_update : { *(.hook_phy_update) }

    .elite_name_ptr 0x0001b61c : { LONG(elite_name_ram) }
    .elite_pnp_ptr 0x0001b724 : { LONG(elite_pnp_ram) }
    .elite_rumble_ptr 0x0001b8f0 : { LONG(elite_rumble_hook + 1) }
    .elite_map_ptr 0x0001b934 : { LONG(elite_map_ram) }

    /DISCARD/ : {
        *(.comment)
        *(.ARM.*)
        *(.note.*)
    }
}
