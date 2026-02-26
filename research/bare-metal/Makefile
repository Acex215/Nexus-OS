# NEXUS OS Bare-Metal Kernel — Makefile
# Target: QEMU virt machine, ARM64 (AArch64)
#
# Usage:
#   make            — build kernel8.img
#   make run        — build + run in QEMU
#   make run-log    — build + run in QEMU, capture output to benchmark.log
#   make clean      — remove build artifacts

CROSS   = aarch64-linux-gnu-
CC      = $(CROSS)gcc
LD      = $(CROSS)ld
OBJCOPY = $(CROSS)objcopy

CFLAGS  = -Wall -nostdlib -nostartfiles -ffreestanding -mgeneral-regs-only -O2 -I.
LDFLAGS = -T linker.ld

OBJS    = boot.o kernel.o contract_table.o

.PHONY: all clean run run-log

all: kernel8.img

boot.o: boot.S
	$(CC) $(CFLAGS) -c boot.S -o boot.o

kernel.o: kernel.c contract_table.h
	$(CC) $(CFLAGS) -c kernel.c -o kernel.o

contract_table.o: contract_table.c contract_table.h
	$(CC) $(CFLAGS) -c contract_table.c -o contract_table.o

kernel8.elf: $(OBJS) linker.ld
	$(LD) $(LDFLAGS) -o kernel8.elf $(OBJS)

kernel8.img: kernel8.elf
	$(OBJCOPY) kernel8.elf -O binary kernel8.img
	@echo "Built kernel8.img ($$(stat -c%s kernel8.img) bytes)"

run: kernel8.img
	qemu-system-aarch64 \
		-M virt \
		-cpu cortex-a72 \
		-nographic \
		-smp 1 \
		-m 128M \
		-kernel kernel8.img

run-log: kernel8.img
	timeout 30 qemu-system-aarch64 \
		-M virt \
		-cpu cortex-a72 \
		-nographic \
		-smp 1 \
		-m 128M \
		-kernel kernel8.img 2>&1 | tee benchmark.log || true

clean:
	rm -f *.o kernel8.elf kernel8.img benchmark.log
