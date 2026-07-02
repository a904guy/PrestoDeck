"""mDNS discovery for the PrestoDeck host service.

The host advertises itself as ``_prestodeck._tcp.local.``. The device sends a
multicast DNS PTR question to ``224.0.0.251:5353`` over a raw UDP socket and
parses the responses (PTR -> SRV -> A) to resolve ``(host_ip, port)``. A
``config.local.json`` host override, when present, short-circuits discovery.

The wire helpers (``build_query``, ``parse_response``, name (de)compression)
are pure and unit-testable off-device; only ``scan``/``resolve_first`` touch
the network and import ``socket`` lazily.
"""

import struct

from . import clock
from . import log

SERVICE_TYPE = "_prestodeck._tcp.local."
MDNS_ADDR = "224.0.0.251"
MDNS_PORT = 5353

# DNS record type codes.
_TYPE_A = 1
_TYPE_PTR = 12
_TYPE_TXT = 16
_TYPE_SRV = 33


class HostInfo:
    """A resolved host advertisement: address, port, and instance name."""

    def __init__(self, host, port, name=None):
        """Store a single resolved service instance.

        :param host: resolved IPv4 dotted-quad address string.
        :param port: TCP port from the SRV record.
        :param name: optional service instance name.
        """
        self.host = host
        self.port = port
        self.name = name


def _encode_name(name):
    """Encode a dotted DNS name into length-prefixed label bytes. Pure."""
    out = bytearray()
    for label in name.rstrip(".").split("."):
        b = label.encode()
        out.append(len(b))
        out.extend(b)
    out.append(0)
    return bytes(out)


def build_query(service_type=SERVICE_TYPE, txid=0, unicast=True):
    """Build an mDNS PTR query packet for ``service_type``.

    Pure; unit-testable. The question class sets the top "unicast response"
    (QU) bit by default so responders reply unicast straight to our ephemeral
    source port. This lets us query from an unbound socket: binding to 5353
    fails (the firmware's own mDNS responder holds it) and binding to an
    ephemeral port makes the multicast send fail with EINVAL on this lwIP.

    :param service_type: the service to query (default PrestoDeck's).
    :param txid: transaction id (mDNS ignores it; default 0).
    :param unicast: set the QU bit to request a unicast response (default True).
    :returns: the raw DNS query packet as ``bytes``.
    """
    header = struct.pack(">HHHHHH", txid, 0x0000, 1, 0, 0, 0)
    qclass = 0x8001 if unicast else 0x0001
    question = _encode_name(service_type) + struct.pack(">HH", _TYPE_PTR, qclass)
    return header + question


def _read_name(data, offset):
    """Decode a (possibly compressed) DNS name. Returns ``(name, next_off)``.

    Pure; unit-testable. Follows 0xC0 compression pointers.
    """
    labels = []
    jumped = False
    next_off = offset
    pos = offset
    safety = 0
    while True:
        safety += 1
        if safety > 128 or pos >= len(data):
            break
        length = data[pos]
        if length == 0:
            pos += 1
            if not jumped:
                next_off = pos
            break
        if (length & 0xC0) == 0xC0:
            pointer = ((length & 0x3F) << 8) | data[pos + 1]
            if not jumped:
                next_off = pos + 2
            jumped = True
            pos = pointer
            continue
        pos += 1
        labels.append(bytes(data[pos:pos + length]).decode("utf-8", "replace"))
        pos += length
    return ".".join(labels), next_off


def parse_response(data):
    """Parse an mDNS response packet into resolved ``HostInfo`` list.

    Pure; unit-testable. Correlates PTR -> SRV (port + target) -> A (address)
    for the PrestoDeck service type. Records that cannot be fully resolved are
    skipped.

    :param data: raw response packet bytes.
    :returns: list of ``HostInfo`` (empty if nothing usable).
    """
    if len(data) < 12:
        return []
    _id, _flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    pos = 12
    # Skip question section.
    for _ in range(qd):
        _name, pos = _read_name(data, pos)
        pos += 4  # QTYPE + QCLASS

    srv_ports = {}   # target name -> port
    a_addrs = {}     # name -> "a.b.c.d"
    ptr_targets = []  # instance names pointing at our service

    total = an + ns + ar
    for _ in range(total):
        if pos >= len(data):
            break
        rname, pos = _read_name(data, pos)
        if pos + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        rdata_start = pos
        if rtype == _TYPE_PTR:
            target, _ = _read_name(data, rdata_start)
            ptr_targets.append(target)
        elif rtype == _TYPE_SRV:
            if rdlen >= 6:
                _prio, _weight, port = struct.unpack(">HHH", data[rdata_start:rdata_start + 6])
                target, _ = _read_name(data, rdata_start + 6)
                srv_ports[rname] = (port, target)
        elif rtype == _TYPE_A:
            if rdlen >= 4:
                octets = data[rdata_start:rdata_start + 4]
                a_addrs[rname] = "{0}.{1}.{2}.{3}".format(octets[0], octets[1], octets[2], octets[3])
        pos = rdata_start + rdlen

    results = []
    candidates = ptr_targets if ptr_targets else list(srv_ports.keys())
    for inst in candidates:
        srv = srv_ports.get(inst)
        if srv is None:
            continue
        port, target = srv
        ip = a_addrs.get(target)
        if ip is None:
            continue
        results.append(HostInfo(ip, port, inst))
    return results


async def scan(timeout_ms=5000):
    """Scan the LAN for the PrestoDeck host via mDNS.

    Sends the PTR query to the mDNS multicast group, collects datagrams until
    ``timeout_ms`` elapses or a usable record is parsed, and returns the
    resolved hosts. Imports ``socket``/``asyncio`` lazily.

    :param timeout_ms: scan budget in milliseconds (~5s typical).
    :returns: list of ``HostInfo`` (empty if none found).
    """
    import socket

    sock = None
    try:
        # Leave the socket UNBOUND: binding to 5353 collides with the firmware's
        # own mDNS responder (EADDRINUSE) and binding to an ephemeral port makes
        # the multicast send fail (EINVAL) on this lwIP. The QU bit in the query
        # makes the responder reply unicast to this socket's ephemeral port.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        addr = socket.getaddrinfo(MDNS_ADDR, MDNS_PORT)[0][-1]
        sock.sendto(build_query(), addr)

        deadline = clock.ticks_add(clock.ticks_ms(), timeout_ms)
        results = []
        while True:
            if clock.ticks_diff(deadline, clock.ticks_ms()) <= 0:
                break
            try:
                data, _src = sock.recvfrom(1024)
            except OSError:
                await clock.sleep_ms(50)
                continue
            found = parse_response(data)
            if found:
                results.extend(found)
                break
        return results
    finally:
        if sock is not None:
            sock.close()


async def resolve_first(timeout_ms=5000):
    """Return the first resolved host, or ``None`` on timeout.

    :param timeout_ms: discovery budget.
    :returns: a ``HostInfo`` or ``None``.
    """
    hosts = await scan(timeout_ms)
    if hosts:
        log.info("mDNS resolved host {0}:{1}".format(hosts[0].host, hosts[0].port))
        return hosts[0]
    log.warn("mDNS scan found no PrestoDeck host")
    return None
