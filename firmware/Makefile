# p3 firmware — host twin only.
#
# `make twin` builds the HOST driver (p3_twin.c + p3_derive.c) that the test suite drives
# over the pinned corpus. It is host tooling, not a board image.
#
# The board application (`p3_app.c`) is cross-compiled by `firmware/bsp/build.sh`, NOT here:
# that script drives the pinned xPack arm-none-eabi-gcc 14.2.1 and a hand-assembled cortex-a9
# standalone BSP to produce firmware/bsp/out/p3_app.elf (docs/l5_findings.md). `make twin`
# below is unchanged — it builds only the HOST driver the corpus test uses.

CC      ?= cc
CFLAGS  ?= -std=c99 -O2 -Wall -Wextra -Werror -pedantic
BUILD   ?= build

.PHONY: twin wire clean
twin: $(BUILD)/p3_twin
wire: $(BUILD)/p3_wire_twin

$(BUILD)/p3_twin: p3_twin.c p3_derive.c p3_derive.h p3_data.h
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -o $@ p3_twin.c p3_derive.c

# The wire twin exposes p3_wire.c -- the application's ACTUAL serialisation -- so
# tests/test_firmware_wire_contract.py can feed the bytes the board emits to the real
# validator. Same source as the image links; that is the whole point.
$(BUILD)/p3_wire_twin: p3_wire_twin.c p3_wire.c p3_derive.c p3_wire.h p3_derive.h p3_data.h
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -o $@ p3_wire_twin.c p3_wire.c p3_derive.c

clean:
	rm -rf $(BUILD)

# --- board image, for the record only (needs an authorisation and a toolchain) ---------
# CROSS      = arm-none-eabi-
# BSP        = <standalone_v9_4 + devcfg_v3_9 built for cortex-a9>
# APP_CFLAGS = -std=c99 -O2 -Wall -Wextra -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard
# $(CROSS)gcc $(APP_CFLAGS) -I$(BSP)/include -o p3_app.elf p3_app.c p3_derive.c \
#     -L$(BSP)/lib -lxil -Tlscript.ld
