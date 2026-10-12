# AS Control Tower — 4 Şirketli Canlı Geçiş: Yedek + Geri Yükleme Kontrolü

**Kapsam:** Supabase `AS-CONTROL-TOWER`, PostgreSQL `ct_app` (26 tablo).
**Durum:** Salt okunur hazırlık. **Canlı migrasyon/rol/erişim/yedek geri yükleme onayı değildir.**

## 1. Canlı veritabanında salt okunur başlangıç tespiti (12 Ekim 2026)

| İncelenen konu | Bulgular |
| --- | --- |
| `ct_app` tablosu | 26 |
| `customers` | 1 kayıt |
| `contacts` | 1 kayıt |
| `audit_log` | 2 kayıt |
| Geri kalan 23 tablo | 0 kayıt |
| `legal_entity_id` içeren tablolar | 0 |
| RLS açık tablo | 0 |
| RLS politikası olan tablo | 0 |
| Supabase development branch | 0 |
| Supabase migration history | 0 |

**4 satırın sahibi ve anlamı belirlenmiş değildir; gerçek/dummy olduğuna hükmedilip silinemez.** Bu sayılar değişebilir; canlı geçişte tekrar yeni bir tutarlı snapshot alınmalıdır. Durum herhangi bir şekilde kullanıcı yetkisi, iş kayıtlarının doğruluğu veya sağlayıcının yedek güvencesi anlamına gelmez.

## 2. Kodda var olan, yeni güçlendirilmiş geri yükleme çalışması

Mevcut altyapı:

- `scripts/postgres_backup.py`: mevcut **legacy** 26 tabloyu salt okunur `REPEATABLE READ` ile ZIP'e aktarır; kayıt ve kolonların SHA-256 kontrolü yapılabilir.
- `scripts/postgres_encrypted_backup.py`: dışa aktarılan ZIP'in şifrelenmesini ve çözülmesini destekler.
- `scripts/postgres_restore_drill.py`: **yalnızca localhost + CI veritabanı** içinde geçici `ct_restore_verify` şemasına gerçek veritabanı geri yükleme provası yapar; constraint / satır karşılaştırmalarını test eder ve **mutlaka rollback** yapar. Supabase URL'sini reddeder.
- `scripts/postgres_backup_reference_hash.py`: ayrı saklanan SHA-256 referansını arşivle karşılaştırır.

Bu PR ile eklenenler:

- `scripts/postgres_recovery_baseline.py`: 26 tablonun **yalnızca sayılarını** ve PostgreSQL kolonlarının fiziksel özellikleri için SHA-256 parmakizini (iş satırlarını çekmeden) çıkarır.
- Yedek geri yükleme CI provasında `ct_app` ile geçici `ct_restore_verify` tablosunun **26 adet kolon parmakizi ve kayıt sayısı** ayrıca karşılaştırılır. Eski satır-bazlı karşılaştırma ve FK kontrolü korunur.
- Testler eksik tablo, başlamış şirket migrasyonu, RLS, farklı şema, değişen kayıt sayısı, sahte özetteki tutarsızlık ve canlı Supabase'e geri yükleme yasağını kapsar.

**Sınırlar:** Bu kayıt-sayısı/kolon parmakizi testi gerçek ödeme, stok ve maliye mutabakatının yerini tutmaz. Birbirinden farklı içerik aynı kayıt sayılarına sahip olabilir. Yedek kökeni, planlanan saklama süresi, anahtarların güvenli saklanması, PostgreSQL kullanıcı/rolleri ve sağlayıcı düzeyindeki **PITR** bu işlemlerle kanıtlanmaz. Başarılı CI testi ancak `review_required` sonucuna gider, `production_cutover_approved=False` kalır.

## 3. Canlı veri değiştirilmeden önce zorunlu sıra

