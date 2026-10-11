# AS Control Tower — Günlük şifreli dış yedek (isteğe bağlı)

**Durum (kod birleşir birleşmez): HAZIR, FAKAT KAPALI.**
Bu özellik kullanıcı GitHub ayarlarından etkinleştirmeden, sunucuya
bağlanmaz, yedek oluşturmaz, şirket verisi indirmez ve depolamaz.

Supabase projesi Free planında olduğu için Pro/Team/Enterprise paketlerine
özgü günlük yönetilen backup/PITR erişimi varmış gibi davranılmamalıdır.
Bu araç tek başına provider-managed backup, felaket kurtarma ve uzun süreli
off-site arşivleme hizmetinin yerini tutmaz.

## Bir defalık kurulum (repo sahibi yapmalıdır)

GitHub reposu `serkanyazicioglu1903/firma-bulucu` →
**Settings → Secrets and variables → Actions**:

1. Repository secret **`CT_BACKUP_DATABASE_URL`**:
   `ct_app` tablolarına salt-okunur erişimi olan **özel yedek kullanıcısının**
   PostgreSQL bağlantı URL'si. Mümkünse güncel Supabase pooler bağlantısını
   kullan. Bu bağlantıyı ChatGPT sohbetinde, GitHub README'de, logda
   veya kaynak kodda paylaşma.
2. Repository secret **`CT_BACKUP_ENCRYPTION_PASSPHRASE`**:
   En az 14 karakterli, benzersiz, güçlü bir şifre. Uygulama içindeki
   şifreli yedeklerle **aynı olması gerekmez**. Bu parolayı güvenli bir
   parola kasasında **GitHub'dan ayrı yerde** sakla; unutulursa indirilmiş
   yedekler açılamaz.
3. Repository variable **`CT_BACKUP_ENABLED`**: Her iki secret hazır ve
   parola güvenli şekilde saklandıktan sonra **`true`** yap.

**Önemli:** Yedek veritabanı kullanıcısının `ct_app` içindeki 26 tabloya
SELECT erişimini ve erişim sınırlarını ayrıca doğrula. Var olan uygulama
yöneticisinin geniş yetkili DB parolasını tekrar kullanmak önerilmez.
Bu işlem için yeni PostgreSQL kullanıcı/grant SQL'ini canlıya otomatik
uygulama. Rol oluşturma ve kimlik bilgisi üretme bağımsız onay gerektirir.

## Otomatik çalıştığında

- GitHub Actions: **Optional daily encrypted PostgreSQL offsite backup**
- Her gün yaklaşık **04:17 Türkiye saati** (01:17 UTC);
  GitHub cron işlerinde gecikme olabilir.
- Tam 26 `ct_app` tablosunu `REPEATABLE READ READ ONLY` işleminde okur.
- ZIP içerikleri sadece işlem belleğinde kalır; üretilen yedek
  AES-256-GCM ve rastgele salt/nonce ile `.asct` olarak şifrelenir.
- `.asct` dosyasını tekrar çözerek doğrular; tablo sayısını,
  ZIP bütünlüğünü ve şifreli SHA-256 değerini sınar.
- GitHub Actions **Artifacts**'ta şifreli çıktı saklanır;
  şifresiz ZIP artefact olarak asla yüklenmez.
- GitHub artefact saklama süresi **7 gün**. Kalıcı arşiv istiyorsan
  dosyayı periyodik olarak indirip ayrı ve güvenli bir konuma taşı.
- Loglara DB URL, parola, müşteri adı, fiyat veya şirket satırları
  yazılmaz. Sadece kayıt/tablo toplamları ve **şifreli dosya** SHA-256'i
  gösterilir.

## İzleme ve güvenlik

1. `Actions` ekranında gerçekten **success** olmuş bir backup run gör.
   **Skipped**, **failed** veya **cancelled**, başarılı yedek sayılmaz.
2. `.asct` dosyasını indir. Control Tower uygulamasında
   **🔐 Şifreli PostgreSQL yedeği → Şifreli dosyayı doğrula**
   ile parola kullanarak şifreli ZIP bütünlüğünü kontrol et.
3. En az bir kez izole, gerçek PostgreSQL geri yükleme tatbikatı
   yap; test ortamının içeriğinin doğru çıktığını doğrula.
4. GitHub Actions'a erişimi olan repo çalışanları şifreli arşiv
   indirebilir. Parolayı onlarla veya arşivle aynı yerde saklama.
5. Repo kamuya açık hale gelir, anahtar sızar veya ekip değişirse
   DB yedek rolünün parolasını ve yedekleme şifresini döndür.
6. 30 MB ZIP / 100.000 satır-tablosu limitleri aşılırsa workflow
   **başarısız olur**; bunu "yedek alındı" diye yorumlama. Daha büyük
   verilerde `pg_dump` veya yönetilen PITR yoluna geçiş planla.

Kullanıcı onayı olmadan GitHub Secrets/Variables kurulmadı ve
Supabase'e hiçbir SQL yazma işlemi uygulanmadı. Bu dosya, kurulum
prosedürünü ve operasyonel sınırları belgeler.
