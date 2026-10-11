# AS Control Tower — Dört şirket için fiziksel FK kontrolü (PR adayı)

## Hedef

Önceki 26 tablo plan denetimi (`company_isolation_blueprint_review.py`)
`parent_scoped` bağlantılarının yalnızca **isimlerini ve mantıksal zincirini**
kontrol ediyordu; gerçekten mevcut ve zorunlu bir PostgreSQL FK'sini
kanıtlamıyordu.

Yeni `scripts/company_fk_catalog_review.py` şunları salt okunur
`pg_catalog` üzerinden doğrular:

- `ct_app` şemasında beklenen **26 tablo** tam ve eksiksiz;
- Her `parent_scoped` bağlantısındaki alt tablo, FK sütunu, üst tablo
  ve üst `id` sütunu fiziksel olarak doğru eşleşiyor;
- FK PostgreSQL tarafından **validated**;
- Alt tablonun FK sütunu `NOT NULL`;
- Eksik, nullable, `NOT VALID`, sahte veya mükerrer FK bilgisi reddediliyor;
- Tüm sonuçlar yalnızca özet durum ve makinece tanınan hata kodu döndürüyor.

**Önemli sınır:** Gerçek FK, yalnızca bağlantının fiziksel varlığını
doğrular; alt kaydın hukuki şirketiyle üst kaydın sahibi arasında
uygunluk veya şirket bazlı erişim yetkisi vermez. Gerçek şirket
`legal_entity_id` ataması, eski kayıt eşlemesi, RLS/sunucu
erişim kontrolü, rolleri ve mali mutabakat ayrı onaylı aşamalardır.
Başarı `review_required` ve `production_approved=False` kalır.

## Gerçek PostgreSQL entegrasyon testi

CI, sadece silinen/geçici PostgreSQL hizmetinde gerçek katalog üzerinden
iki zorunlu ilişkiyi kontrol eder: `contacts.customer_id` →
`customers.id` ve `activities.customer_id` → `customers.id`.
Ayrıca `opportunities.customer_id` bağlantısının mevcut şemada
nullable olduğunu **tespit edip miras sahibi olamayacağını** sınar.

Yalnızca doğrulama sorguları çalışır, DDL/migrasyon, kimlik
ataması ve gerçek Supabase üzerinde kayıt değişikliği yapılmaz.

## Çıkış koşulu

Bu PR ana sürüme eklenmiş olsa bile dört şirketin verilerini
ayırmaz ve canlı sipariş açmaz. Ticaret sicil bilgileri, 26 tablo
için onaylı plan, kullanıcı/şirket izinleri, test edilmiş yedek
geri yükleme ve pozitif-negatif gerçek veri güvenliği senaryoları
tamamlanmadan canlı kayıt geçişine başlanmayacak.
