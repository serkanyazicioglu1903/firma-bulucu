# AS Control Tower — v1 pilot teslim raporu

Tarih: 10 Ekim 2026. Durum: yerel SQLite üzerinde test edilmiş bütünleşik pilot; canlı kullanıma onay verilmiş sürüm değildir.

## İncelenen PR'lar

| PR | İncelenen commit | Sonuç |
|---|---|---|
| #25 | 47fbda45e19276aeb5983894f00dd0c27ec8d14f | Staging HOLD/ödeme ve güvenli temizleme kontrolleri; korundu. |
| #26 | 9d05edf8bea01dc677f7121bdbe9d261a68f5717 | Otomatik demo oluşturmayı kapatma ve boş ekran korumaları; korundu. |
| #27 | 414c5ca08213cf3ce81559510f5b650f232754a0 | Birleşik geliştirme temeli olarak kullanıldı. |

Hiçbiri birleştirilmedi. Main ve canlı veritabanlarına yazılmadı. Gerçek yedek dosyaları açılmadı. Testler geçici ve sentetik verilerle çalıştırıldı.

## Çalışan akış

1. Üretici Bulucu sonuçlarını mevcut CRM aktarımıyla üretici/tedarikçi adayına dönüştürme; katalog veya CRM tedarikçisini bütünleşik sipariş formunda seçme.
2. Müşteri ve katalog ürünü için maliyet/kârlılık hesabı; Kabul durumunda teklif kaydı.
3. Yönetici Paneli içindeki **Tekliften tahsilata** merkezinden satın alma siparişi ve planlanan tedarikçi borcunu aynı transaction içinde oluşturma.
4. Satın Alma & Stok ekranlarından ithalat sevkiyatı, varış deposu, lot ve stok girişi. Kısmi teslimat ve kalan PO takibi mevcut akışta korunur.
5. Kalite HOLD, son kullanma tarihi, bloke regülasyon, rezerve miktar ve kalan sipariş miktarı kontrol edilerek müşteri sevki.
6. Sevkle birlikte atomik stok düşümü ve müşteri alacağı; kısmi sevk desteği.
7. Finans ekranlarından borç ödeme ve tahsilat; işlem referansıyla tekrar kaydı engelleme, para birimi kontrolü, kalan tutar sınırı.
8. İşlem merkezinde sipariş, sevk, kalan miktar, tedarikçi borcu ve baz para biriminde tahmini katkı/kâr görünümü. Mevcut yönetici, stok ve nakit raporları aynı kayıtları kullanır.

Yeni bütünleşik işlemler ADMIN rolündedir. Mevcut diğer rol portalları korunmuştur. Planlanan borç tedarikçi faturası değildir; sevkte açılan alacak resmî e-fatura değildir. Kâr, teklif maliyeti üzerinden hesaplanan tahmindir.

## Düzeltmeler

- Aynı sevkiyatın eşzamanlı iki kere stoğa alınmasını engelleyen SQLite yazma kilidi.
- Eşzamanlı ödeme/tahsilatta aşırı kapamayı ve aynı referansın tekrarını engelleme.
- İptal edilmiş finans kaydına ödeme ve NaN/sonsuz tutarları reddetme.
- Stok/finans servis girişlerinde rol kontrolü.
- Siparişe bağlanan teklifi değişiklik/silmeden koruma; revizyon yeni teklif olmalıdır.
- Ürün önerisi bulunmayan ekranın SQL `not` alan adı hatası.
- `app.py` import edilirken arayüzü başlatma sorunu: ana giriş fonksiyonuna alındı.
- Testlerin normal uygulama veritabanını silmesi önlendi; pytest için her teste ayrı geçici veritabanı ve test giriş yapılandırması.
- `AS_CONTROL_TOWER_DB` ile ayrılmış önizleme; ortam değişkenlerinden giriş yapılandırması.
- Doğrulanan Streamlit sürümü sabitlendi; birleşik regresyon seti CI'a eklendi.

## Test kanıtı

Python 3.12 / Streamlit 1.65.0 üzerinde:

| Kontrol | Sonuç |
|---|---|
| `python -m pytest -q` | 116 geçti; 27 alt senaryo geçti; 0 hata |
| Python compile kontrolü | Geçti |
| `python preflight_check.py --demo` | PASS |
| Yerel Streamlit `/_stcore/health` | HTTP yanıtı `ok` |
| `git diff --check` | Geçti |
| Chromium masaüstü 1440×900 / telefon 390×844 | GitHub CI: geçti; giriş, modül geçişleri, yatay taşma kontrolü |
| Gerçek iPhone/Safari ve MacBook testi | Yapılamadı |
| PostgreSQL gerçek sunucu entegrasyonu | Yapılmadı; staging testleri çevrimdışı taklit bağlantılarla |

