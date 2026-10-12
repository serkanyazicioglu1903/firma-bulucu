# AS Control Tower — Dört Şirket / 23 Tablo RLS Olumsuz Erişim Testi

## Amaç
Şirketler arası kayıt sızıntısı oluşmaması için **23 özel işletme tablosunda** PostgreSQL Row Level Security (RLS) kuralını ve en az yetkili veritabanı rolleriyle olumsuz erişim testini doğrulamak.

**ÖNEMLİ: Bu bir izolasyonlu GitHub PostgreSQL provasıdır. Canlı üretim için hazırlanmış ve etkinleştirilecek güvenlik politikası değildir.** `scripts/four_company_rls_ci_proof.py` yalnızca sabit CI SQL dizisini oluşturur. Kendisi bir bağlantı açmaz, hiç veri yazmaz, migration çalıştırmaz.

### Kapsam
- 23 şirket-özel tablo: `legal_entity_id` alanı ve `FORCE ROW LEVEL SECURITY` temelinde SELECT/INSERT için ayrı RLS koşulları.
- Dört *tamamen hayalî* PostgreSQL test rolü, yalnızca şirket bazlı ve açıkça izin verilmiş satırları görüntüleyebilir. Gerçek üretim kullanıcıları oluşturulmaz.
- Test şirketi A, B, C, D için yalnızca izolasyonlu test verisi: A/B/D okunabilir, C izinsizdir; A yalnız kendi şirketine INSERT edebilir; B yazamaz; A'nın B'ye kayıt yazma denemesi reddedilir.
- 23 tablonun RLS + FORCE bayrakları ve toplam 46 politika, PostgreSQL sistem kataloglarından doğrulanır.
- Testin en sonunda **ROLLBACK** yapılır; sentetik DB rolleri, şema değişiklikleri, politikalar ve test kayıtları kalmaz.
- Üretimde henüz sahipliği belirlenmemiş kayıtlar için bir şirket varsayımı yapılmaz.

### Bu PR neyi çözmez?
1. Gerçek Streamlit kullanıcıları hâlen ayrı, güçlü, en az yetkili PostgreSQL rolüne güvenli biçimde bağlanmadı. Mevcut ayrıcalıklı bağlantı RLS'yi geçebileceğinden **bu SQL doğrudan canlıya kurulamaz**.
2. İzin kayıtlarının yönetimi ve rol bazlı uygulama kimliği/oturum bütünlüğü henüz canlı düzeyde doğrulanmadı.
3. `product_catalog`, `audit_log`, `system_settings` için ayrı paylaşım/gizlilik kararı ve politikaları gerekiyor. Ortak ürün kataloğu bütün ticari fiyatları otomatik ortak kılmaz.
4. Farklı şirkete bağlı müşteri/sipariş/depo/ürün ilişkileri için fiziki, doğrulanmış ve gerektiğinde bileşik FK zorunlulukları tüm ilişki ağında henüz tamamlanmadı.
5. Üretim Supabase sağlayıcı yedeğinin izole geri yüklemesi, dört resmî şirketin ticaret sicili kimlikleri, kullanıcı rol/şirket izinleri ve mevcut müşteri/irtibat/audit kayıtlarının sahipliği teyit edilmedi.
6. Eski şirket filtresiz UI/API işlemleri bütünüyle kaldırılmadan canlı şirket ayrımı açılamaz.

### Uygulamaya geçiş şartı
Bütün engeller ayrı kontrolle çözülecek; operasyon/satış/muhasebe sahipliği belgeleri karşılaştırılacak; read-only PostgreSQL snapshot/izole restore kayıtları doğrulanacak. Ancak sonrasında, canlıya uygulanacak *ayrı* migration paketi ve bakım/geri alma planı incelenip özel izin istenecek.

**Bu PR, dört şirketin canlı aktif olduğu veya gerçek Supabase kullanıcılarının izole olduğu anlamına gelmez. GitHub PR birleştirme onayı canlı SQL çalıştırma onayı değildir.**
