/*
 * 1% Home / link ring PWM driver for 8BitDo Ultimate 2 Wireless, stock v1.10.
 * Adapted from the U2W Home Ring 1% add-on (PR #1) and linked into ClosetPie.
 *
 * PB5 is the Home/link-ring LED. The stock firmware drives it as GPIO (100% or
 * 0%). This helper switches PB5 to PWM5 once during the stock PWM init, then
 * writes only PWM5's compare word: period=10000, ON=100 (1%), OFF=0.
 * It intentionally does not alter the shared PWM clock or PWM4 configuration.
 *
 * IMPORTANT: This does not change the 8BitDo image's proprietary code. The
 * caller-site byte guards in build.py must continue to match stock v1.10.
 */
    .section .cave.home_ring, "ax"
    .align 2
    .global home_ring_set
    .global home_ring_blink_go
    .global home_ring_maybe_off
    .global home_ring_maybe_on
    .global home_ring_setup

home_ring_set:
    tcmp    r0, #0
    tjeq    home_ring_duty_off
    tloadr  r0, home_ring_duty_on
    tj      home_ring_store
home_ring_duty_off:
    tloadr  r0, home_ring_duty_zero
home_ring_store:
    tloadr  r3, home_ring_pwm5
    tstorer r0, [r3, #0]
    tjex    lr

/* Blink hooks preserve the original LR. Stock continuation is 0xf506. */
home_ring_blink_go:
    tjl     home_ring_set
    tpop    {r3}
    tmov    lr, r3
    tloadr  r3, home_ring_ret_f506
    tjex    r3

/* Intercept PB5 only; replay the displaced stock instructions for other pins. */
home_ring_maybe_off:
    tloadr  r1, home_ring_pin
    tcmp    r3, r1
    tjne    home_ring_stock_off
    tmovs   r0, #0
    tjl     home_ring_set
    tloadr  r0, home_ring_ret_f5c0
    tmov    lr, r0
    tjex    lr
home_ring_stock_off:
    tshftl  r3, r3, #16
    tshftr  r1, r3, #16
    tloadr  r0, home_ring_ret_f5ce
    tmov    lr, r0
    tjex    lr

home_ring_maybe_on:
    tloadr  r1, home_ring_pin
    tcmp    r3, r1
    tjne    home_ring_stock_on
    tmovs   r0, #1
    tjl     home_ring_set
    tloadr  r0, home_ring_ret_f5c0
    tmov    lr, r0
    tjex    lr
home_ring_stock_on:
    tshftl  r3, r3, #16
    tshftr  r2, r3, #16
    tloadr  r0, home_ring_ret_f5ee
    tmov    lr, r0
    tjex    lr

/*
 * Called at stock 0xf71c after r3/r1 were prepared by 0xf71a.
 * Preserve PWM4's enable state, mux PB5 to PWM5, enable PB5 output/PWM5,
 * and initialise the ring to OFF until the normal stock path requests ON.
 */
home_ring_setup:
    tpush   {lr}
    tmovs   r2, #16
    tor     r2, r1
    tshftl  r2, r2, #24
    tshftr  r2, r2, #24
    tstorerb r2, [r3, #0]
    tloadr  r0, home_ring_pin
    tmovs   r1, #25
    tjl     gpio_set_func
    tloadr  r3, home_ring_oen
    tloadrb r2, [r3, #0]
    tmovs   r1, #32
    tbclr   r2, r1
    tstorerb r2, [r3, #0]
    tloadr  r3, home_ring_en
    tloadrb r2, [r3, #0]
    tmovs   r1, #32
    tor     r2, r1
    tstorerb r2, [r3, #0]
    tloadr  r0, home_ring_duty_zero
    tloadr  r3, home_ring_pwm5
    tstorer r0, [r3, #0]
    tpop    {pc}

    .align 2
home_ring_pin:          .word 0x120
home_ring_oen:          .word 0x80058a
home_ring_en:           .word 0x800780
home_ring_pwm5:         .word 0x8007a8
home_ring_duty_on:      .word 0x27100064
home_ring_duty_zero:    .word 0x27100000
home_ring_ret_f5c0:     .word 0xf5c0
home_ring_ret_f5ce:     .word 0xf5ce
home_ring_ret_f5ee:     .word 0xf5ee
home_ring_ret_f506:     .word 0xf506
