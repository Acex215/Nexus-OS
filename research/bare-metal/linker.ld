/*
 * NEXUS OS Bare-Metal Linker Script
 * Target: QEMU virt machine (ARM64)
 *
 * QEMU -M virt loads kernel at 0x40000000 by default.
 * Stack grows down from _stack_top (kernel base + 2MB).
 */

ENTRY(_start)

SECTIONS
{
    . = 0x40000000;

    .text.boot : {
        *(.text.boot)
    }

    .text : {
        *(.text)
    }

    .rodata : {
        *(.rodata)
    }

    .data : {
        *(.data)
    }

    . = ALIGN(8);
    __bss_start = .;
    .bss : {
        *(.bss)
    }
    __bss_end = .;

    . = ALIGN(16);
    . = . + 0x10000;   /* 64KB stack */
    _stack_top = .;
}
