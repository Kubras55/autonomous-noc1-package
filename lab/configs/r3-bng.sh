#!/bin/sh
set -eu
sysctl -w net.ipv4.ip_forward=1
ip addr add 10.0.0.6/30 dev eth1
ip link set eth1 up
ip link add link eth2 name eth2.100 type vlan id 100
ip addr add 192.168.100.1/24 dev eth2.100
ip link set eth2 up
ip link set eth2.100 up
ip route add 10.0.0.0/30 via 10.0.0.5

