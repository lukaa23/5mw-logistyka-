"""Adresy laptopa w sieci lokalnej — do podania telefonom, gdy serwer działa w trybie sieciowym."""

import ipaddress
import socket


def private_ipv4(candidates):
    """Zostawia unikalne, prywatne adresy IPv4 (bez loopback i link-local), posortowane."""
    result = set()
    for raw in candidates:
        try:
            address = ipaddress.ip_address(str(raw).strip())
        except ValueError:
            continue
        if address.version != 4 or address.is_loopback or address.is_link_local or address.is_unspecified:
            continue
        if address.is_private:
            result.add(address)
    return [str(address) for address in sorted(result)]


def local_addresses():
    candidates = []
    try:
        candidates += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # UDP: nic nie jest wysyłane, system wybiera interfejs
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass
    return private_ipv4(candidates)


def lan_urls(port, addresses=None):
    found = local_addresses() if addresses is None else private_ipv4(addresses)
    return [f"http://{address}:{port}" for address in found]
