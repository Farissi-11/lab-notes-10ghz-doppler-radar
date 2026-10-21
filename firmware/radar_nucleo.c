/* =====================================================================
 * Lab Notes - 10 GHz radar, part 1: radar IF output -> NUCLEO-F401RE -> PC
 * Bare-metal version (no CubeMX / HAL needed): flash the .bin by copying it
 * onto the "NOD_F401RE" USB drive that appears when the NUCLEO is plugged in.
 *
 * What it does
 *   - Samples the radar IF output on A0 (PA0 = ADC1_IN0), 5000 samples/s.
 *   - Each sample is the SUM of 16 ADC conversions (oversampling):
 *     finer than one 12-bit step (0.8 mV), about 0.2 mV with the noise.
 *   - Blocks of 4096 samples (0.82 s) are sent to the PC through the ST-LINK
 *     virtual COM port, 115200 bit/s 8N1, frame (little-endian):
 *       "RDR2" + N (uint16) + FS (uint16) + full scale in uV (uint32)
 *       + N x uint16
 *     full scale = 3.3 V / 16, so radar_spectrum.py reads mV = value * fs / 4096.
 *   - Green LED LD2 toggles after each block (= the board is alive).
 *   - Clock: 8 MHz from the ST-LINK quartz (HSE bypass) -> exact 5000 samples/s.
 *     At start-up LD2 gives 3 short flashes = quartz OK ; 1 long flash = no
 *     quartz, internal RC oscillator used (sample rate up to a few % off).
 *
 * Wiring: radar IF -> A0 (CN8 pin 1), radar GND -> GND. Radar +5V stays on the
 * lab supply, NEVER on the NUCLEO. The NUCLEO is powered by its USB cable.
 * ===================================================================== */
#include <stdint.h>
#include "stm32f4xx.h"

#define FS_HZ        5000u
#define N_SAMPLES    4096u
#define BAUD         115200u

static uint16_t buf[N_SAMPLES];
static uint32_t sysclk_hz = 16000000u;   /* HSI after reset */
static uint32_t pclk1_hz  = 16000000u;
static uint32_t n_os      = 4u;          /* conversions summed per sample */
static uint32_t use_hse   = 0u;          /* 1 = 8 MHz from the ST-LINK quartz */

/* ------------------------------------------------------------------ clock */
static void clock_84mhz(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_PWREN;
    (void)RCC->APB1ENR;
    PWR->CR = (PWR->CR & ~PWR_CR_VOS) | (2u << PWR_CR_VOS_Pos);      /* scale 2: up to 84 MHz */
    FLASH->ACR = FLASH_ACR_ICEN | FLASH_ACR_DCEN | FLASH_ACR_PRFTEN | FLASH_ACR_LATENCY_2WS;

    /* 8 MHz clock from the ST-LINK (MCO -> PH0, HSE bypass), quartz accuracy */
    RCC->CR |= RCC_CR_HSEBYP;                                        /* while HSE is off */
    RCC->CR |= RCC_CR_HSEON;
    for (uint32_t t = 0; t < 200000u; t++)
        if (RCC->CR & RCC_CR_HSERDY) { use_hse = 1u; break; }
    if (!use_hse) RCC->CR &= ~(RCC_CR_HSEON | RCC_CR_HSEBYP);         /* fall back to HSI */

    /* HSE 8 MHz / 8 (or HSI 16 MHz / 16) * 336 = 336 MHz VCO ; /4 = 84 MHz ; /7 = 48 MHz */
    RCC->PLLCFGR = ((use_hse ? 8u : 16u) << RCC_PLLCFGR_PLLM_Pos) | (336u << RCC_PLLCFGR_PLLN_Pos)
                 | (1u << RCC_PLLCFGR_PLLP_Pos) | (7u << RCC_PLLCFGR_PLLQ_Pos)
                 | (use_hse ? RCC_PLLCFGR_PLLSRC_HSE : RCC_PLLCFGR_PLLSRC_HSI);
    RCC->CR |= RCC_CR_PLLON;
    for (uint32_t t = 0; !(RCC->CR & RCC_CR_PLLRDY); t++)
        if (t > 200000u) return;                                     /* stay on HSI */

    RCC->CFGR = RCC_CFGR_HPRE_DIV1 | RCC_CFGR_PPRE1_DIV2 | RCC_CFGR_PPRE2_DIV1;
    RCC->CFGR |= RCC_CFGR_SW_PLL;
    for (uint32_t t = 0; (RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL; t++)
        if (t > 200000u) { RCC->CFGR &= ~RCC_CFGR_SW; return; }

    sysclk_hz = 84000000u;
    pclk1_hz  = 42000000u;
    n_os      = 16u;
}

/* ------------------------------------------------------------------ gpio */
static void gpio_init(void)
{
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;
    (void)RCC->AHB1ENR;
    /* PA0 analog (ADC1_IN0) */
    GPIOA->MODER |= (3u << (0 * 2));
    /* PA2 / PA3 = USART2 TX / RX (AF7) -> ST-LINK virtual COM port */
    GPIOA->MODER = (GPIOA->MODER & ~((3u << (2 * 2)) | (3u << (3 * 2))))
                 | (2u << (2 * 2)) | (2u << (3 * 2));
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~((0xFu << (2 * 4)) | (0xFu << (3 * 4))))
                  | (7u << (2 * 4)) | (7u << (3 * 4));
    /* PA5 = green LED LD2, output */
    GPIOA->MODER = (GPIOA->MODER & ~(3u << (5 * 2))) | (1u << (5 * 2));
}

