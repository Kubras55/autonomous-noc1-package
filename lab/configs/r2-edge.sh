#!/bin/sh
set -eu
sysctl -w net.ipv4.ip_forward=1
ip addr add 10.0.0.2/30 dev eth1
ip addr add 10.0.0.5/30 dev eth2
ip link set eth1 up
ip link set eth2 up
ip route add 192.168.100.0/24 via 10.0.0.6

