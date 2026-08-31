#!/usr/bin/env bash
# Build the P3 standalone image (p3_app.elf) with the pinned xPack toolchain and a
# hand-assembled Cortex-A9 standalone BSP from Xilinx 2025.2 embeddedsw sources (non-SDT).
# Host-only: produces an ELF; touches no board. See docs/l5_findings.md.
set -euo pipefail

REPO=/home/test/zynq_psoracle
TC=$REPO/toolchain/xpack-arm-none-eabi-gcc-14.2.1-1.1
CC=$TC/bin/arm-none-eabi-gcc
SA=/home/test/Xilinx/2025.2/data/embeddedsw/lib/bsp/standalone_v9_4/src
WD=/home/test/Xilinx/2025.2/data/embeddedsw/XilinxProcessorIPLib/drivers/scuwdt_v2_6/src
BSP=$REPO/firmware/bsp
OUT=$BSP/out
mkdir -p "$OUT"

ARCH="-mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard"
INC="-I$BSP/include -I$SA/common -I$SA/arm/common -I$SA/arm/common/gcc \
     -I$SA/arm/cortexa9 -I$SA/arm/cortexa9/gcc -I$WD"
# BSP sources are third-party; do not apply the app's -Werror/-pedantic to them.
BSP_CFLAGS="$ARCH -std=gnu11 -O2 -g $INC -DUSE_AMP=0 -ffunction-sections -fdata-sections"
APP_CFLAGS="$ARCH -std=c99 -O2 -g $INC -Wall -Wextra -ffreestanding -ffunction-sections -fdata-sections"

# --- BSP: startup + platform ------------------------------------------------------------
ASM_SRCS="arm/cortexa9/gcc/boot.S arm/cortexa9/gcc/cpu_init.S \
          arm/cortexa9/gcc/translation_table.S arm/cortexa9/gcc/xil-crt0.S \
          arm/cortexa9/gcc/asm_vectors.S"
C_SRCS="arm/cortexa9/xil_cache.c arm/cortexa9/xil_mmu.c arm/cortexa9/xil_misc_psreset_api.c \
        arm/cortexa9/xl2cc_counter.c arm/cortexa9/xtime_l.c \
        arm/common/vectors.c arm/common/xil_exception.c \
        common/xil_assert.c common/xil_printf.c common/print.c common/xil_mem.c \
        common/xil_sutil.c common/xil_util.c common/outbyte.c common/inbyte.c"
SYS_SRCS="arm/common/gcc/sbrk.c arm/common/gcc/_sbrk.c arm/common/gcc/write.c \
          arm/common/gcc/read.c arm/common/gcc/close.c arm/common/gcc/fstat.c \
          arm/common/gcc/isatty.c arm/common/gcc/lseek.c arm/common/gcc/_exit.c \
          arm/common/gcc/_open.c arm/common/gcc/open.c arm/common/gcc/unlink.c \
          arm/common/gcc/getpid.c arm/common/gcc/kill.c arm/common/gcc/errno.c \
          arm/common/gcc/abort.c"
WDT_SRCS="xscuwdt.c xscuwdt_g.c xscuwdt_sinit.c"

OBJS=()
for s in $ASM_SRCS; do o="$OUT/$(echo "$s" | tr / _).o"; "$CC" $BSP_CFLAGS -c "$SA/$s" -o "$o"; OBJS+=("$o"); done
for s in $C_SRCS $SYS_SRCS; do o="$OUT/$(echo "$s" | tr / _).o"; "$CC" $BSP_CFLAGS -c "$SA/$s" -o "$o"; OBJS+=("$o"); done
for s in $WDT_SRCS; do o="$OUT/wd_$s.o"; "$CC" $BSP_CFLAGS -c "$WD/$s" -o "$o"; OBJS+=("$o"); done

# --- glue + application -----------------------------------------------------------------
"$CC" $BSP_CFLAGS -c "$BSP/src/console.c" -o "$OUT/console.o"; OBJS+=("$OUT/console.o")
for s in p3_app.c p3_derive.c p3_search.c; do
  "$CC" $APP_CFLAGS -c "$REPO/firmware/$s" -o "$OUT/$s.o"; OBJS+=("$OUT/$s.o")
done

# --- link -------------------------------------------------------------------------------
# -nostartfiles drops the default crt0 (Xilinx's xil-crt0.S provides _start) but also
# crti/crtn; add the .init/.fini framing objects back explicitly so _init/_fini resolve.
CRTI=$("$CC" $ARCH -print-file-name=crti.o)
CRTBEGIN=$("$CC" $ARCH -print-file-name=crtbegin.o)
CRTEND=$("$CC" $ARCH -print-file-name=crtend.o)
CRTN=$("$CC" $ARCH -print-file-name=crtn.o)
"$CC" $ARCH -nostartfiles -Wl,--gc-sections -Wl,--build-id=none \
      -Wl,-T,"$BSP/lscript.ld" -Wl,-Map,"$OUT/p3_app.map" \
      -o "$OUT/p3_app.elf" "$CRTI" "$CRTBEGIN" "${OBJS[@]}" \
      -Wl,--start-group -lgcc -lc -lm -Wl,--end-group "$CRTEND" "$CRTN"
echo "LINK OK -> $OUT/p3_app.elf"
"$TC/bin/arm-none-eabi-size" "$OUT/p3_app.elf"
