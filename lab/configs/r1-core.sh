#!/bin/sh
set -eu
sysctl -w net.ipv4.ip_forward=1
ip addr add 10.0.0.1/30 dev eth1
ip link set eth1 up
ip route add 192.168.100.0/24 via 10.0.0.2

