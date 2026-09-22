# Autonomous NOC

> Final teslim ve demo adımları için [FINAL-DEMO.md](FINAL-DEMO.md) dosyasını kullanın.

Sanal genişbant ağındaki olayları Prometheus alarmlarından toplayan, incident yaşam döngüsünü yöneten, kök neden analizi yapan ve güvenli müdahale önerileri üreten örnek platform.

## Mimari

- `lab/`: Containerlab üzerinde Core, Edge, BNG, access switch ve VLAN 100 istemcisi
- `gns3/`: Aynı ağın görsel GNS3 kablolama planı ve Cisco CLI başlangıç konfigürasyonları
- `app/`: FastAPI incident API, Alertmanager webhook'u, RCA ve LLM adaptörü
- PostgreSQL: kalıcı incident kayıtları
- Prometheus + Alertmanager: metrik, alarm ve otomatik incident zinciri
- Grafana: servis sağlığı, istek oranı, p95 gecikme ve incident panelleri

## Başlatma

1. `.env.example` dosyasını `.env` olarak kopyalayın ve parolayı değiştirin.
2. WSL Docker'ı başlatın ve PowerShell'de `powershell -ExecutionPolicy Bypass -File scripts\start-final-demo.ps1` çalıştırın.
3. Açın:
   - API/Swagger: http://localhost:8001/docs
   - Operatör konsolu: http://localhost:8002
   - Prometheus: http://localhost:9090
   - Alertmanager: http://localhost:9093
   - Grafana: http://localhost:3001 (`admin` / `admin`)
4. Hızlı test: `powershell -ExecutionPolicy Bypass -File scripts/smoke-test.ps1`

## LLM kullanımı

Varsayılan `LLM_PROVIDER=disabled` iken sistem deterministik RCA kurallarıyla çalışır. OpenAI kullanmak için `.env` içinde `LLM_PROVIDER=openai`, `OPENAI_API_KEY` ve istenen `LLM_MODEL` değerini ayarlayın. API anahtarını Git'e eklemeyin. LLM yalnızca öneri üretir; yüksek riskli komutlar otomatik uygulanmaz.

## Sanal ağ

Containerlab Docker Desktop'ın Windows motorunda doğrudan değil, Linux/WSL içinde çalıştırılmalıdır. Ayrıntılar [lab/README.md](lab/README.md) dosyasındadır. GNS3 alternatifi için aynı IP planı kullanılabilir.

Lab topolojisi devreye alındıktan sonra telemetri ajanını başlatın:

```bash
docker compose --profile lab up -d --build telemetry-agent
docker compose logs -f telemetry-agent
```

Ajan her düğümü 10 saniyede bir kontrol eder. Üç ardışık başarısızlıkta `NetworkNodeDown` incident'ı açar; düğüm tekrar erişilebilir olduğunda incident'ı `resolved` durumuna getirir. Eşik ve hedefler `.env` üzerinden değiştirilebilir. Lab çalışmıyorken ajanı başlatmayın.

## Test

Yerel Python ortamında `pip install -r requirements-dev.txt && pytest -q`; veya backend imajı oluşturulduktan sonra container içinde test bağımlılıklarıyla çalıştırılabilir.
