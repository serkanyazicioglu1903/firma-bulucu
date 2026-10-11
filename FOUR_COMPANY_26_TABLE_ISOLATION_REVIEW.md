# AS Control Tower — Dört şirket, 26 tablo: veri ayrımı hazırlığı

Bu geliştirme **canlı şirkete geçiş veya veri tabanı migrasyonu değildir**. PR yalnızca taslak şirket/tablolar arası sahiplik mimarisinin **çevrimdışı kontrolünü** sağlar.

## Dört şirket

`AS_ILERI_GIDA`, `PLANET_INGREDIENTS`, `AS_FOOD_GLOBAL` ve `AS_ILERI_HOLDING` uygulamadaki etiketlerdir. Bu etiketler ticaret sicilindeki tam unvan, şirket ID'si, vergi numarası veya bir kullanıcının yetkisi sayılmaz. Her biri için bağımsız resmi evrak kontrolü ve kanıt referansı gerekir. Holding olmanın diğer şirketlere otomatik erişim sağlamaması gerekir.

## Karar verilmesi gereken 26 tablo

| Grup | Tablo | Desteklenen *taslak* karar |
|---|---|---|
| 8 kritik operasyon/finans | purchase_orders, shipments, inventory_lots, quality_cases, payables, receivables, finance_transactions, cash_accounts | Her kayda doğrudan şirket sahibi |
| Müşteri/depo/görev | customers, warehouses, tasks | Doğrudan sahibi veya doğrulanacak üst kayıttan şirket mirası |
| 12 bağlı süreç tablosu | opportunities, contacts, activities, opportunity_stage_history, customer_product_status, quotes, inventory_policy, cash_events, quality_actions, quality_recoveries, compliance_documents, regulatory_items | Doğrudan sahibi veya açık ve döngüsüz üst kayıt sahipliği |
| Ürün ana kayıtları | product_catalog | Doğrudan sahiplik veya ayrıca incelenecek ortak-katalog adayı |
| Dahili tablo | audit_log, system_settings | Doğrudan sahiplik veya uygulama iş ekranlarından izole dahili erişim |

Yukarıdaki sınıflandırma gerçek veri sahipliği anlamına gelmez. Her tablo için bağımsız kanıtlı karar gerekir. Ortak ürün katalogları tedarikçi fiyatı gibi ticari sırlar içerebilir; `shared_candidate` **erişim yetkisi vermez**. Fiziki PostgreSQL yabancı anahtarlarının, şirket eşleşmelerinin ve tüm SQL/CSV/rapor yollarının ayrıca doğrulanması gerekir.

## Test edilen çevrimdışı değerlendirme

`scripts/company_isolation_blueprint_review.py` içindeki `review_isolation_blueprint` fonksiyonu, dört şirketin hukuki evrak referanslarını ve 26 tablonun sahiplik stratejisini içeren bağımsız bir **taslak nesneyi** değerlendirir. Eksik, mükerrer, izin verilmeyen ortak tablo, eksik üst kayıt, döngüsel sahiplik ve geçersiz FK tanımları reddedilir. Doğrulamada şirket unvanları, kayıt kimlikleri ve kanıt belgeleri rapora geri verilmez.

Geçerli bir planın çıktısı **yalnızca `review_required`** olur. `production_approved`, `legal_register_verified`, `row_level_access_verified` ve `database_constraints_verified` bayrakları daima **false** kalır.

## Gerçek kayıtlı siparişe geçişin kalan blokajları

1. Dört tüzel kişiliğin hukuki kayıtları ve hangi eski kayıtların hangi şirkete ait olduğu bağımsız teyit edilmeli. Hiçbir şirket sahibi otomatik tahmin edilmeyecek.
2. Yetki manifesti, tüm kullanıcı rolleri ve şirket bazlı okuma/yazma erişimleri gözden geçirilmeli; sadece rol ismi veya arayüz etiketi yetmez.
3. Canlı veritabanının tutarlı ve şifreli yedeği alınıp ayrı ortamda **geri yükleme testi** başarıyla bitirilmeli.
4. Önce geçici PostgreSQL üzerinde 26 tabloyu kapsayan DDL, referans bütünlüğü, şirketler arası erişim olumsuz testleri, finans ve stok akışı doğrulanmalı.
5. Tüm eski filtrelenmemiş Streamlit ekranları, API/CSV/raporlar ve alternatif SQL yolları ya kapatılmalı ya da sunucu tarafında kanıtlı şirket iznine bağlanmalı.
6. Kullanıcının ayrıca vereceği **canlı migrasyon ve canlı yazma izni** olmadan Supabase şemasına, gerçek kayıtlara, rol ve RLS ayarlarına dokunulmamalı.

**Bu PR hiçbir kalıcı satın alma, stok, finans veya şirket ayrımı kaydı oluşturmaz.** Mevcut tekliften oluşturulan onaysız CSV taslağı ayrı çalışmaya devam eder.
