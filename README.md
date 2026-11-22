# Kanat-Bek Takip — Kurulum

Kanat oyuncusuyla oynayan dizilişlerde (4-4-2, 4-2-3-1, 4-3-3, 4-1-4-1, 4-4-1-1)
kanada bek özellikli bir oyuncu yerleştirilmişse telefonuna bildirim atar.
Kadrolar SofaScore'dan, oyuncu mevkileri önce Transfermarkt'tan
(bulunamazsa SofaScore'dan) alınır. GitHub Actions'ta 15 dakikada bir çalışır.

## 1. Bildirim: ntfy (önerilen)
1. Telefonuna **ntfy** uygulamasını kur (App Store / Google Play, ücretsiz).
2. **+** → **Subscribe to topic** → tahmin edilmesi zor bir kanal adı yaz,
   ör. `kanatbek-ahmet-7391`. (Kanal adını bilen herkes mesajları görebilir,
   o yüzden basit bir ad seçme.)
3. Bu adı not al; 3. adımda `NTFY_TOPIC` olarak gireceksin.

(İstersen Telegram da kullanabilirsin: @BotFather'dan bot açıp
`TELEGRAM_TOKEN` ve `TELEGRAM_CHAT_ID` secret'larını eklemen yeterli.
İkisi birlikte de çalışır.)

## 2. GitHub deposu
1. github.com'da **New repository** → isim ver → **Public** seç.
   (Private depoda aylık ücretsiz süre 15 dakikalık çalışmaya yetmez; public'te sınır yok.
   Kanal adı ve token'lar Secrets'ta durduğu için kimse göremez.)
2. **Add file → Upload files** ile `kanat_bek_takip.py`, `requirements.txt`, `README.md` dosyalarını yükle.
3. **Add file → Create new file**, dosya adına `.github/workflows/takip.yml` yaz,
   `takip.yml` içeriğini yapıştır, kaydet.

## 3. Gizli bilgiler
**Settings → Secrets and variables → Actions → New repository secret**:
- `NTFY_TOPIC` = ntfy kanal adın

## 4. İlk çalıştırma
**Actions** sekmesi → **Kanat-Bek Takip** → **Run workflow**. Kayıtlarda:
- "Zaman aralığındaki maç: …" → çalışıyor.
- "SofaScore isteği engelledi" → GitHub sunucuları SofaScore'a giremiyor.
- "Transfermarkt engelledi" → mevkiler SofaScore'dan alınıyor; sistem yine çalışır.

## Ayarlar (`kanat_bek_takip.py` başındaki bölüm)
- `KANATLI_DIZILISLER`: yeni diziliş eklemek için.
- `SADECE_ANA_MEVKI`: `False` yaparsan ikinci mevkisi bek olanlar da bildirilir.
- `TRANSFERMARKT_KULLAN`: `False` yaparsan sadece SofaScore kullanılır.
- `ILK_OYUNCU_SAG`: bildirimde sağ/sol ters çıkıyorsa `False` yap.

## Bilgisayarda test
```
pip install -r requirements.txt
python kanat_bek_takip.py --mac <SofaScore maç ID>   # ilk 11'i mevkileriyle yazar
NTFY_TOPIC=kanal-adin python kanat_bek_takip.py --test-bildirim
```
Maç ID'si, SofaScore maç adresinin sonundaki `#id:` sonrası sayıdır.
