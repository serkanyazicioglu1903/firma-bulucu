# PostgreSQL uygulama arka ucu

Kod, varsayılan SQLite yanında **açıkça seçilen** PostgreSQL bağlantısını destekler.
Bu dosya bir dağıtım talimatını otomatik yürütmez. Canlı geçiş, veri aktarımı ve
PR birleştirme için Serkan'ın ayrıca onayı gerekir.

## Ayarlar

Uygulama sürecine ortam değişkenleri olarak sağlanır; bağlantı parolası repoya yazılmaz:

- `AS_CONTROL_TOWER_BACKEND=postgres`
- `AS_CONTROL_TOWER_POSTGRES_URL`: uygulamaya ayrılmış PostgreSQL DSN
- `AS_CONTROL_TOWER_POSTGRES_SCHEMA`: ayrı şema; varsayılan `ct_staging`

Genel `DATABASE_URL` iş veritabanı seçiminde kullanılmaz. Eksik veya hatalı ayarda
SQLite'a sessiz dönüş yapılmaz. Ana uygulama, raporlar, rol portalları, denetim
kayıtları ve CSV dışa aktarımı aynı bağlantı katmanını kullanır.

Uygulama açılışı yalnız şemayı kontrol eder; PostgreSQL'de otomatik DDL/migrasyon
uygulamaz. Yeni boş şema için `scripts/build_pg_schema.py`, eski test şemasına
ilave akış tabloları için `scripts/build_workflow_migration.py` çevrimdışı SQL
üretir. SQL dosyaları incelenmeden ve ilgili ortam için onay alınmadan uygulanmaz.
Mevcut SQLite kayıtlarını bu kod kendiliğinden taşımaz.

## İşlem ve yedek davranışı

- Değerler parametreyle bağlanır. SQL ayrıştırıcısı tarih hesaplarını, parametreleri
  ve tek satırdaki MAX/MIN hesaplarını PostgreSQL sözdizimine çevirir.
- Bileşik finans/stok akışları ve normal yazmalar aynı işlem kilidini kullanır.
  Hata halinde işlem geri alınır; PostgreSQL kimlikleri RETURNING ile alınır.
- Açık bağlantılar işlem sonunda kapatılır. Rapor bağlantıları ayrı işlemlerdir.
- PostgreSQL CSV dışa aktarımı tek, tutarlı salt okunur anlık görüntü kullanır.
  CSV dosyaları tam geri yükleme yedeği değildir.
- PostgreSQL seçiliyken SQLite dosya yedeği ve bağımsız eski staging pilot ekranları
  gösterilmez. Sunucu yedeği/PITR ve geri yükleme tatbikatı ayrıca hazırlanmalıdır.
- `python preview.py --demo --lan` daima geçici SQLite kullanır; ortamda PostgreSQL
  ayarı bulunsa bile ona bağlanmaz. Demo preflight da aynı şekilde izoledir.

## Güvenli kabul testleri

GitHub Actions ayrı ve geçici PostgreSQL 16 servisinde `ct_test` veritabanını
kullanır. Testler **yalnız açık loopback adresli ct_test** bağlantısını kabul eder.
`tests/test_postgres_workflow_live.py` ve
`python scripts/browser_acceptance.py --postgres-test` bu test şemasını sıfırlar;
bu komutlara canlı bağlantı verilmez. Parola test servisine özeldir.

Kabul kapsamı: sipariş/stok/kalite/sevk/tahsilat, maliyet/iade/ters kayıt,
eşzamanlılık ve rollback; altı rolün ekranları, boş uygulama, CSV dışa aktarımı;
Chromium ve WebKit masaüstü/telefon görünümü. Fiziksel cihaz ve canlı ortam
kabulü bu otomatik kontrollerin kapsamı dışındadır.
