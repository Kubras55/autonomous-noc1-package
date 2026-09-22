#!/bin/sh
set -eu

if ! command -v ip >/dev/null 2>&1; then
  echo "ip command is missing. Install it with: sudo apt install -y iproute2" >&2
  exit 1
fi

if ! ip link show sw-access >/dev/null 2>&1; then
  ip link add name sw-access type bridge
fi

ip link set dev sw-access up
echo "sw-access Linux bridge is ready"
ip -brief link show sw-access
