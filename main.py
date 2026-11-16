import sys
import site
import subprocess
import importlib
import importlib.util

REQUIRED_PACKAGES = ["zeroconf"]


def ensure_dependencies():
    """Automatically installs any missing pip packages on Windows or Linux."""
    for pkg in REQUIRED_PACKAGES:
        if importlib.util.find_spec(pkg) is None:
            print(f"Installing missing dependency: {pkg}...")
            cmd = [sys.executable, "-m", "pip", "install", pkg]
            try:
                subprocess.check_call(cmd)
            except subprocess.CalledProcessError:
                subprocess.check_call(cmd + ["--break-system-packages"])

            user_site = site.getusersitepackages()
            if user_site not in sys.path:
                sys.path.append(user_site)
            importlib.invalidate_caches()


ensure_dependencies()

import speaker_api as api  # noqa: E402


def prompt_speaker(speakers, prompt_text="Which speaker?"):
    """Displays numbered speakers and lets the user pick by number or full name (spaces supported)."""
    if not speakers:
        print("  No speakers found yet. Run 'scan' first.")
        return None, None

    names = list(speakers.keys())
    print(f"\n  Available speakers:")
    for idx, name in enumerate(names, start=1):
        print(f"    {idx}. {name} ({speakers[name]})")

    choice = input(f"  {prompt_text} (enter number or name): ").strip()
    if not choice:
        print("  Cancelled.")
        return None, None

    # Allow selecting by number (e.g., "1")
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            selected = names[idx]
            return selected, speakers[selected]

    # Allow selecting by exact or case-insensitive name with spaces (e.g., "Dining Room")
    for name, ip in speakers.items():
        if name.lower() == choice.lower():
            return name, ip

    print(f"  Could not find speaker '{choice}'.")
    return None, None


def print_help():
    print("""
Available Commands (just type the command and follow the prompts):
  list      - Show all discovered speakers
  scan      - Re-scan the network for speakers
  rename    - Rename a speaker (supports spaces like "Dining Room")
  group     - Link two speakers together for multiroom playback
  ungroup   - Separate two grouped speakers
  volume    - Change a speaker's volume (0-20)
  power     - Turn a speaker on or put it into standby
  mute      - Mute or unmute a speaker
  play      - Resume playback on a speaker
  pause     - Pause playback on a speaker
  next      - Skip to the next track
  prev      - Go back to the previous track
  status    - Check power, volume, group state & current track
  help      - Show this menu
  exit      - Quit
""")


