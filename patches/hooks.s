/*
 * TC32 patch entry points for U2W v1.10 Switch 2 BLE and persistent mode memory.
 */

#ifdef S2_BOND_DIAGNOSTICS
    .section .hook_profile_leds, "ax"
    .global _hook_profile_leds
_hook_profile_leds:
    tjl     s2_profile_led_slot_hook
#endif

    .section .hook_bt_mac_init, "ax"
    .global _hook_bt_mac_init
_hook_bt_mac_init:
    tjl     s2_bt_mac_init_hook

    .section .hook_ble_init, "ax"
    .global _hook_ble_init
_hook_ble_init:
    tjl     ble_init_hook

    .section .hook_gatt_init, "ax"
    .global _hook_gatt_init
_hook_gatt_init:
    tjl     s2_gatt_init_hook

    .section .hook_smp_init, "ax"
    .global _hook_smp_init
_hook_smp_init:
    tjl     s2_smp_init_hook

    .section .hook_adv_data, "ax"
    .global _hook_adv_data
_hook_adv_data:
    tjl     s2_adv_data_hook

    .section .hook_scan_rsp, "ax"
    .global _hook_scan_rsp
_hook_scan_rsp:
    tjl     s2_scan_rsp_hook

    .section .hook_bond_count, "ax"
    .global _hook_bond_count
_hook_bond_count:
    tjl     s2_bond_count_hook

    .section .hook_conn_mtu, "ax"
    .global _hook_conn_mtu
_hook_conn_mtu:
    tjl     s2_connect_mtu_hook

    .section .hook_conn_param, "ax"
    .global _hook_conn_param
_hook_conn_param:
    tjl     s2_conn_param_hook

    .section .hook_disconn, "ax"
    .global _hook_disconn
_hook_disconn:
    tjl     s2_disconnect_hook

    .section .hook_batt_notify, "ax"
    .global _hook_batt_notify
_hook_batt_notify:
    tjl     s2_batt_notify_hook

    .section .hook_input_report, "ax"
    .global _hook_input_report
_hook_input_report:
    tjl     s2_input_report_hook

    .section .hook_elite_notify, "ax"
    tjl     elite_notify_hook

    .section .hook_conn_interval, "ax"
    .global _hook_conn_interval
_hook_conn_interval:
    tjl     s2_conn_interval

    .section .cave.interval, "ax"
    .global s2_conn_interval
s2_conn_interval:
    tloadr  r3, .Lstock_bt
    tloadrb r3, [r3, #0]
    tcmp    r3, #0
    tjne    .Lstock_interval
    tsub    r2, r1, #4       /* Switch 2 uses a 5 ms interval */
    tj      .Linterval_done
.Lstock_interval:
    tsub    r2, r1, #6       /* Original 7.5 ms minimum */
.Linterval_done:
    tshftl  r2, r2, #16     /* Displaced instruction at 0x15b5e */
    tjex    lr
    .align  2
.Lstock_bt:
    .word   0x00845f77

    .section .hook_start_pairing, "ax"
    .global _hook_start_pairing
_hook_start_pairing:
    tjl     s2_start_pairing_hook

/* Home Ring PWM5: preserve stock on/off and pairing-blink control flow. */
    .section .hook_home_ring_blink_off, "ax"
    .global _hook_home_ring_blink_off
_hook_home_ring_blink_off:
    tpush   {lr}
    tmovs   r0, #0
    tjl     home_ring_blink_go
    .short  0x06c0
    .short  0x06c0

    .section .hook_home_ring_blink_on, "ax"
    .global _hook_home_ring_blink_on
_hook_home_ring_blink_on:
    tpush   {lr}
    tmovs   r0, #1
    tjl     home_ring_blink_go
    .short  0x06c0
    .short  0x06c0
    .short  0x06c0
    .short  0x06c0

    .section .hook_home_ring_solid_off, "ax"
    .global _hook_home_ring_solid_off
_hook_home_ring_solid_off:
    tjl     home_ring_maybe_off

    .section .hook_home_ring_solid_on, "ax"
    .global _hook_home_ring_solid_on
_hook_home_ring_solid_on:
    tjl     home_ring_maybe_on

    .section .hook_home_ring_init, "ax"
    .global _hook_home_ring_init
_hook_home_ring_init:
    tjl     home_ring_setup
    .short  0x06c0
    .short  0x06c0
    .short  0x06c0

.section .hook_pair_mac_inc, "ax"
    .global _hook_pair_mac_inc
_hook_pair_mac_inc:
    tjl     stock_noop /* Per-slot Pair MAC bump is handled in s2_bt_mac_init_hook */

    .section .hook_ble_app_loop, "ax"
    .global _hook_ble_app_loop
_hook_ble_app_loop:
    tjl     s2_ble_app_loop_hook

    .section .hook_24g_init, "ax"
    .global _hook_24g_init
_hook_24g_init:
    tjl     s2_24g_init_hook

    .section .hook_phy_update, "ax"
    .global _hook_phy_update
_hook_phy_update:
    tjl     s2_phy_update_dispatch

    .section .cave.phy_update, "ax"
s2_phy_update_dispatch:
    /* r1 = opcode, r6 = validated, optionally decrypted LL header. */
    tcmp    r1, #0x18
    tjne    .Lstock_phy
    tloadr  r3, .Lphy_stock_bt
    tloadrb r3, [r3, #0]
    tcmp    r3, #0
    tjne    .Lstock_phy
    tmov    r0, r6
    tjl     s2_handle_phy_update
    tloadr  r3, .Lphy_rx_done
    tjex    r3
.Lstock_phy:
    tloadr  r0, .Lll_features
    tloadr  r0, [r0, #0]
    tjex    lr
    .align  2
.Lphy_stock_bt:
    .word   0x00845f77
.Lphy_rx_done:
    .word   0x00016deb
.Lll_features:
    .word   0x00844a04
