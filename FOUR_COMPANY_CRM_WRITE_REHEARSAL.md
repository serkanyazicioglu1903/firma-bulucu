# AS Control Tower — Şirket Bazlı Müşteri ve İrtibat Kaydı Denemesi

## Gerçek işe yönelik geliştirme

Bu PR, sadece kullanıcı tarafından onaylanmış geçişten **sonra** etkinleştirilebilecek müşteri ve irtibat kayıt açma yolunu **geçici PostgreSQL** için hazırlar. Eski/demo müşteri verisi kullanılmaz, gerçek müşteri sahipliği otomatik tahmin edilmez ve canlı Supabase'e hiçbir yazı yapılmaz.

İki işlem tasarlandı:

- `create_customer`: Müşteri adı, ülke, sektör, durum, sorumlu ve para birimiyle **yetkili şirkete ait** müşteri kaydı.
- `create_contact`: Yalnızca **aynı şirkete** ait mevcut bir müşterinin iletişim kişisi.

Kayıt oluşturmadan önce sunucu tarafından doğrulanmış bir kullanıcı kimliği sağlanmalı, hem şirket okuma hem de yazma izni PostgreSQL'de doğrulanmalı; müşteri ve irtibat tablosunda `legal_entity_id NOT NULL` bulunmalı ve `contacts(customer_id,legal_entity_id)` → `customers(id,legal_entity_id)` doğrulanmış bileşik FK'si olmalı. İşlem ve `company_operation_audit` kaydı **aynı transaction** içinde yapılmalı; hata halinde ikisi de geri alınmalı. Bu PR'da yalnızca **ADMIN** rol etiketli çağrı kabul ediliyor; **rolün gerçek kullanıcının oturumundan doğrulanması canlı sürüm için ayrıca zorunlu**. SALES veya holding etiketi üzerinden otomatik hak yok.

## Gerçek ortamda devre dışı

`scripts/postgres_scoped_company_crm_write_rehearsal.py` **Streamlit ekranına bağlanmadı**. Dış çağrı `run_company_crm_write_rehearsal()` yalnızca belirli `localhost:5432`, CI `ct_ci` kullanıcısı, `ct_ci_control_tower` veritabanı ve açık CI ayarlarına izin verir. Supabase hostu, normal PostgreSQL veya geçersiz ayarlarda işlem **kategorik olarak reddedilir**. Mevcut satın alma yazma provasının güvenli hedef/izin denetimi tekrar kullanılır.

`run_company_crm_write_on_cursor` alt fonksiyonu yalnızca **izole CI transaction kuran testler** tarafından kullanılmalıdır; üretim cursor'ı verilmesi yasaktır. Bu bir production API veya gerçek CRM kaydı oluşturma onayı değildir. Kullanıcının şirket seçimi yetki vermez.

## Testler

- Her iki kayıt işleminde gerçek şirket sahipliği ve `company_operation_audit` kontrol edilir.
- Başka şirketin müşteri ID'si irtibat olarak kullanılamaz.
- Okuma izni olsa bile yazma izni olmayan kullanıcı kayıt açamaz.
- Yazma yetkisi iptal edildikten sonra yeni kayıt reddedilir.
- SALES, VIEWER ve FINANCE rolleri bu ilk CRM kayıt yolu için yetkisizdir.
- Hatalı ve boş girdiler SQL yazmadan reddedilir.
- Geçici GitHub PostgreSQL'de sahte iki şirkete ait müşteriler/kişiler oluşturulur; izinsiz şirket/kişi erişimi sınanır. **Transaction rollback** sonunda şema, rol/izin ve sahte kayıtlar kalıcı olmaz.

## Henüz eksik olan canlı geçiş koşulları

Dört şirketin ticaret sicil/yasal sahipliği, 26 tablonun satır bazlı ayrımı, tüm eski uygulama yollarının şirket filtrelenmesi, en az yetkili PostgreSQL uygulama rolü ve RLS/benzeri güvenlik, imzalı gerçek kullanıcı rolü doğrulaması, bağımsız canlı yedek+geri yükleme, muhasebe/stok mutabakatı ve kullanıcıdan ayrıca **canlı migrasyon/yazma onayı** alınması. Bu PR herhangi bir canlı iş kaydını değiştirmez, gerçek CRM kullanıcı arayüzünü açmaz ve otomatik canlı dağıtım başlatmaz.

**PR'ın main dalına birleştirilmesi ayrıca onay gerektirir.**
