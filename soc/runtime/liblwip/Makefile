include $(MSCDIR)/software/common.mak

LWIPDIR=../lwip/src

CFLAGS += $(CPPFLAGS) -I. \
	-I$(LWIPDIR)/include \
	-I$(LWIPDIR)/include/ipv4

# COREFILES, CORE4FILES: The minimum set of files needed for lwIP.
COREOBJS=$(LWIPDIR)/core/mem.o \
	$(LWIPDIR)/core/memp.o \
	$(LWIPDIR)/core/netif.o \
	$(LWIPDIR)/core/pbuf.o \
	$(LWIPDIR)/core/raw.o \
	$(LWIPDIR)/core/stats.o \
	$(LWIPDIR)/core/sys.o \
	$(LWIPDIR)/core/tcp.o \
	$(LWIPDIR)/core/tcp_in.o \
	$(LWIPDIR)/core/tcp_out.o \
	$(LWIPDIR)/core/udp.o \
	$(LWIPDIR)/core/dhcp.o \
	$(LWIPDIR)/core/inet_chksum.o \
	$(LWIPDIR)/core/timers.o \
	$(LWIPDIR)/core/init.o

CORE4OBJS=$(LWIPDIR)/core/ipv4/icmp.o \
	$(LWIPDIR)/core/ipv4/ip4.o \
	$(LWIPDIR)/core/ipv4/ip4_addr.o \
	$(LWIPDIR)/core/ipv4/ip_frag.o

# NETIFOBJS: Files implementing various generic network interface functions.
NETIFOBJS=$(LWIPDIR)/netif/etharp.o  \
	netif/liteethif.o

PPPOBJS=$(LWIPDIR)/netif/ppp/auth.o \
	$(LWIPDIR)/netif/ppp/ccp.o \
	$(LWIPDIR)/netif/ppp/chap-md5.o \
	$(LWIPDIR)/netif/ppp/chap_ms.o \
	$(LWIPDIR)/netif/ppp/chap-new.o \
	$(LWIPDIR)/netif/ppp/demand.o \
	$(LWIPDIR)/netif/ppp/eap.o \
	$(LWIPDIR)/netif/ppp/ecp.o \
	$(LWIPDIR)/netif/ppp/eui64.o \
	$(LWIPDIR)/netif/ppp/fsm.o \
	$(LWIPDIR)/netif/ppp/ipcp.o \
	$(LWIPDIR)/netif/ppp/ipv6cp.o \
	$(LWIPDIR)/netif/ppp/lcp.o \
	$(LWIPDIR)/netif/ppp/magic.o \
	$(LWIPDIR)/netif/ppp/mppe.o \
	$(LWIPDIR)/netif/ppp/multilink.o \
	$(LWIPDIR)/netif/ppp/ppp.o \
	$(LWIPDIR)/netif/ppp/pppcrypt.o \
	$(LWIPDIR)/netif/ppp/pppoe.o \
	$(LWIPDIR)/netif/ppp/pppol2tp.o \
	$(LWIPDIR)/netif/ppp/pppos.o \
	$(LWIPDIR)/netif/ppp/upap.o \
	$(LWIPDIR)/netif/ppp/utils.o \
	$(LWIPDIR)/netif/ppp/vj.o

# LWIPOBJS: All the above.
LWIPOBJS=$(COREOBJS) $(CORE4OBJS) $(NETIFOBJS) $(PPPOBJS)
OBJS_LIB+=$(LWIPOBJS)

LWIPLIB=liblwip.a

all: $(LWIPLIB)

.PHONY: all compile clean

%.o: %.c
	$(compile-dep)

%.o: %.S
	$(assemble)

clean:
	rm -f $(LWIPOBJS) $(LWIPOBJS:.o=.d) $(LWIPLIB)

liblwip.a: $(LWIPOBJS)
	$(AR) clr liblwip.a $(LWIPOBJS)
	$(RANLIB) liblwip.a
