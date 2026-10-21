# Build the NUCLEO-F401RE firmware with the GNU Arm toolchain (arm-none-eabi-gcc).
# "make" downloads the CMSIS headers (Apache-2.0, from ST and Arm) the first time.
CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
CFLAGS  = -mcpu=cortex-m4 -mthumb -mfloat-abi=soft -O2 -Wall -Wextra -ffreestanding \
          -DSTM32F401xE -Icmsis
LDFLAGS = -nostdlib -T stm32f401re.ld -Wl,--gc-sections
ST  = https://raw.githubusercontent.com/STMicroelectronics/cmsis_device_f4/master/Include
ARM = https://raw.githubusercontent.com/ARM-software/CMSIS_5/develop/CMSIS/Core/Include
HDR = stm32f401xe.h stm32f4xx.h system_stm32f4xx.h
CORE = core_cm4.h cmsis_version.h cmsis_compiler.h cmsis_gcc.h mpu_armv7.h

all: radar_nucleo_f401re.bin

cmsis/.done:
	mkdir -p cmsis
	for f in $(HDR);  do curl -sSfL -o cmsis/$$f $(ST)/$$f;  done
	for f in $(CORE); do curl -sSfL -o cmsis/$$f $(ARM)/$$f; done
	touch $@

radar_nucleo.elf: radar_nucleo.c stm32f401re.ld cmsis/.done
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ radar_nucleo.c -lgcc

radar_nucleo_f401re.bin: radar_nucleo.elf
	$(OBJCOPY) -O binary $< $@

clean:
	rm -f radar_nucleo.elf

.PHONY: all clean
