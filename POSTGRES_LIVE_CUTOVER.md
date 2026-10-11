# AS Control Tower — PostgreSQL live cutover

## Activation behavior

The Streamlit deployment already has `DATABASE_URL` in Secrets. Once this
reviewed change is merged and the deployment restarts, Control Tower selects
the persistent **Supabase PostgreSQL `ct_app` schema by default**. Both the
business forms and their dashboards/reporting/AI reads use PostgreSQL through
the compatibility layer. Manufacturing/producer sourcing and company-acquisition
search remain separate from the business database.

There is **no automatic table creation, destructive migration, mock data seed,
or data copying**. The local SQLite file is preserved untouched. The cutover
refuses to proceed when:

- The `DATABASE_URL` secret is invalid or Supabase is unreachable;
- The full `ct_app` 26-table structure is not valid;
- Any retained legacy SQLite business record is detected; or
- The old SQLite file's schema or integrity cannot be verified.

If PostgreSQL fails, Control Tower displays a safe error and **does not fall
back to SQLite**, preventing silent split-brain records.

## Implemented safeguards

- Psycopg connection pool with mandatory TLS (unless an exact disposable local
  CI test URL), bounded connections, statement timeouts and disabled server-side
  prepared statements for transaction-pooler compatibility.
- Existing 26-table Control Tower business forms, user role portal, AI and
  management reporting resolve to the same `ct_app` backend.
- A known-syntax SQLite-to-PostgreSQL SQL compatibility shim preserves bound
  parameters, aliases, date arithmetic, min/max and rounding behavior.
- Direct form writes require authenticated role permissions and produce an
  atomic PostgreSQL audit entry inside the same transaction.
- Shipment stock receipt, supplier payments and customer collections use the
  audited native PostgreSQL transaction engine with replay guards, row locks,
  currency consistency and quality HOLD payment blocking.
- Empty workspace and detailed PostgreSQL Streamlit integration tests run on
  a **disposable localhost PostgreSQL 16 database only**; they never access the
  user's Supabase instance.
- Admin-only **Sistem Yönetimi** contains live health, audit and optional
  on-demand ZIP export of all 26 PostgreSQL tables. The archive contains
  sensitive company data and is intentionally not stored by this application.

## First live acceptance on phone and Mac

1. Reopen or reboot the existing Streamlit app after merging.
2. Log in to AS Control Tower. At its top expect:
   **🟢 Canlı veri modu: ... Supabase PostgreSQL ct_app**.
3. Check the executive panel shows empty new business data, not demo rows.
4. In **Sistem → Sistem Sağlığı**, run count checks.
5. Add one explicitly approved *real* nonfinancial master entry (e.g. a
   company-own warehouse or test-labeled record) and confirm that it persists
   after reboot. Do not use fictional production invoices.
6. Verify role restrictions and export a verified backup before entering
   substantial financial records. Confirm provider-managed encrypted backup
   and restore policy separately.

## PostgreSQL operasyon mutabakatı — salt okunur

**Sistem → 🔍 Operasyon Mutabakatı** runs ten fixed aggregate-only checks against
the same `ct_app` data in one PostgreSQL REPEATABLE READ / READ ONLY
transaction. The controls flag:

- Received shipments without stock lots and unreceived shipments with lots;
- Non-cancelled shipments over the PO quantity;
- Invalid stock quantity/reservation/HOLD combinations;
- HOLD lots without a matching quality case or inconsistent HOLD status;
- Overpaid supplier invoices and overcollected customer receivables;
- Reused bank-account transfer references and negative cash balances.

The UI displays only safe counts, descriptions and severity to authenticated
ADMINs on an explicit button click. It never returns customer identifiers or
finance record details and never alters a ledger, quality case or lot. A
zero-issue result validates **only these ten rules**; it is not a complete
accounting reconciliation, authorization assessment or a backup restore drill.
A finding requires manual investigation by the responsible business team.
The checks are also tested on a disposable local PostgreSQL CI service, with
fictional bad-stock input to establish that anomalies are detected.

