import socket
import time
import uuid
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import concurrent.futures
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

DEFAULT_PIN = "1234"


class _SpeakerListener(ServiceListener):
    """Listens for Frontier Silicon / Philips Spotify Connect mDNS broadcasts."""
    def __init__(self):
        self.found_ips = set()

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            props = {
                k.decode("utf-8", errors="ignore"): v.decode("utf-8", errors="ignore")
                for k, v in info.properties.items()
                if v is not None
            }
            if props.get("CPath") == "/goform/spotifyConfig":
                for addr in info.parsed_addresses():
                    if "." in addr:
                        self.found_ips.add(addr)

    def update_service(self, zc, type_, name):
        self.add_service(zc, type_, name)

    def remove_service(self, zc, type_, name):
        pass


def discover_speakers(timeout=2.5):
    """Auto-discovers Philips/Frontier Silicon speakers on Windows, Linux, and macOS."""
    speakers = {}
    zc = Zeroconf()
    listener = _SpeakerListener()
    ServiceBrowser(zc, "_spotify-connect._tcp.local.", listener)

    time.sleep(timeout)
    zc.close()

    for ip in listener.found_ips:
        name = get_name(ip)
        if name:
            speakers[name] = ip

    if not speakers:
        speakers = _subnet_fallback_scan()

    return speakers


def _get_local_subnet_prefix():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            return ".".join(local_ip.split(".")[:3]) + "."
    except Exception:
        return "192.168.0."


def _check_ip(ip):
    try:
        with socket.create_connection((ip, 80), timeout=0.35):
            pass
        name = get_name(ip)
        if name:
            return name, ip
    except Exception:
        pass
    return None


