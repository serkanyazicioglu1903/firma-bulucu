# AS Control Tower — Gerçek şirket bazlı müşteri/irtibat okuma

## Özellik
İmzalı ve ayrıca etkinleştirilmiş `REVIEW_ONLY_WITH_SIGNED_SESSION` modunda iki CRM okuma bölümü hazırlandı: **Müşteriler** ve **İrtibat Kişileri**.

Kullanıcı kimliği, sunucunun parola doğrulamasından sonra imzaladığı oturumdan alınır. Şirket etiketi veya ADMIN rolü tek başına erişim vermez. PostgreSQL üzerinde ilgili şirket için geçerli `company_read_grants` izni kontrol edilir ve sonuçlar şirket sahibi üzerinden sınırlandırılır.

### Verinin görüntülenmesi için *tümü* gerekli
1. Sekiz kritik operasyon tablosunda daha önceden onaylanmış `legal_entity_id NOT NULL` sahiplik yapısı ve ilgili `legal_entities`/`company_read_grants` tabloları.
2. `customers` ve `contacts` tablolarında `legal_entity_id NOT NULL`.
3. `contacts(customer_id,legal_entity_id)` → `customers(id,legal_entity_id)` bağlantısını doğrulayan **gerçek, VALIDATED PostgreSQL bileşik FK**.
4. Hem üst müşteri hem alt irtibat kaydının şirket sahipliğinin eşleşmesi.
5. Sunucuda imzalı, güncel kullanıcı oturumu ve şirket için açık **veritabanı okuma izni**.

Eksik kural, yetkisiz kullanıcı, iptal edilmiş izin, hatalı bağlantı, geçersiz sorgu veya veritabanı arızasında **hiçbir CRM kaydı döndürülmez**. Etkin olmayan şirketin kayıtları gösterilmez. Bir istekte en fazla 100 satır ve yalnızca önceden belirlenmiş sütunlar alınır.

### Şu an ne *olmaz*?
Canlı Supabase `ct_app` içindeki bu sahiplik sütunları ve izin kayıtları hazır değildir. Dolayısıyla özellik mevcut canlı uygulamada müşteri kayıtlarını otomatik açmaz. Gerçek CRM yazma, müşteri oluşturma, irtibat kaydetme, içe aktarma, stok/finans kaydı ve konsolidasyon **bu PR’da yok**. Şirket etiketleri hukuken doğrulanmış kayıt değildir.

## Testler
- Çevrimdışı güvenlik testleri: sahte kimlik, yanlış şirket, geçersiz bölüm, şirket verisi yokluğu, eksik bileşik FK, yetkisiz grant.
- Streamlit yönlendirme testleri: imzasız oturumda veri sorgusu yok, tuşa basılmadan sorgu yok, yetkisiz şirkette satır yok.
- GitHub Actions disposable PostgreSQL testi: şirket A/B için sahte müşteri ve irtibat kayıtları; yalnızca izin verilen A kayıtları gösterilir; B ve izinsiz kullanıcı engellenir; FK başka şirkete geçişi reddeder. **Tüm şema/veri/izin değişiklikleri geçici test işlemi sonunda geri alınır.**

## Prod geçişi
Gerçek ticari sicil/kayıt sahipliği, tüm 26 tabloda geçiş mimarisi, bağımsız şirket/kullanıcı izinleri, eksiksiz RLS veya eşdeğer erişim katmanı, geri yükleme tatbikatı ve mevcut legacy ekranların izolasyonu ayrıca onaylanmadan canlı migrasyon yapılmayacak.

**Bu PR canlı Supabase’e bağlanmaz, veri/şema/rol/izin değiştirmez. PR birleştirme ve canlı dağıtım için ayrıca onay gereklidir.**
