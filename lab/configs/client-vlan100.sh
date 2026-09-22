#!/bin/sh
set -eu
ip link add link eth1 name eth1.100 type vlan id 100
ip addr add 192.168.100.10/24 dev eth1.100
ip link set eth1 up
ip link set eth1.100 up
# Keep the Docker management default route on eth0 and send only lab
# backbone traffic through the BNG subscriber gateway.
ip route replace 10.0.0.0/8 via 192.168.100.1
