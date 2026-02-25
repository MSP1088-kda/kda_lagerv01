#!/usr/bin/env bash
set -euo pipefail

# Linux only helper: set hostname + enable Avahi for mDNS (.local)
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Dieses Skript muss als root ausgeführt werden (sudo)." >&2
  exit 1
fi

if [[ "${OSTYPE:-}" == "msys"* || "${OSTYPE:-}" == "cygwin"* ]]; then
  echo "Dieses Skript ist nur für Linux gedacht." >&2
  exit 1
fi

HOSTNAME_NEW="${1:-lager}"
if [[ -z "${HOSTNAME_NEW}" ]]; then
  echo "Bitte Hostname angeben, z. B.: sudo ./scripts/linux_mdns_enable.sh lager" >&2
  exit 1
fi

if command -v hostnamectl >/dev/null 2>&1; then
  hostnamectl set-hostname "${HOSTNAME_NEW}"
else
  echo "hostnamectl nicht gefunden. Bitte Hostname manuell setzen." >&2
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y avahi-daemon avahi-utils
  systemctl enable avahi-daemon
  systemctl restart avahi-daemon
  echo "mDNS aktiviert. Test: ping ${HOSTNAME_NEW}.local"
else
  echo "apt-get nicht gefunden. Bitte Avahi für deine Distribution manuell installieren." >&2
fi

echo "Fertig. App danach im Browser über http://${HOSTNAME_NEW}.local/ prüfen."