def _subnet_fallback_scan():
    prefix = _get_local_subnet_prefix()
    speakers = {}
    ips = [f"{prefix}{i}" for i in range(1, 255)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        for result in executor.map(_check_ip, ips):
            if result:
                name, ip = result
                speakers[name] = ip
    return speakers


def _request(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            xml_data = resp.read().decode("utf-8")
            return ET.fromstring(xml_data)
    except Exception:
        return None


def create_session(ip, pin=DEFAULT_PIN):
    root = _request(f"http://{ip}/fsapi/CREATE_SESSION?pin={pin}")
    if root is not None and root.findtext("status") == "FS_OK":
        return root.findtext("sessionId")
    return None


def delete_session(ip, sid, pin=DEFAULT_PIN):
    _request(f"http://{ip}/fsapi/DELETE_SESSION?pin={pin}&sid={sid}")


def get_node(ip, node, value_type="u8", pin=DEFAULT_PIN):
    sid = create_session(ip, pin)
    if not sid:
        return None
    root = _request(f"http://{ip}/fsapi/GET/{node}?pin={pin}&sid={sid}")
    delete_session(ip, sid, pin)
    if root is not None and root.findtext("status") == "FS_OK":
        return root.findtext(f".//{value_type}")
    return None


def set_node(ip, node, value, pin=DEFAULT_PIN):
    sid = create_session(ip, pin)
    if not sid:
        return False
    encoded_val = urllib.parse.quote(str(value))
    root = _request(f"http://{ip}/fsapi/SET/{node}?pin={pin}&sid={sid}&value={encoded_val}")
    delete_session(ip, sid, pin)
    return root is not None and root.findtext("status") == "FS_OK"


def _set_node_debug(ip, node, value, pin=DEFAULT_PIN):
    sid = create_session(ip, pin)
    if not sid:
        return False, "NO_SESSION"
    encoded_val = urllib.parse.quote(str(value))
    root = _request(f"http://{ip}/fsapi/SET/{node}?pin={pin}&sid={sid}&value={encoded_val}")
    delete_session(ip, sid, pin)
    if root is None:
        return False, "HTTP_ERROR"
    status = root.findtext("status")
    return (status == "FS_OK"), status


# --- System & Identity ---

def get_name(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.sys.info.friendlyName", "c8_array", pin)


def set_name(ip, new_name, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.sys.info.friendlyName", new_name, pin)


def get_version(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.sys.info.version", "c8_array", pin)


def get_wifi_signal(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.sys.net.wlan.rssi", "s8", pin)


# --- Power, Volume & Mute ---

def get_power(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.sys.power", "u8", pin)


def set_power(ip, state, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.sys.power", int(state), pin)


def get_volume(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.sys.audio.volume", "u8", pin)


def set_volume(ip, level, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.sys.audio.volume", int(level), pin)


def get_mute(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.sys.audio.mute", "u8", pin)


def set_mute(ip, muted, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.sys.audio.mute", int(muted), pin)


# --- Playback & Now Playing ---

def play(ip, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.play.control", 1, pin)


def pause(ip, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.play.control", 2, pin)


def next_track(ip, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.play.control", 3, pin)


def prev_track(ip, pin=DEFAULT_PIN):
    return set_node(ip, "netRemote.play.control", 4, pin)


def get_now_playing(ip, pin=DEFAULT_PIN):
    return {
        "status": get_node(ip, "netRemote.play.status", "u8", pin),
        "track": get_node(ip, "netRemote.play.info.name", "c8_array", pin),
        "artist": get_node(ip, "netRemote.play.info.artist", "c8_array", pin),
        "album": get_node(ip, "netRemote.play.info.album", "c8_array", pin),
    }


# --- Multiroom Grouping ---

def get_peer_devices(ip, pin=DEFAULT_PIN):
    """Reads netRemote.multiroom.device.listAll to get peer UDNs, IPs, and group roles."""
    sid = create_session(ip, pin)
    if not sid:
        return []
    root = _request(
        f"http://{ip}/fsapi/LIST_GET_NEXT/netRemote.multiroom.device.listAll/-1?pin={pin}&sid={sid}&maxItems=20"
    )
    delete_session(ip, sid, pin)
    peers = []
    if root is not None:
        for item in root.findall(".//item"):
            entry = {}
            for field in item.findall("field"):
                fname = field.attrib.get("name", "").lower()
                val = "".join(field.itertext()).strip()
                entry[fname] = val
            peers.append(entry)
    return peers


def get_udn_for_target(observer_ip, target_ip, pin=DEFAULT_PIN):
    for peer in get_peer_devices(observer_ip, pin):
        if peer.get("ipaddress") == target_ip:
            udn = peer.get("udn")
            if udn:
                return udn
    for peer in get_peer_devices(target_ip, pin):
        udn = peer.get("udn")
        if udn and peer.get("ipaddress") == target_ip:
            return udn
    return None


def get_group_id(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.multiroom.group.id", "c8_array", pin)


def get_group_role(target_ip, peer_ip=None, pin=DEFAULT_PIN):
    if peer_ip:
        for peer in get_peer_devices(peer_ip, pin):
            if peer.get("ipaddress") == target_ip:
                return peer.get("grouprole", "0")
    gid = get_group_id(target_ip, pin)
    return "Grouped" if gid else "0"


def debug_multiroom(ip, pin=DEFAULT_PIN):
    candidate_nodes = [
        "netRemote.sys.info.version",
        "netRemote.multiroom.caps.maxClients",
        "netRemote.multiroom.caps.protocolVersion",
        "netRemote.multiroom.group.id",
        "netRemote.multiroom.group.create",
        "netRemote.multiroom.group.destroy",
        "netRemote.multiroom.group.addClient",
        "netRemote.multiroom.group.removeClient",
    ]
    sid = create_session(ip, pin)
    if not sid:
        print(f"  Could not create session on {ip}")
        return

    print(f"\n  --- Multiroom Node Scan for {ip} ---")
    for node in candidate_nodes:
        root = _request(f"http://{ip}/fsapi/GET/{node}?pin={pin}&sid={sid}")
        if root is not None:
            status = root.findtext("status")
            val_el = root.find("value")
            val_str = ET.tostring(val_el, encoding="unicode").strip() if val_el is not None else ""
            print(f"  [{status}] {node} {val_str}")

    delete_session(ip, sid, pin)

    peers = get_peer_devices(ip, pin)
    print(f"  Discovered Peers visible to {ip}:")
    for p in peers:
        print(f"    - {p.get('friendlyname')} | IP: {p.get('ipaddress')} | UDN: {p.get('udn')} | Role: {p.get('grouprole')} | GroupID: {p.get('groupid')}")
    print()


def group_speakers(master_ip, client_ip, group_name="Multiroom", pin=DEFAULT_PIN):
    set_power(master_ip, 1, pin)
    set_power(client_ip, 1, pin)

    client_udn = get_udn_for_target(master_ip, client_ip, pin)
    print(f"  [Info] Target Client IP: {client_ip} | Resolved Client UDN: {client_udn}")

    if not client_udn:
        print("  [Error] Could not resolve client speaker UDN. Make sure both speakers are powered on.")
        return False

    _set_node_debug(master_ip, "netRemote.multiroom.group.create", group_name, pin)
    time.sleep(0.4)
    group_id = get_group_id(master_ip, pin)

    if not group_id:
        group_id = str(uuid.uuid4()).upper()
        _set_node_debug(master_ip, "netRemote.multiroom.group.id", group_id, pin)

    print(f"  [Step 1] Master group.id active: {group_id}")

    ok_add, st_add = _set_node_debug(master_ip, "netRemote.multiroom.group.addClient", client_udn, pin)
    print(f"  [Step 2] Master addClient({client_udn}): {st_add}")

    time.sleep(0.8)
    role = get_group_role(client_ip, peer_ip=master_ip, pin=pin)
    print(f"  [Verify] Client grouprole is now: {role} (2 = Client, 1 = Master, 0 = Ungrouped)")
    return ok_add


def ungroup_speaker(ip, pin=DEFAULT_PIN):
    """Resets an individual speaker back to standalone mode."""
    _set_node_debug(ip, "netRemote.multiroom.group.id", "", pin)
    _set_node_debug(ip, "netRemote.multiroom.group.destroy", 1, pin)
    time.sleep(0.3)
    return not get_group_id(ip, pin)