1. **Kimlik ve şirket:** AS İleri Gıda, Planet Ingredients, AS Food Global Ltd ve AS İleri Holding isimlerinin resmî sicil kayıtları ve hukuki unvanları bağımsız olarak doğrulanır. Holding olması otomatik diğer şirket okuma hakkı vermez.
2. **Eski kayıt envanteri:** 26 tablo, mevcut 4 kayıt ve 8 kritik tablodaki tüm işletme ilişkileri tekrar tutarlı read-only snapshot'la kontrol edilir. Eski kayıtlar sırf demo görünümü nedeniyle silinmez, şirkete rastgele atanmaz.
3. **Sağlayıcı yedeği:** Supabase panelinde mevcut hizmetin gerçek yedek / PITR durumu, son geri dönüş noktası, saklama süresi, şifreleme yöntemi, geri dönüş saati ve geri yükleme yetkisi bağımsız olarak doğrulanır. Bu bilgiler **bu PR tarafından teyit edilmiş değildir**.
4. **Bağımsız kopya:** Yedek/anahtarlar ayrı güvenli ortamda tutulur; dosyanın ayrı saklanan SHA-256 değeri teyit edilir. Mevcut `ct_app` ZIP'i **şirket migrasyonu sonrasındaki rolleri/RLS'yi ve yeni kayıt tablolarını içermez**; bunlar için ayrıca tam kapsamlı PostgreSQL/provider restore planı gerekir.
5. **İzole geri yükleme:** Üretim dışı, yetkileri kısıtlı ayrı PostgreSQL projesinde/klonunda gerçekten restore edilir. Kaynak ve izole hedefin tablo sayıları, kolon parmakizleri, PK/FK, row counts, referans bütünlüğü, sequence ve iş mutabakatı kayda geçirilir. Gerçek restore hedefi hiçbir koşulda mevcut canlı projeye yöneltilmez.
6. **Yetkiler ve RLS:** 26 tablo için kayıt sahipliği, `legal_entities`, kullanıcı/şirket izinleri ve RLS/ya da bağımsız kanıtlı sunucu yetki katmanı gözden geçirilir. Tek şirkete ait yetkiyi diğerinin satırlarını okuma/yazma için kullanmaya yönelik olumsuz testler zorunludur. `service_role` ile tüm verilere sınırsız erişen uygulama bağlantısı kullanılmaz.
7. **İki aşamalı migrasyon:** Yalnızca onaylı bakım penceresinde önce nullable sahiplik alanları, bağımsız kanıta göre kayıt eşleştirme ve mutabakat; ardından FK/NOT NULL/RLS ve erişim kontrolleri. Eski şirket filtresiz uygulama akışları tamamen kapatılmadan prod aktivasyonu yapılmaz.
8. **Açık son onay:** İsim ve kapsamı tanımlanmış canlı işlemler için ayrıca kullanıcı onayı; mali/operasyonel mutabakat raporu ve açık geri dönüş planı. Başarısız herhangi bir kontrol = **NO-GO**, gerçek iş kayıtlarına yazma başlamaz.

## 4. Yayına alma kararı için kanıt paketi

Yayınlanacak paket sadece **özet kimlikler/referanslar** içermelidir: kaynak snapshot tarihi, `schema_sha256`, `counts_sha256`, 26 tablonun sayıları, şifreli arşiv SHA-256 (dosyadan bağımsız saklanan), sağlayıcı geri yükleme denemesinin kayıt/işlem referansı, izole hedef, tutarlı PK/FK ve işlem mutabakatı sonucu, yetki/RLS olumsuz test çıktısı, yetkili onay isim/tarihleri, başarısızlık durumunda geri dönüş adımları. **Arşiv, DB URL, şifre, finansal satırlar veya kullanıcı parolaları GitHub'a/PR açıklamasına konmamalıdır.**

## 5. Mevcut durumda ne yapıldı / ne yapılmadı?

Yapılan: salt okunur canlı envanter; yeni CI baz çizgi/parmakizi kodu; izole PostgreSQL yedek geri yükleme testinin güçlendirilmesi; kontrol listesi.

**Yapılmayan:** Supabase production restore, gerçek/provider yedeği alma ve indirip saklama, yeni Supabase projesi açma veya ücretli branch oluşturma, canlı SQL migrasyonu, canlı rol/RLS/GRANT değişimi, kayıt silme/eşleştirme, PR merge ve canlı deploy. Bunlar ayrıca onay gerektirir.

**Bu nedenle “yedekler doğrulandı, canlıya geçilebilir” iddiasında bulunulmaz.**