def main():
    print("Scanning network for Philips SW700M/05 speakers...")
    speakers = api.discover_speakers()

    if not speakers:
        print("No speakers found. (Make sure you are on the same network/subnet as the speakers.)")
    else:
        print("Found speakers:")
        for name, ip in speakers.items():
            print(f"  - {name} ({ip})")

    print_help()

    while True:
        try:
            cmd = input("speaker> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not cmd:
            continue

        if cmd in ("exit", "quit"):
            break

        elif cmd == "help":
            print_help()

        elif cmd == "list":
            if not speakers:
                print("  No speakers cached. Type 'scan' to search again.")
            else:
                for idx, (name, ip) in enumerate(speakers.items(), start=1):
                    print(f"  {idx}. {name} ({ip})")

        elif cmd == "scan":
            print("Scanning network...")
            speakers = api.discover_speakers()
            if not speakers:
                print("  No speakers found.")
            else:
                for idx, (name, ip) in enumerate(speakers.items(), start=1):
                    print(f"  {idx}. {name} ({ip})")

        elif cmd == "rename":
            old_name, ip = prompt_speaker(speakers, "Which speaker do you want to rename?")
            if not ip:
                continue

            new_name = input(f"  Enter new name for '{old_name}' (spaces allowed): ").strip()
            if not new_name:
                print("  Cancelled (name cannot be empty).")
                continue

            if api.set_name(ip, new_name):
                del speakers[old_name]
                speakers[new_name] = ip
                print(f"  Success: Renamed '{old_name}' -> '{new_name}'")
            else:
                print("  Failed to rename speaker.")

        elif cmd == "group":
            m_name, m_ip = prompt_speaker(speakers, "Select the MAIN (master) speaker")
            if not m_ip:
                continue

            c_name, c_ip = prompt_speaker(speakers, f"Select the speaker to link to '{m_name}'")
            if not c_ip:
                continue

            if m_ip == c_ip:
                print("  You cannot group a speaker with itself.")
                continue

            ok = api.group_speakers(m_ip, c_ip)
            print(f"  Grouped '{m_name}' + '{c_name}': {'Success' if ok else 'Failed'}")

        elif cmd == "ungroup":
            m_name, m_ip = prompt_speaker(speakers, "Select the MAIN (master) speaker")
            if not m_ip:
                continue

            c_name, c_ip = prompt_speaker(speakers, f"Select the speaker to unlink from '{m_name}'")
            if not c_ip:
                continue

            ok = api.ungroup_speakers(m_ip, c_ip)
            print(f"  Ungrouped '{m_name}' and '{c_name}': {'Success' if ok else 'Failed'}")

        elif cmd in ("volume", "vol"):
            name, ip = prompt_speaker(speakers, "Which speaker's volume do you want to change?")
            if not ip:
                continue

            current_vol = api.get_volume(ip)
            level = input(f"  Enter volume for '{name}' (0-20, currently {current_vol}): ").strip()
            if not level.isdigit():
                print("  Cancelled (please enter a valid number).")
                continue

            ok = api.set_volume(ip, int(level))
            print(f"  Set volume on '{name}' to {level}: {'Success' if ok else 'Failed'}")

        elif cmd == "power":
            name, ip = prompt_speaker(speakers, "Which speaker do you want to turn on/off?")
            if not ip:
                continue

            choice = input(f"  Turn '{name}' ON or OFF? (on/off): ").strip().lower()
            if choice not in ("on", "off"):
                print("  Cancelled (please enter 'on' or 'off').")
                continue

            ok = api.set_power(ip, 1 if choice == "on" else 0)
            print(f"  Power {choice.upper()} on '{name}': {'Success' if ok else 'Failed'}")

        elif cmd == "mute":
            name, ip = prompt_speaker(speakers, "Which speaker do you want to mute/unmute?")
            if not ip:
                continue

            choice = input(f"  Mute or unmute '{name}'? (mute/unmute): ").strip().lower()
            if choice in ("mute", "on", "yes"):
                state, label = 1, "Muted"
            elif choice in ("unmute", "off", "no"):
                state, label = 0, "Unmuted"
            else:
                print("  Cancelled (please enter 'mute' or 'unmute').")
                continue

            ok = api.set_mute(ip, state)
            print(f"  {label} '{name}': {'Success' if ok else 'Failed'}")

        elif cmd in ("play", "pause", "next", "prev"):
            name, ip = prompt_speaker(speakers, f"Which speaker should '{cmd}' run on?")
            if not ip:
                continue

            func = {
                "play": api.play,
                "pause": api.pause,
                "next": api.next_track,
                "prev": api.prev_track,
            }[cmd]
            print(f"  {cmd.capitalize()} on '{name}': {'Success' if func(ip) else 'Failed'}")

        elif cmd == "status":
            name, ip = prompt_speaker(speakers, "Which speaker's status do you want to check?")
            if not ip:
                continue

            np = api.get_now_playing(ip)
            group_map = {"0": "Standalone (Ungrouped)", "1": "Group Master", "2": "Group Client"}
            g_state = api.get_group_state(ip)
            print(f"\n  --- {name} ({ip}) ---")
            print(f"    Power:  {'On' if api.get_power(ip) == '1' else 'Standby'}")
            print(f"    Volume: {api.get_volume(ip)} (Muted: {'Yes' if api.get_mute(ip) == '1' else 'No'})")
            print(f"    Group:  {group_map.get(g_state, g_state)} (ID: {api.get_group_id(ip)})")
            print(f"    Track:  {np['track']} - {np['artist']}\n")

        else:
            print(f"  Unknown command '{cmd}'. Type 'help' to see available commands.")


if __name__ == "__main__":
    main()