#include <stdio.h>
#include <string.h>
#include <irq.h>
#include <uart.h>
#include <console.h>
#include <system.h>
#include <time.h>
#include <generated/csr.h>
#include <hw/flags.h>

#include <lwip/init.h>
#include <lwip/memp.h>
#include <lwip/ip4_addr.h>
#include <lwip/ip4.h>
#include <lwip/netif.h>
#include <lwip/sys.h>
#include <lwip/tcp.h>
#include <lwip/timers.h>

#ifdef CSR_ETHMAC_BASE
#include <netif/etharp.h>
#include <netif/liteethif.h>
#endif
#include <netif/ppp/ppp.h>
#include <netif/ppp/pppos.h>
#include <lwip/sio.h>

#include "bridge_ctl.h"
#include "kloader.h"
#include "flash_storage.h"
#include "clock.h"
#include "test_mode.h"
#include "kserver.h"
#include "session.h"
#include "moninj.h"

u32_t sys_now(void)
{
    return clock_get_ms();
}

u32_t sys_jiffies(void)
{
    return clock_get_ms();
}

#ifdef CSR_ETHMAC_BASE
static struct netif eth_netif;
#endif
static struct netif ppp_netif;
static ppp_pcb *ppp;

static void lwip_service(void)
{
    sys_check_timeouts();
#ifdef CSR_ETHMAC_BASE
    if(ethmac_sram_writer_ev_pending_read() & ETHMAC_EV_SRAM_WRITER) {
        liteeth_input(&eth_netif);
        ethmac_sram_writer_ev_pending_write(ETHMAC_EV_SRAM_WRITER);
    }
#endif
    if(uart_read_nonblock()) {
        u8_t c;
        c = uart_read();
        pppos_input(ppp, &c, 1);
    }
}

#ifdef CSR_ETHMAC_BASE
unsigned char macadr[6];

static int hex2nib(int c)
{
    if((c >= '0') && (c <= '9'))
        return c - '0';
    if((c >= 'a') && (c <= 'f'))
        return c - 'a' + 10;
    if((c >= 'A') && (c <= 'F'))
        return c - 'A' + 10;
    return -1;
}

static void init_macadr(void)
{
    static const unsigned char default_macadr[6] = {0x10, 0xe2, 0xd5, 0x32, 0x50, 0x00};
#if (defined CSR_SPIFLASH_BASE && defined SPIFLASH_PAGE_SIZE)
    char b[32];
    char fs_macadr[6];
    int i, r, s;
#endif

    memcpy(macadr, default_macadr, 6);
#if (defined CSR_SPIFLASH_BASE && defined SPIFLASH_PAGE_SIZE)
    r = fs_read("mac", b, sizeof(b) - 1, NULL);
    if(r <= 0)
        return;
    b[r] = 0;
    for(i=0;i<6;i++) {
        r = hex2nib(b[3*i]);
        s = hex2nib(b[3*i + 1]);
        if((r < 0) || (s < 0))
            return;
        fs_macadr[i] = (r << 4) | s;
    }
    for(i=0;i<5;i++)
        if(b[3*i + 2] != ':')
            return;
    memcpy(macadr, fs_macadr, 6);
#endif
}

static void fsip_or_default(struct ip4_addr *d, char *key, int i1, int i2, int i3, int i4)
{
    int r;
#if (defined CSR_SPIFLASH_BASE && defined SPIFLASH_PAGE_SIZE)
    char cp[32];
#endif

    IP4_ADDR(d, i1, i2, i3, i4);
#if (defined CSR_SPIFLASH_BASE && defined SPIFLASH_PAGE_SIZE)
    r = fs_read(key, cp, sizeof(cp) - 1, NULL);
    if(r <= 0)
        return;
    cp[r] = 0;
    if(!ip4addr_aton(cp, d))
        return;
#endif
}

static void network_init_eth(void)
{
    struct ip4_addr local_ip;
    struct ip4_addr netmask;
    struct ip4_addr gateway_ip;

    init_macadr();
    fsip_or_default(&local_ip, "ip", 192, 168, 0, 42);
    fsip_or_default(&netmask, "netmask", 255, 255, 255, 0);
    fsip_or_default(&gateway_ip, "gateway", 192, 168, 0, 1);

    netif_add(&eth_netif, &local_ip, &netmask, &gateway_ip, 0, liteeth_init, ethernet_input);
    netif_set_default(&eth_netif);
    netif_set_up(&eth_netif);
    netif_set_link_up(&eth_netif);
}
#endif

static void ppp_status_cb(ppp_pcb *pcb, int err_code, void *ctx)
{
}

u32_t sio_write(sio_fd_t fd, u8_t *data, u32_t len)
{
    int i;

    for(i=0;i<len;i++)
        uart_write(data[i]);
    return len;
}

static void network_init_ppp(void)
{
    ppp = pppos_create(&ppp_netif, NULL, ppp_status_cb, NULL);
    ppp_set_auth(ppp, PPPAUTHTYPE_NONE, "", "");
    ppp_set_default(ppp);
    ppp_connect(ppp, 0);
}

static void regular_main(void)
{
    clock_init();
    brg_start();
    brg_ddsinitall();
    kloader_stop();
    lwip_init();
#ifdef CSR_ETHMAC_BASE
    puts("Accepting sessions on Ethernet.");
    network_init_eth();
#endif
    puts("Accepting sessions on serial (PPP).");
    network_init_ppp();
    kserver_init();
    moninj_init();

    session_end();
    while(1) {
        lwip_service();
        kserver_service();
    }
}

static void blink_led(void)
{
    int i, ev, p;

    p = identifier_frequency_read()/10;
    time_init();
    for(i=0;i<3;i++) {
        leds_out_write(1);
        while(!elapsed(&ev, p));
        leds_out_write(0);
        while(!elapsed(&ev, p));
    }
}

static int check_test_mode(void)
{
    char c;

    timer0_en_write(0);
    timer0_reload_write(0);
    timer0_load_write(identifier_frequency_read() >> 2);
    timer0_en_write(1);
    timer0_update_value_write(1);
    while(timer0_value_read()) {
        if(readchar_nonblock()) {
            c = readchar();
            if((c == 't')||(c == 'T'))
                return 1;
        }
        timer0_update_value_write(1);
    }
    return 0;
}

int main(void)
{
    irq_setmask(0);
    irq_setie(1);
    uart_init();

    puts("ARTIQ runtime built "__DATE__" "__TIME__"\n");

    puts("Press 't' to enter test mode...");
    blink_led();

    if(check_test_mode()) {
        puts("Entering test mode.");
        test_main();
    } else {
        puts("Entering regular mode.");
        regular_main();
    }
    return 0;
}