/* ------------------------------------------------------------------ uart */
static void uart_init(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_USART2EN;
    (void)RCC->APB1ENR;
    USART2->CR1 = 0;
    USART2->BRR = (pclk1_hz + BAUD / 2u) / BAUD;                      /* 42 MHz: 365 */
    USART2->CR1 = USART_CR1_TE | USART_CR1_UE;
}

static void uart_write(const uint8_t *p, uint32_t n)
{
    while (n--) {
        while (!(USART2->SR & USART_SR_TXE)) { }
        USART2->DR = *p++;
    }
    while (!(USART2->SR & USART_SR_TC)) { }
}

/* ------------------------------------------------------------------ adc */
static void adc_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_ADC1EN;
    (void)RCC->APB2ENR;
    ADC1_COMMON->CCR = (ADC1_COMMON->CCR & ~ADC_CCR_ADCPRE) | ADC_CCR_ADCPRE_0;  /* PCLK2 / 4 */
    ADC1->CR1 = 0;                                                   /* 12 bits */
    ADC1->CR2 = 0;                                                   /* single conversion */
    ADC1->SMPR2 = (ADC1->SMPR2 & ~ADC_SMPR2_SMP0) | (6u << ADC_SMPR2_SMP0_Pos);  /* 144 cycles */
    ADC1->SQR1 = 0;                                                  /* 1 conversion */
    ADC1->SQR3 = 0;                                                  /* channel 0 = PA0 */
    ADC1->CR2 |= ADC_CR2_ADON;
    for (volatile uint32_t i = 0; i < 1000u; i++) { }               /* ADC wake-up */
}

static inline uint32_t adc_read(void)
{
    ADC1->CR2 |= ADC_CR2_SWSTART;
    while (!(ADC1->SR & ADC_SR_EOC)) { }
    return ADC1->DR & 0x0FFFu;                                       /* reading clears EOC */
}

/* ------------------------------------------------------------------ timing */
static void cycle_counter_init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static void delay_ms(uint32_t ms)
{
    const uint32_t t0 = DWT->CYCCNT, n = ms * (sysclk_hz / 1000u);
    while ((uint32_t)(DWT->CYCCNT - t0) < n) { }
}

static void startup_flash(void)                                      /* clock source on LD2 */
{
    if (use_hse) {
        for (int i = 0; i < 3; i++) {
            GPIOA->ODR |= (1u << 5);  delay_ms(120);
            GPIOA->ODR &= ~(1u << 5); delay_ms(180);
        }
    } else {
        GPIOA->ODR |= (1u << 5);  delay_ms(1000);
        GPIOA->ODR &= ~(1u << 5); delay_ms(300);
    }
}

/* ------------------------------------------------------------------ main */
int main(void)
{
    clock_84mhz();
    gpio_init();
    uart_init();
    adc_init();
    cycle_counter_init();
    startup_flash();

    const uint32_t period = sysclk_hz / FS_HZ;                       /* 16800 cycles = 200 us */
    const uint32_t fullscale_uv = 3300000u / n_os;                   /* 206250 uV with 16x */

    for (;;) {
        /* 1) acquire one block, one sample every 200 us */
        uint32_t t = DWT->CYCCNT;
        for (uint32_t i = 0; i < N_SAMPLES; i++) {
            while ((uint32_t)(DWT->CYCCNT - t) < period) { }
            t += period;
            uint32_t s = 0;
            for (uint32_t k = 0; k < n_os; k++) s += adc_read();     /* 16 x 7.4 us = 119 us */
            buf[i] = (uint16_t)s;
        }

        /* 2) send it to the PC */
        const uint8_t hdr[12] = {
            'R', 'D', 'R', '2',
            (uint8_t)(N_SAMPLES & 0xFFu), (uint8_t)(N_SAMPLES >> 8),
            (uint8_t)(FS_HZ & 0xFFu),     (uint8_t)(FS_HZ >> 8),
            (uint8_t)(fullscale_uv & 0xFFu),         (uint8_t)((fullscale_uv >> 8) & 0xFFu),
            (uint8_t)((fullscale_uv >> 16) & 0xFFu), (uint8_t)((fullscale_uv >> 24) & 0xFFu)
        };
        uart_write(hdr, sizeof hdr);
        uart_write((const uint8_t *)buf, sizeof buf);

        GPIOA->ODR ^= (1u << 5);                                     /* LD2 = alive */
    }
}

/* ------------------------------------------------------------------ startup */
extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;

void Reset_Handler(void)
{
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;
    for (dst = &_sbss; dst < &_ebss; ) *dst++ = 0;
    main();
    for (;;) { }
}

void Default_Handler(void)
{
    for (;;) { GPIOA->ODR |= (1u << 5); }                           /* LED stays on = fault */
}

__attribute__((section(".isr_vector"), used))
void (* const vectors[16])(void) = {
    (void (*)(void))(&_estack),   /* initial stack pointer */
    Reset_Handler,                /* reset */
    Default_Handler,              /* NMI */
    Default_Handler,              /* HardFault */
    Default_Handler,              /* MemManage */
    Default_Handler,              /* BusFault */
    Default_Handler,              /* UsageFault */
    0, 0, 0, 0,
    Default_Handler,              /* SVCall */
    Default_Handler,              /* DebugMonitor */
    0,
    Default_Handler,              /* PendSV */
    Default_Handler,              /* SysTick */
};
