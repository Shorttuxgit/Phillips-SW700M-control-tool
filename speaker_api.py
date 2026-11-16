import socket
import time
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
            # Check TXT records for Frontier Silicon's signature path
            props = {
                k.decode("utf-8", errors="ignore"): v.decode("utf-8", errors="ignore")
                for k, v in info.properties.items()
                if v is not None
            }
            if props.get("CPath") == "/goform/spotifyConfig":
                for addr in info.parsed_addresses():
                    if "." in addr:  # IPv4 only
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
    browser = ServiceBrowser(zc, "_spotify-connect._tcp.local.", listener)

    time.sleep(timeout)
    zc.close()

    for ip in listener.found_ips:
        name = get_name(ip)
        if name:
            speakers[name] = ip

    # Fallback: if mDNS is blocked by a firewall, scan the local /24 subnet directly
    if not speakers:
        speakers = _subnet_fallback_scan()

    return speakers


def _get_local_subnet_prefix():
    """Detects the active local IPv4 subnet (e.g., '192.168.0.')."""
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

def get_group_state(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.multiroom.group.state", "u8", pin)


def get_group_id(ip, pin=DEFAULT_PIN):
    return get_node(ip, "netRemote.multiroom.group.id", "c8_array", pin)


def group_speakers(master_ip, client_ip, pin=DEFAULT_PIN):
    if get_group_state(master_ip, pin) != "1":
        set_node(master_ip, "netRemote.multiroom.group.state", 1, pin)

    group_id = get_group_id(master_ip, pin)
    if not group_id:
        return False

    set_node(client_ip, "netRemote.multiroom.group.state", 2, pin)
    ok_client = set_node(client_ip, "netRemote.multiroom.group.id", group_id, pin)
    ok_master = set_node(master_ip, "netRemote.multiroom.group.addClient", client_ip, pin)
    return ok_client or ok_master


def ungroup_speakers(master_ip, client_ip, pin=DEFAULT_PIN):
    set_node(master_ip, "netRemote.multiroom.group.removeClient", client_ip, pin)
    ok_client = set_node(client_ip, "netRemote.multiroom.group.state", 0, pin)
    set_node(master_ip, "netRemote.multiroom.group.state", 0, pin)
    return ok_client