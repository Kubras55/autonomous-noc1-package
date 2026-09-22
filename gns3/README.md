# GNS3 görsel laboratuvarı

Bu klasör, Containerlab topolojisinin GNS3 üzerindeki görsel eşini kurmak için başlangıç konfigürasyonlarını içerir.

## Görsel topoloji

```text
VPCS-VLAN100 --- SW-ACCESS --- R3-BNG --- R2-EDGE --- R1-CORE
```

## Kablolama

| A ucu | B ucu | Amaç |
|---|---|---|
| R1 `GigabitEthernet0/0` | R2 `GigabitEthernet0/0` | Core–Edge omurga |
| R2 `GigabitEthernet0/1` | R3 `FastEthernet0/0` | Edge–BNG |
| R3 `FastEthernet0/1` | SW-ACCESS port 1 | VLAN 100 trunk |
| VPCS `Ethernet0` | SW-ACCESS port 2 | VLAN 100 access |

Arayüz adları kullanılan IOS imajına göre değişebilir. Cihazınızda `show ip interface brief` ile gerçek adları kontrol edip konfigürasyonları uyarlayın.

## Kurulum

1. GNS3'te `Autonomous-NOC-GNS3` adında proje oluşturun.
2. Çalışma alanına üç router, bir Ethernet switch ve bir VPCS ekleyin.
3. Cihaz adlarını `R1-CORE`, `R2-EDGE`, `R3-BNG`, `SW-ACCESS`, `VPCS-VLAN100` yapın.
4. Yukarıdaki tabloya göre `Add a Link` ile kablolayın.
5. Switch port 1'i VLAN 100 için `dot1q`/trunk, port 2'yi VLAN 100 access olarak ayarlayın.
6. Router konsollarında `configs/` altındaki ilgili komutları uygulayın.
7. VPCS konsolunda `configs/vpcs-vlan100.txt` içindeki komutları uygulayın.

## Doğrulama

VPCS konsolunda:

```text
ping 192.168.100.1
ping 10.0.0.1
```

Router'larda:

```text
show ip interface brief
show ip route
show vlan-switch
```

Son komut kullanılan switch/router imajında bulunmayabilir.

## Hibrit kullanım

- GNS3: görsel çalışma, Cisco CLI, kablo çıkarma ve sunum
- Containerlab: otomatik kurulum, tekrarlanabilir chaos testleri ve CI
- Autonomous NOC: her iki laboratuvardan gelen alarm ve telemetriyi aynı incident/RCA akışında işler

GNS3 yönetim bağlantısı ikinci aşamada eklenecektir. Önce veri topolojisinin ping testleri tamamlanmalıdır.