Uçtan uca test: 1.000 kg, alış 2 EUR/kg, satış 3 EUR/kg, teklif toplam maliyeti 2,50 EUR/kg. Önce HOLD sebebiyle sevk reddedilir; serbest bırakıldıktan sonra 400 + 600 kg sevk edilir. Stok 0, alacak 3.000 EUR, borç 2.000 EUR, ödeme ve tahsilat sonrası banka 10.000 → 11.000 EUR; tahmini katkı 500 EUR. Ayrıca rollback, aynı referansı tekrar gönderme, fazla sevk, rezerve stok, SKT, regülasyon blokesi, yetki ve eşzamanlı işlemler test edildi. Streamlit ekranından 100 kg sevk testi stok 900 kg/alacak 300 EUR sonucunu doğruladı.

Bir mevcut uyarı: parola hash testindeki `datetime.utcnow()` kullanımı için deprecation uyarısı. Test başarısını etkilemiyor.

Yerel Chromium indirmesi geçersiz/eksik arşiv döndürdüğü için tarayıcı kabul testi GitHub CI ortamına taşındı ve geçti. 1440×900 masaüstü ve 390×844 telefon boyutunda giriş, modül geçişleri, sayfa yatay taşması ve uygulama istisnaları kontrol edildi. Ekran görüntüleri CI artifact olarak kaydedildi. Bu test fiziksel iPhone/Safari veya MacBook testinin yerine geçmez. Sonraki GitHub CI çalışmasında ana uygulama kontrolleri, birleşik test seti ve staging güvenlik testleri de geçti.

## MacBook ve aynı Wi-Fi'deki telefon için önizleme

Bu dalın koduyla proje klasöründe:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python preview.py --demo --lan
```

Başlatıcı en az 12 karakterli geçici şifre ister. Kullanıcı adı `serkan`. MacBook'ta `http://localhost:8501`, telefonda aynı güvenilir Wi-Fi üzerinden MacBook'un yerel IP adresi ve `:8501` kullanılır. Bu bir internet dağıtımı değildir. `--lan` verilmezse yalnızca MacBook'tan açılır. `--demo` verilmezse boş çalışma alanı açılır.

Önizleme ayrı geçici veritabanı kullanır; normal şirket veritabanını açmaz. Kapatıldığında önizleme kayıtları silinir. Gerçek bilgi girilmemelidir. Demo örnekleri iş gerçeği veya güncel fiyat olarak değerlendirilmemelidir.

## Açık işler ve ilk sürümün sınırları

- Sürekli ve çok kullanıcılı canlı çalışma için PostgreSQL uygulama veri katmanı tamamlanmalı. Yeni `workflow_orders` ve `workflow_deliveries` tabloları ile teklif kilitleri PostgreSQL staging migration/adapter kapsamına henüz eklenmedi. Mevcut staging pilotu tam üretim veri katmanı değildir.
- iPhone Safari, MacBook Safari/Chrome gerçek cihaz kabul testi; dar ekran form ve tablo kontrolleri.
- Gerçekleşen navlun, gümrük, kur farkı ve finansman masraflarının sipariş bazında mutabakatı. Mevcut kâr teklif varsayımlarını kullanır.
- İlk bütünleşik akış tek ürünlü teklif ve ona ait PO lotlarından sevki destekler. Çok kalemli sipariş, farklı PO'lardan tahsis, iade/iptal/ters kayıt iş akışları ek geliştirme gerektirir.
- Üretici araması bir aday taramasıdır; resmî üretici teyidi, otomatik banka/muhasebe/e-fatura ve Outlook entegrasyonu bu sürümde tamamlanmış değildir.
- Gümrük/mevzuat kayıtları kullanıcı takibidir; otomatik mevzuat uygunluk onayı değildir.
- Canlı geçişten önce yedekleme/geri dönüş, yetki kabulü ve gerçek PostgreSQL transaction testi tamamlanmalı.

PR birleştirme, canlı dağıtım veya canlı veri aktarımı için Serkan Bey'in ayrıca onayı gerekir.

## Son GitHub doğrulaması

Test edilen kod commit’i: `d56b28969ae72ac2f4b4a67dceabe23c166bfcd8`.

- [Ana uygulama + tarayıcı kabul testi: başarılı](https://github.com/serkanyazicioglu1903/firma-bulucu/actions/runs/38074788079)
- [Staging güvenliği: başarılı](https://github.com/serkanyazicioglu1903/firma-bulucu/actions/runs/38074788074)
- Tarayıcı ekran görüntüleri ilk bağlantıdaki `browser-acceptance` artifact içinde.
- İlk CI denemesindeki pytest import yolu sorunu düzeltildi; pandas test edilen 2.2.3 sürümüne sabitlendi.
- Bu sonuçların ardından yapılan rapor güncellemesi uygulama kodunu değiştirmez.