## İndirilmiş ZIP dosyasının yerel bütünlük kontrolü

**🧪 İndirilen yedeği doğrula — hızlı erişim**, yalnızca giriş yapmış
**ADMIN** kullanıcısına açılır. Kullanıcı kendi telefonundan/Mac'inden
aldığı ZIP dosyasını Streamlit uygulamasına seçer ve kontrol düğmesine
bilerek basar. Araç ZIP'i uygulama belleğinde sınırlar ve şu kontrolleri
yapar:

- Tam 26 tablo ve izinli ZIP üyeleri; geçerli yedek formatı/manifest;
- Her tablo için SHA-256 ve bildirilen satır sayısı;
- Gerçek satırlar mevcutsa beklenen kolon adlarının bire bir eşleşmesi;
- En fazla 30 MB ZIP, ZIP açılma boyutu ve satır sayısı sınırları.

İşlem sırasında **veritabanına erişilmez, satır güncellenmez**, sunucu diskine
yedek kaydedilmez ve satır içerikleri ekranda gösterilmez. Yalnızca
arşivin bütün dosya SHA-256 değeri, tablo/kayıt sayıları ve tarih gösterilir.
Bu doğrulama, dosyanın korunmuş olabileceğini kanıtlar; onu canlı Supabase'e
geri yüklemez, felaket kurtarma testinin yerini tutmaz.

**Gizlilik:** ZIP dosyası Streamlit sunucusuna bellekte doğrulama amacıyla
aktarılır; ChatGPT sohbetine yüklemeye gerek yoktur. Dosya düz metin ZIP
biçimindedir ve şirket verisi içerir: güvenli, şifreli özel depoda tutulmalıdır.

## Yedekten geri yükleme tatbikatı — gerçek fakat izole PostgreSQL

GitHub Actions, 26 tabloluk uygulama yedeğinin manifestini ve SHA-256
kontrollerini doğrulayarak ZIP içeriğini yalnızca **geçici yerel PostgreSQL CI**
veritabanındaki `ct_restore_verify` şemasına geri yükler. Bütün satırları,
sütunları ve yabancı anahtar ilişkilerini tekrar kontrol eder. Geri yükleme
ayrı bir transaction içinde yapılır ve doğrulama başarılı olsa bile
**kesinlikle ROLLBACK** edilir. Böylece veritabanında kalıcı test şeması
veya sahte kayıt kalmaz.

Geri yükleme aracında üretim/Supabase URL'leri açıkça yasaklanmıştır;
yalnızca `CT_LOCAL_POSTGRES_TEST=1` ile belirtilen sabit localhost CI
kullanıcısı, veritabanı ve portu kabul edilir. Streamlit arayüzünde geri
yükleme komutu veya butonu yoktur.

**Sınır:** Bu tatbikat ZIP formatının bir test PostgreSQL sunucusunda
geri yüklenebildiğini gösterebilir, ancak kullanıcının iPhone'da indirdiği
özgül dosyaya erişmez. Supabase'in kendi otomatik yedek/PITR hizmetinin
yapılandırmasını veya felaket kurtarma planını da doğrulamaz. Bu iki canlı
ortam kalemi ayrıca kontrol edilmeden tam üretim sertifikası verilmez.

## Gerçek şirket kayıtlarının kontrollü CSV aktarımı

Canlı PostgreSQL ekranındaki **📥 Şirket verilerini içe aktar — hızlı erişim**
bölümü yalnızca ADMIN kullanıcıya açıktır. Buradan üç ayrı boş UTF-8 CSV
şablonu indirilebilir: Müşteriler, Ürünler (üretici/tedarikçi bilgisi dahil)
ve Depolar. Uygulama hiçbir hayali veri önceden doldurmaz.

