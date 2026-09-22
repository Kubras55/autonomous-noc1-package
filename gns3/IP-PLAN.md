# IP adresleme planı

| Segment | Ağ | Cihaz/aralık |
|---|---|---|
| Core–Edge | `10.0.0.0/30` | R1 `.1`, R2 `.2` |
| Edge–BNG | `10.0.0.4/30` | R2 `.5`, R3 `.6` |
| Abone VLAN 100 | `192.168.100.0/24` | BNG `.1`, VPCS `.10` |
| Yönetim (sonraki aşama) | `172.31.255.0/24` | NOC `.1`, R1 `.11`, R2 `.12`, R3 `.13` |

