# Haber Trade Ajanı (X → Claude → Kripto Vadeli)

Seçtiğiniz X hesaplarının paylaşımlarını takip eder, her yeni paylaşımı Claude ile analiz eder.
Olumlu haberde **long**, olumsuz haberde **short** açar. Pozisyonlar stop-loss, take-profit ve
süre limitiyle yönetilir. Telefondan giriş kodlu bir web panelle kontrol edilir.

```
Zamanlayıcı (dakikada 1) → /api/tick → X'ten yeni paylaşımlar → Claude analizi → filtreler → ccxt ile emir
Telefon → web panel (giriş kodu) → durum, pozisyon kapatma, duraklat, haber testi
Veriler → Upstash Redis
```

> ⚠️ Varsayılan mod `dry_run` (kâğıt üzerinde işlem). Gerçek emir göndermez. Bu bir yatırım tavsiyesi değildir.

---

## Vercel'e kurulum

### 1. Projeyi içe aktarın
vercel.com → **Add New → Project** → bu GitHub reposunu seçin → **Deploy**.
Vercel Flask uygulamasını (`app.py`) kendisi tanır, ek ayar gerekmez.
Fonksiyonlar Frankfurt'ta (`fra1`) çalışır, çünkü bazı borsalar ABD IP'lerini engeller.

### 2. Redis ekleyin (zorunlu)
Proje → **Storage** → **Upstash (Redis)** → oluşturun ve projeye bağlayın.
`KV_REST_API_URL` ve `KV_REST_API_TOKEN` otomatik eklenir.

### 3. Ortam değişkenlerini girin
Proje → **Settings → Environment Variables**:

| Değişken | Değer |
|---|---|
| `WEB_CODE` | Panel giriş kodu (ör. `kadir`; sonra güçlü bir kodla değiştirin) |
| `CRON_SECRET` | Uzun, rastgele bir metin (zamanlayıcı için) |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `X_BEARER_TOKEN` | developer.x.com (tweet okumak için ücretli plan gerekir) |
| `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` | Sadece testnet/live için. **Çekim yetkisini asla açmayın** |
| `TRADE_MODE` | İsteğe bağlı: `dry_run` / `testnet` / `live` |

Değişkenleri girdikten sonra **Deployments → Redeploy** yapın.

### 4. Zamanlayıcıyı kurun (zorunlu)
Vercel'in ücretsiz (Hobby) planı zamanlanmış görevleri **günde bir kez** çalıştırır. Bu yüzden haber
kontrolünü ücretsiz bir dış zamanlayıcı tetikler:

1. [cron-job.org](https://cron-job.org) → ücretsiz hesap → **Create cronjob**
2. URL: `https://PROJENIZ.vercel.app/api/tick`
3. Schedule: **Every 1 minute**
4. Advanced → Headers → `Authorization` = `Bearer CRON_SECRET_DEĞERİNİZ`
   (Header ekleyemiyorsanız URL'yi `.../api/tick?key=CRON_SECRET_DEĞERİNİZ` yapın)

> Vercel Pro planınız varsa bunun yerine `vercel.json` içine
> `"crons": [{"path": "/api/tick", "schedule": "* * * * *"}]` ekleyebilirsiniz.
> Vercel, `CRON_SECRET` değerini otomatik olarak gönderir.

Panel açıkken zamanlayıcı gecikirse turu panel kendisi de tetikler.

### 5. Telefondan açın
`https://PROJENIZ.vercel.app` → giriş kodu → panel. Tarayıcıda **Ana ekrana ekle** ile uygulama gibi kullanın.

---

## Ayarlar (`config.yaml`)
Takip edilen hesaplar, coin listesi, kaldıraç, stop-loss ve take-profit oranları gibi ayarlar burada.
Değiştirip GitHub'a gönderdiğinizde Vercel otomatik olarak yeniden yayınlar.
**Repo herkese açıksa bu dosyaya anahtar veya şifre yazmayın.**

| Ayar | Açıklama |
|---|---|
| `min_confidence`, `min_abs_score` | Claude emin değilse veya haber zayıfsa işlem açılmaz |
| `max_tweet_age_seconds` | Eski haberlerle işlem açılmaz |
| `allowed_assets` | Sadece bu coinlerde işlem yapılır |
| `stop_loss_pct` / `take_profit_pct` | Borsaya koruyucu emir olarak yazılır, ajan çalışmasa da geçerlidir |
| `max_hold_minutes` | Bu süre dolunca pozisyon kapatılır |
| `max_open_positions`, `max_trades_per_day`, `cooldown_minutes` | Aşırı işlemi engeller |

## Güvenlik
- Giriş kodu ve tüm anahtarlar yalnızca Vercel ortam değişkenlerinde durur, kodda yoktur.
- Aynı IP'den 5 hatalı girişten sonra o IP 15 dakika kilitlenir. Toplam deneme sayısı da sınırlıdır.
- `/api/tick` adresi yalnızca `CRON_SECRET` ile veya giriş yapmış kullanıcı tarafından çağrılabilir.
- Live mod için hem `TRADE_MODE=live` hem de `LIVE_ONAY=true` gerekir.

## Vercel dışında çalıştırma (bilgisayar / VPS / Android Termux)
```bash
pip install -r requirements.txt
cp .env.example .env     # değerleri doldurun
python run.py            # panel: http://localhost:8080 (zamanlayıcı gerekmez)
python run.py --test "BREAKING: SEC approves spot Solana ETF"
```
Ubuntu sunucuda kalıcı servis olarak kurmak için: `bash deploy/install.sh`. Redis tanımlı değilse
veriler `store.json` dosyasında tutulur.

## Bilmeniz gerekenler
- **Hız:** Dakikada bir kontrol, saniyeler içinde tepki veren botların gerisinde kalır.
- **Yanıltıcı haberler:** Haber hesapları bazen yanlış "BREAKING" paylaşır. Düşük kaldıraç ve kısa stop-loss bu yüzden önemli.
- **"Sell the news":** Olumlu haber de fiyatı düşürebilir.
- Önce haftalarca `dry_run`, sonra `testnet` modunda deneyin. Gerçek parayı en son, küçük tutarla kullanın.
