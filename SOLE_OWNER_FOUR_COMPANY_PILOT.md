# AS Control Tower — İlk Canlı Pilot: Sadece Şirket Sahibinin Hesabı

## Kullanıcı kararı (12 Ekim 2026)

Şirket sahibi, **ilk kullanımda yalnızca kendi hesabının** erişebilmesini istedi. Bu karar, henüz bilinmeyen gerçek uygulama giriş kullanıcı adının tahmin edilmesine veya gerçek kullanıcı kaydı açılmasına izin vermez.

**Hedef erişim kararı** (her şirketin kendi kanıtlı tüzel kişilik ID'siyle ayrı ayrı):

| Şirket etiketi | Tek onaylı yönetici hesabı | Diğer hesaplar |
| --- | --- | --- |
| AS İleri Gıda | Okuma önerisi: EVET; yazma: HAYIR | Erişim yok |
| Planet Ingredients | Okuma önerisi: EVET; yazma: HAYIR | Erişim yok |
| AS Food Global Ltd | Okuma önerisi: EVET; yazma: HAYIR | Erişim yok |
| AS İleri Holding A.Ş. | Okuma önerisi: EVET; yazma: HAYIR | Erişim yok |

Holding şirketi var ve kuruluşunun en az 15 yıl önce tamamlandığı kullanıcı tarafından teyit edildi. Ancak ticaret sicil numaraları/tam tescil unvanı, fiziksel veritabanı kimliği ve mevcut kayıt eşleştirmeleri ayrı doğrulanmalıdır.

## Bu PR'nin yaptığı

- `scripts/sole_owner_four_company_pilot.py`: yalnızca **bir adet etkin ADMIN kullanıcı** (sunucuda önceden doğrulanmış login) bulunan, diğer tüm hesapların etkinlik durumunun **FALSE**, izinlerinin ve DB rolü eşleştirmelerinin boş olduğu açık planı denetler.
- Bu tek kullanıcı için dört ayrı şirketin **tam dört explicit READ izni** gerekir. Yazma izni veya ekstra şirket, genel `*` yetkisi, rol mirası ve kaynağı uyuşmayan manifest engellenir.
- Kullanıcı rol/şirket yetkileri, `company_access_manifest_review.py` ve `company_user_db_role_manifest.py` doğrulayıcılarının kaynak hesabı SHA-256 kontrolleriyle teyit edilir.
- Bir örnek PostgreSQL testinde **bir hayalî rol dört hayalî şirkete ait satırları görür**; öteki üç rol hiçbirini göremez, hiçbiri yazamaz. Bütün şema, kayıt, test rolü ve izinler işlem sonundaki **ROLLBACK** ile kaybolur.
- Sonuç `review_required` olmak zorundadır. Kullanıcı kimlik doğrulaması, gerçek veritabanı rolü ve üretim hakları oluşturulmadığı için **`production_authorized=False`** kalır.

## Gerçek kurulum için hâlâ gerekenler

1. Kullanıcının **mevcut Streamlit giriş kullanıcı adı** uygulamanın sunucu sırlarında kullanıcı tarafından doğrulanacak. Hesap parolası, parola hash'i, Supabase veritabanı parolası, token veya servis anahtarı GitHub PR açıklamasına ya da sohbete yapıştırılmayacak.
2. Yetkili gerçek kullanıcı listesi `APP_USERS_JSON` doğrulanacak. **Diğer hesaplar yetkili ve etkin kalıyorsa ilk tek-hesap planı NO-GO:** hesapları kapatma işlemi de ayrı onaylı değişiklik olmalıdır. Bu PR kimseyi devre dışı bırakmaz.
3. Tek yöneticinin gerçek LOGIN yetkisine sahip, RLS bypass/CREATE ROLE/SUPERUSER izinleri bulunmayan, özel en az yetkili PostgreSQL bağlantısının güvenli oturumu doğrulanacak. Yönetici `DATABASE_URL` bağlantısı operasyonel son kullanıcı bağlantısı olmayacak.
4. Dört şirketin hukukî kayıtları ve gerçek `ct_app.legal_entities` tanımları; müşteri/irtibat/audit dahil eski kayıtların gerçek sahiplik kararı; kalan 23 şirketli tablo FK/RLS ve 3 özel tablo politikaları; eski şirket filtresiz iş ekranlarının kapanması ayrı ayrı doğrulanacak.
5. Gerçek Supabase yedeği bağımsız izole ortama geri yüklenip doğrulanacak. Başarılı CI/ZIP denemesi sağlayıcının yedeklenebildiğini kanıtlamaz.
6. **Okuma pilotu** geçirildikten sonra stok, müşteri, finans ve satın alma için **yazma yetkileri** ayrı ayrı değerlendirilip açık onayla etkinleştirilecek. Bu kullanıcı kararı “hemen sınırsız yazma” anlamında yorumlanmamalıdır.

**Canlı Supabase SQL/DML, kullanıcı düzenleme, şifre değişimi, yedek geri yükleme, dağıtım veya PR merge bu değişiklik kapsamında gerçekleştirilmez.**
