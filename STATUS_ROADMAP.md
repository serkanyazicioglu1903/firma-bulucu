# AS CONTROL TOWER — DURUM / ROADMAP

Güncelleme: 2026-10-07

## CANLIDA OLANLAR (main)

1. Firma Satın Alma / Halefiyet
2. Üretici / Hammadde Bulucu
3. AS Control Tower çekirdeği
4. CRM / Müşteri 360
5. Satış Pipeline ve takip
6. Ürün × Müşteri cross-sell motoru
7. Teklif + gerçek maliyet + finansman + kârlılık
8. Satın Alma / PO / Sevkiyat / Stok / Yeniden Sipariş
9. Finans / Tahsilat / Borç / 30-60-90 nakit
10. Kalite / Claim / HOLD-RELEASE / Sertifika / Regülasyon
11. AI Yönetici / CEO Sabah Özeti / Risk Merkezi

## HAZIR AMA CANLIYA ALINMAYANLAR

### PR #2 — Outlook + Takvim + Toplantı Merkezi
Kod ve test hazır.
Kullanıcı Microsoft Entra yetkisi gerekiyor.

Gerekli:
- MICROSOFT_CLIENT_ID
- MICROSOFT_TENANT_ID
- CONTROL_TOWER_PASSWORD
- opsiyonel MICROSOFT_ALLOWED_EMAIL

### PR #4 — Production Hardening + Yönetim Raporları
Kod ve test hazır.

İçerik:
- Kullanıcı girişi
- Roller
- Rol bazlı DB yazma yetkisi
- Admin dışındaki kullanıcılar için ayrı, kısıtlı rol portalları
- Audit log
- Sistem sağlığı
- Veritabanı backup
- CSV ZIP export
- CSV toplu import
- Yönetim performans raporları
- SQLite -> PostgreSQL/Supabase migration helper
- Otomatik core tests

Canlıya alınmadan önce Streamlit Secrets içine en az:
CONTROL_TOWER_PASSWORD = "..."

eklenmeli.

## ROLLER

ADMIN
- Tam yetki

SALES
- CRM
- cross-sell
- teklifler
- pipeline
- takip
- görev

PURCHASING
- ürün
- satın alma
- PO
- sevkiyat
- stok
- görev

FINANCE
- teklif maliyeti
- finans
- tahsilat
- borç
- rapor

QUALITY
- kalite
- claim
- sertifika
- regülasyon
- görev

VIEWER
- yönetici raporları
- AI/CEO ekranı

## TEST DURUMU

PR #4:
- Dependencies: SUCCESS
- Python compile: SUCCESS
- Core business tests: SUCCESS
- Authenticated ADMIN Streamlit startup: SUCCESS
- Core business tests: SUCCESS
- Role write-permission tests: SUCCESS

## SABAH YAPILACAK EN KISA İŞ

1. Streamlit Secrets içine güçlü CONTROL_TOWER_PASSWORD ekle.
2. PR #4 main'e merge et.
3. Canlı uygulamayı aç ve ADMIN girişini test et.
4. İstenirse Microsoft Entra ayarlarını yap.
5. PR #2 Outlook entegrasyonunu main'e al.
6. Gerçek şirket verisi girmeden önce Sistem > Yedekleme ekranını test et.
7. Bulut veritabanı için Supabase/PostgreSQL bağlantı bilgisini hazırla; SQLite cutover bundan sonra yapılır.

## ÖNEMLİ

- Outlook kullanıcının Microsoft hesabında bir defalık onay olmadan tamamlanamaz.
- Kalıcı PostgreSQL/Supabase geçişi bağlantı bilgisi olmadan canlı yapılamaz.
- Bu iki dış bağımlılık dışında kod tarafındaki production hazırlıkları tamamlanmıştır.
