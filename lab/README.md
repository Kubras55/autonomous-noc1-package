# Sanal ağ laboratuvarı

Topoloji: `R1 Core -- R2 Edge -- R3 BNG -- Access Switch -- VLAN 100 Client`.

Adres planı:

| Bağlantı | Ağ | Uçlar |
|---|---|---|
| R1–R2 | 10.0.0.0/30 | R1 `.1`, R2 `.2` |
| R2–R3 | 10.0.0.4/30 | R2 `.5`, R3 `.6` |
| VLAN 100 | 192.168.100.0/24 | BNG `.1`, istemci `.10` |

Linux/WSL ortamında Containerlab kurulduktan sonra:

```bash
cd lab
sudo apt install -y iproute2 iptables
sudo sh setup-host.sh
sudo containerlab deploy -t topology.clab.yml
docker exec clab-autonomous-noc-client-vlan100 ping -c 4 192.168.100.1
sudo containerlab destroy -t topology.clab.yml
```

`kind: bridge` mevcut bir Linux bridge kullanır; Containerlab bu bridge'i kendisi oluşturmaz. `setup-host.sh`, `sw-access` bridge'ini güvenli ve tekrarlanabilir biçimde hazırlar.
