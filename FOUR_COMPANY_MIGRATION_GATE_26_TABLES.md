# AS Control Tower — 26 tablo göç güvenlik kapısı (PR adayı)

**Canlı veritabanını değiştirmeyen kontrol.** Bu geliştirme dört şirketin
veri sahipliğini kurmaz, kullanıcı yetkisi vermez ve gerçek iş kaydı oluşturmaz.

## Sorun ve gerçek PostgreSQL görünümü

11 Ekim 2026 tarihinde `AS-CONTROL-TOWER` Supabase bağlantısındaki
`ct_app` şemasına salt okunur SQL ile bakıldı:

- 26 uygulama tablosu mevcut.
- 0/26 tabloda `legal_entity_id` var.
- 0/26 tabloda RLS etkin; 0 uygulama tablosunda RLS politikası görüldü.
- Henüz dört şirketin veri ayrımı **gerçekte uygulanmış değil**.

Bu sonuçlar şirket bazlı yetki denetimlerinin yapıldığı veya PostgreSQL
yedek/restore işleminin başarılı olduğu anlamına gelmez.

## Değişiklik ve gerekçe

Mevcut Streamlit Control Tower eski şirket filtresiz ekranlara girilmeden
önce `scripts/postgres_company_migration_guard.py` kontrolünü çalıştırır.
Önceki güvenlik kapısı yalnızca 8 kritik operasyon tablosundaki
`legal_entity_id` kolonlarını ve 5 şirket tablo işaretini izliyordu.

Bir CRM, ürün, depo veya destek tablosuna sahiplik alanı eklenirse, ya da
26 tablodan birinde RLS/politika veya `anon`, `authenticated`,
`service_role` API rolüne etkili şema+tablo erişimi verilirse eski
şirket filtresiz ekranın **açık kalmasını** önlemek için kontrol
artık 26 tablonun tamamını okuyor.

- **Tam temiz legacy şema:** Önceki davranış değişmez.
- **Şirket sahipliği/RLS/politika/API grant sinyali:** Eski şirket
  filtresiz PostgreSQL iş ekranları kapatılır.
- **Eksik, şüpheli veya erişilemeyen metadata:** Ekran güvenlik
  gereği kapalı kalır; SQL hata veya kullanıcı verisi dönmez.
- **İmzalı şirket bazlı salt okunur inceleme:** Mevcut ayrı yol
  korunur; bu PR onun yetkilerini değiştirmez.

Kontrol yalnızca katalog sorguları yapar, iş satırı veya kullanıcı bilgisi
okumaz. RLS kapalı diye veritabanı otomatik olarak kamuya açık
varsayılmaz. API rolüne etkin tablo izni tespit edilmesi de doğrudan
internet erişimini kanıtlamaz; sadece ayrı güvenlik incelemesi tetikler.

## Canlı geçişin kalan zorunlu koşulları

Şirket ticari sicil/vergi bilgileri ve kayıt sahipliği, 26 tablo için
gerçek FK/uygulama politikaları, rol-bazlı kullanıcı izinleri,
imzalı oturum doğrulama, RLS veya eşdeğer sunucu satır güvenliği,
gerçek yedek **geri yükleme tatbikatı**, mutabakat ve izole PostgreSQL
üzerinde gerçek iş akışı testleri tamamlanmadan canlı şirket kaydı
veya veritabanı migrasyonu yapılmayacak.

**Bu PR yalnızca kod ve çevrimdışı testleri içerir. PR merge/canlı
dağıtım için ayrı kullanıcı onayı gerekir.**