Dosya seçildikten sonra (en fazla 150 kayıt / 512 KB) bütün alanlar,
zorunlu değerler, maksimum uzunluklar, aynı dosyadaki mükerrer adlar ve
para birimi/depo tipi doğrulanır. İlk 20 satır önizlenir; **önizleme hiçbir
veritabanı işlemi yapmaz**. Kalıcı içe aktarım ancak aynı işlem sırasında:

1. Yönetici olarak giriş yapılmışsa;
2. Güncel PostgreSQL yedeğinin güvenli saklandığı onay kutusuyla belirtilmişse;
3. `ONAYLI_KALICI_AKTARIM` ifadesi yazılmışsa; ve
4. **Yeni kayıt ekle** düğmesine açıkça basılmışsa

çalışır. Her satır yeniden doğrulanır. Mevcut PostgreSQL `ct_app` üzerinde
her kaydın adı kontrol edilir. Dosyadaki tek bir mevcut ad bile tüm toplu
işlemi durdurur; daha önce bu dosyadan eklenen kayıtlar aynı transaction
içinde geri alınır. Başarılı eklemelerin tamamı aktörü belirtilmiş
`audit_log` satırlarıyla aynı transaction içinde saklanır.

**İçe aktarma finans, satın alma siparişleri veya stok hareketi yaratmaz.**
İçe aktarım, müşteri ve tedarikçi isimlerini veya ticari koşulları kendisi
araştırmaz; yalnızca yönetici tarafından onaylı CSV içeriğini kaydeder.
Kaynak şablonlar gerçek şirket verileriyle doldurulmadan gerçek şirket
kayıtlarının yüklendiği iddia edilemez.

## Salt okunur PostgreSQL güvenlik durumu

**🔐 PostgreSQL güvenlik kontrolü — hızlı erişim**, yalnızca yetkili
ADMIN kullanıcı düğmeye bastığında TLS kullanımını, mevcut PostgreSQL
rolünün süper kullanıcı/rol oluşturma/RLS atlama izinlerini, `ct_app`
tablolarında RLS etkinliğini ve asgari CRM/denetim günlüğü yetkilerini
kontrol eder. Bu SQL işlemlerinin tümü read-only transaction içindedir;
kullanıcı adı, veritabanı adresi, şifre, firma kayıtları veya token
görüntülenmez.

RLS kullanımının gerekliliği mimariye bağlıdır: yalnızca sunucu taraflı
Streamlit bağlantısıyla uygulama rolleri denetleniyorsa doğrudan istemci
erişimi olan bir sistemden farklıdır. Gelişigüzel canlı şema/RLS değişikliği
yapılmaz; ayrı gözden geçirilmelidir.

Bu araç Supabase proje ayarlarına/Management API'ye erişmediğinden
**otomatik yedekleme, saklama süresi, Point-in-Time Recovery, firewall,
restore tatbikatı ve key rotation** durumunu daima *hesaptan
doğrulanmalı* olarak gösterir. Salt SQL sorgusundan genel
`production_ready` sonucu üretmez.

## Critical limitations and rollback

- The GitHub CI test verifies the code against PostgreSQL 16 but **does not
  constitute a live Supabase write, production load, backup-restore, or device
  acceptance test**.
- There is no automatic import of historical SQLite data. The owner's
  last read-only preflight showed 0 business rows and an empty `ct_app`
  schema. Live startup repeats the SQLite-data gate rather than trusting the
  prior screenshot.
- Provider-managed Supabase snapshots, restore drills, connection permission
  hardening, row-level security and multi-user concurrent load testing are
  operational prerequisites for unrestricted financial production use.
- The local SQLite file remains available for investigation but should not
  become an independent live source after cutover. If Supabase is unavailable,
  leave the app stopped/fail-closed and repair or restore the database; do not
  resume new business writes to ephemeral SQLite.

## Development status

This branch intentionally replaces the old **SQLite pilot default** only when
the trusted `DATABASE_URL` is configured and validated. Without a configured
PostgreSQL connection, existing isolated SQLite development/test behavior is
left unchanged. Legacy SQLite-dependent System Management is replaced by the
PostgreSQL-only administration panel while PostgreSQL is active.
