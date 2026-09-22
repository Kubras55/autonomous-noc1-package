# Autonomous NOC Final Demo Rehberi

## 1. Sistemi başlatma

Önce WSL Docker servisini başlatın:

```bash
sudo systemctl start docker
exit
```

Ardından proje klasöründe PowerShell ile:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-final-demo.ps1
```

GNS3'te `Autonomous-NOC-Redundant-OSPF` projesini açın ve tüm düğümleri başlatın.

## 2. NMS üzerindeki izleme süreçleri

NMS-SERVER-1 üzerinde bir konsolda SNMP ajanı:

```sh
python3 /opt/autonomous-noc/nms-snmp-agent.py \
  --backend-url http://10.77.168.68:18001 \
  --interval 10 \
  --failure-threshold 2
```

İkinci konsolda Syslog ajanı:

```sh
python3 /opt/autonomous-noc/nms-syslog-agent.py \
  --backend-url http://10.77.168.68:18001
```

Gerekirse ham loglar üçüncü konsolda izlenebilir:

```sh
tail -f /var/log/network/routers.log
```

## 3. Final arıza senaryosu

R2-CORE-2 üzerinde R1'e giden bağlantıyı kapatın:

```text
enable
configure terminal
interface FastEthernet0/0
shutdown
end
```

Beklenen olaylar:

- Syslog, R2 FastEthernet0/0 arayüzünün kapandığını görür.
- R1, OSPF komşusu 2.2.2.2'nin düştüğünü bildirir.
- Syslog ajanı backend'e iki alarm gönderir.
- Operatör konsolunda arayüz arızası ve OSPF etkisi görünür.
- VLAN100 ve VLAN200 trafiği yedek R3/R4 yollarından devam eder.

İstemci testleri:

```text
ping 10.0.0.1
trace 10.0.0.1
```

## 4. Arızayı giderme

R2-CORE-2 üzerinde:

```text
configure terminal
interface FastEthernet0/0
no shutdown
end
```

Beklenen sonuç:

- Arayüz `up/up` olur.
- OSPF komşuluğu tekrar `FULL` olur.
- Syslog ajanı `resolved` alarmı gönderir.
- Incident, operatör kontrolü için `investigating` durumuna geçer.

## 5. Sunumda açılacak adresler

- Operatör konsolu: http://localhost:8002
- Grafana: http://localhost:3001
- Backend sağlık: http://localhost:8001/health
- Prometheus: http://localhost:9090
- Alertmanager: http://localhost:9093

## 6. Alınması gereken ekran görüntüleri

1. GNS3 yedekli topolojisinin tamamı
2. R2 arayüzünün administratively down olduğu CLI çıktısı
3. Syslog arayüz ve OSPF `DOWN` kayıtları
4. VLAN100 ve VLAN200 başarılı ping/traceroute çıktıları
5. Operatör konsolundaki aktif incident
6. Ollama kök neden analizi ve canlı teşhis sonucu
7. Arayüz açıldıktan sonraki OSPF `FULL` kaydı
8. Grafana genel görünümü

