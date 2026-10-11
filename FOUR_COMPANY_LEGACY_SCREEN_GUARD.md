# AS Control Tower — otomatik dört şirket geçiş kilidi

**Bu PR canlı veritabanında değişiklik yapmaz.** Kod yalnızca mevcut
`ct_app` şemasının okunabilir metadata'sını inceler; şirketlere kayıt
atamaz, kullanıcı oluşturamaz, izin veremez ve ödeme yapamaz.

## Neden gerekli?

Mevcut eski Control Tower ve rol portalı yazma/okuma yolları:
`control_tower.py` (uyumluluk köprüsünden SELECT/INSERT/UPDATE),
`role_portal.py`, `postgres_workspace.py`,
`scripts/postgres_operational_read.py` ve
`scripts/postgres_operational_write.py` **genel olarak dört şirket
bazlı filtrelenmiş değildir**. Bunların testlerde çalışması şirketler
arası izolasyonu kanıtlamaz.

Önceki PR #58 güvenli, doğrulanmış kullanıcı oturumu ile açılan read-only
şirket ekranını **isteğe bağlı** hazırlamıştı. Ancak owner migrasyonu
başladığında bu mod aktive edilmezse eski ekranların açık kalma
riski vardı.

## Yeni otomatik fail-closed yönlendirme

Her başarılı, giriş yapılmış canlı PostgreSQL Control Tower ekranında
`inspect_company_migration_state` çağrılır, **yalnızca pg_catalog** okunur:

| Görülen ct_app metadata durumu | Eski ekranlar |
| --- | --- |
| Sekiz kritik tablo mevcut; hiç legal_entity_id/grant tablosu yok | Mevcut davranış korunur — **bu dört şirket onayı değildir** |
| Sadece birkaç owner kolonu veya grant tablosu var | Tamamen engellenir |
| Sekiz owner kolonu ve tüm üç ilişki/izin tablosu var | Tamamen engellenir |
| Şema sorgulanamaz, beklenmedik tablo/metadata var | Tamamen engellenir |

Kilit, **normal SELECT/INSERT/UPDATE/sevkiyat/finans formları, import,
export, rapor ve role portal yüklenmeden önce** çalışır. Yalnızca
ayrı ve açıkça etkinleştirilmiş
`CT_COMPANY_SCOPED_VIEW_MODE=REVIEW_ONLY_WITH_SIGNED_SESSION` inceleme
modu kilitten önce kendi güvenli UI yoluna gider. O yol da imzalı login,
şirket grant'ı, sekiz NOT NULL owner kolonu ve kontrollü sorgu olmadan
veri göstermez.

Hatalı DB metadata durumunda eski UI gizlenir; sistem otomatik olarak
SQLite'a geçmez. Bu bir güvenlik kilididir, canlı geçiş otomasyonu değil.

## Test kapsamı

- Offline metadata senaryoları: owner kolonu yok, ilk kolon eklenmiş,
  eksik grants, tamamlanmış tablolar, yanlış tablo yapısı ve DB hatası.
- UI yönlendirmesi: eksik owner/grant metadata durumunda hiçbir eski
  Control Tower sekmesi veya role portal açılmaz.
- Gerçek geçici PostgreSQL entegrasyonu: mevcut 8 tablo → nullable
  owner migration → 8 owner kolon/grant tabloları → tümünü geri alan
  transaction; kilit davranışı her aşamada doğrulanır.

## Eksik ZIP yedeğinin otomatik engellenmesi

`scripts/postgres_backup.py` eski 26 tablodan ZIP üretiyor. Yeni
`legal_entities`, `company_read_grants`, `company_write_grants` ve
`company_warehouse_scope` tabloları bu ZIP formatının parçası değil.
Dolayısıyla şirket migrasyonu başladığında bu formatın kullanımına
izin vermek, **eksik kurtarma dosyasına tam yedek demek** olur.

Bu PR, mevcut AES ve normal ZIP export yolunda, veri satırlarına
girmeden önce aynı metadata kilidini çağırıyor. Owner/grant yapısı
algılanırsa `company_scope_unsupported` ile indirme engelleniyor;
içerik üretilmiyor ve telefondaki yedek ekranı nedeni açıkça gösteriyor.

Bu **yedek almamak** anlamına gelmemeli: grup şirketli şema için
ayrı hazırlanmış eksiksiz veri + şema + izinler + dış depo yedeği
ve bağımsız bir geri yükleme testi zorunlu. Bu PR böyle bir yedekleme
mekanizması veya gerçek Supabase restore testi sağlamaz.

## Hâlâ canlıya hazır değil

Bu kilit **eski şema devam ederken var olan şirketler arası erişimi
düzeltmez**, eski ekranları yeni çok-şirketli hale getirmez. Sekiz tablo
dışındaki paylaşılan CRM ve ürün ekranları, RLS/least-privilege, üretim
şirket kodu/vergi eşleştirmesi, manuel sahiplik onayı, gerçek bağımsız
şifreli yedek ve geri yükleme, ödeme mutabakatı ve intercompany
konsolidasyon ayrı eksiklerdir.

CI ortamındaki 26-tablo ZIP restore tatbikatı **gerçek Supabase yedeğinin
bağımsız ortamda geri yüklendiği anlamına gelmez**. Böyle bir yedekleme
kanıtı gelmeden üretim göçü onaylanmamalı.

**Canlı Supabase şemasında DDL/DML yok, PR merge yok, feature flag
değişikliği yok.** Yeni kilit kodunu birleştirmek için ayrıca onay
istenir; production migration ve deployment farklı bir onay sürecidir.
