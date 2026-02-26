/*
 * NEXUS OS Bare-Metal Boot — ARM64 (AArch64)
 *
 * Targets QEMU virt machine (-M virt -cpu cortex-a72).
 * Sets up stack, zeros BSS, jumps to kernel_main().
 *
 * Adapted from s-matyukevich/raspberry-pi-os lesson01.
 */

.section ".text.boot"
.global _start

_start:
    /* Only let CPU 0 through; park all other cores */
    mrs     x0, mpidr_el1
    and     x0, x0, #0xFF
    cbz     x0, primary_cpu
    b       cpu_hang

primary_cpu:
    /* Drop to EL1 if we're in EL2 (QEMU may start in EL1 or EL2) */
    mrs     x0, CurrentEL
    lsr     x0, x0, #2
    cmp     x0, #2
    b.ne    el1_entry

    /* Configure EL2 -> EL1 transition */
    mov     x0, #(1 << 31)         /* HCR_EL2.RW = 1 (AArch64 at EL1) */
    msr     hcr_el2, x0

    mov     x0, #0x3C5             /* SPSR_EL2: EL1h, DAIF masked */
    msr     spsr_el2, x0

    adr     x0, el1_entry
    msr     elr_el2, x0
    eret

el1_entry:
    /* Set up exception vector table */
    ldr     x0, =exception_vectors
    msr     vbar_el1, x0

    /* Zero BSS section */
    ldr     x0, =__bss_start
    ldr     x1, =__bss_end
bss_loop:
    cmp     x0, x1
    b.ge    bss_done
    str     xzr, [x0], #8
    b       bss_loop
bss_done:

    /* Set up stack pointer (grows down from 2MB above kernel base) */
    ldr     x0, =_stack_top
    mov     sp, x0

    /* Jump to C kernel */
    bl      kernel_main

    /* Should never return; hang if it does */
cpu_hang:
    wfe
    b       cpu_hang

/*
 * Exception vector table (minimal — just prints and hangs)
 * Each entry is 128 bytes (0x80), 16 entries total = 2048 bytes
 */
.balign 0x800
.global exception_vectors
exception_vectors:
    /* Current EL with SP_EL0 */
    b       exc_handler     /* Synchronous */
    .balign 0x80
    b       exc_handler     /* IRQ */
    .balign 0x80
    b       exc_handler     /* FIQ */
    .balign 0x80
    b       exc_handler     /* SError */
    .balign 0x80

    /* Current EL with SP_ELx */
    b       exc_handler     /* Synchronous */
    .balign 0x80
    b       exc_handler     /* IRQ */
    .balign 0x80
    b       exc_handler     /* FIQ */
    .balign 0x80
    b       exc_handler     /* SError */
    .balign 0x80

    /* Lower EL, AArch64 */
    b       exc_handler     /* Synchronous */
    .balign 0x80
    b       exc_handler     /* IRQ */
    .balign 0x80
    b       exc_handler     /* FIQ */
    .balign 0x80
    b       exc_handler     /* SError */
    .balign 0x80

    /* Lower EL, AArch32 */
    b       exc_handler     /* Synchronous */
    .balign 0x80
    b       exc_handler     /* IRQ */
    .balign 0x80
    b       exc_handler     /* FIQ */
    .balign 0x80
    b       exc_handler     /* SError */
    .balign 0x80

exc_handler:
    b       cpu_hang
