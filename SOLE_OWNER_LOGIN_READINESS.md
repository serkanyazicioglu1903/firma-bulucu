# AS Control Tower — Serkan Tek Hesap Giriş Ön Kontrolü (PR #86)

Bu hazırlık, kullanıcı tarafından belirlenen **`serkan`** giriş adını hedef alır. Kullanıcı adı **canlı Streamlit sırlarıyla doğrulanmış değildir**; bu PR hiçbir gerçek kullanıcıyı etkinleştirmez/devre dışı bırakmaz.

## Neden gerekli?

`security_admin.py` içindeki eski `CONTROL_TOWER_PASSWORD` tek şifreli geri dönüş yolu, `serkan` hesabını açabiliyor. Ancak `company_session_principal.py` şirket bazlı imzalı oturum için **açık `APP_USERS_JSON`**, **PBKDF2-SHA256 `password_hash`** ve en az 32 karakterlik ayrı **`CT_COMPANY_SESSION_SIGNING_KEY`** istiyor. Tek şifreli yol şirket bazlı erişim vermez.

## Eklenen güvenlik ön kontrolü

`scripts/sole_owner_login_readiness.py` yalnızca **bellekten verilen** yapılandırma örneğini inceler. Gerçek Streamlit sırlarını okumaz; parola, parola özeti, anahtar veya kullanıcı adı döndürmez. `tests/test_sole_owner_login_readiness.py` tamamen kurgusal girdilerle sınır durumlarını test eder.

İstenen yapı:
- `APP_USERS_JSON` içinde açık `username: serkan`, `role: ADMIN`, `enabled: true`.
- Başka kullanıcı varsa `enabled: false` (gerçek hesaplar bu PR ile değiştirilmez).
- `password` düz metin alanı kullanılmaz; `serkan` hesabı geçerli PBKDF2-SHA256 `password_hash` biçimindedir.
- `CT_COMPANY_SESSION_SIGNING_KEY` sunucuda saklanan ayrı güçlü bir anahtardır.
- Eski `CONTROL_TOWER_PASSWORD` geri dönüş yolu kapatılmalıdır; bunun için ayrıca onaylı güvenli dağıtım gerekir.
- `enabled` değerleri JSON boolean olmalı; `"false"` gibi stringler reddedilir. Eski `load_users()` içindeki `bool("false")` davranışının yanlışlıkla kullanıcı açmaması için fail-closed kontrol uygulanır.

### Gerçek sunucuda sonraki doğrulamalar

1. Yetkili operatör Streamlit **Secrets** ayarlarını yerinde denetler; **hiçbir sır veya hash GitHub'a/sohbete kopyalanmaz**. Bu PR gerçek sırları incelemez.
2. Tek gerçek yönetici oturumu güvenli girişle sınanır; başka hesapların fiilen devre dışı olduğu ayrıca doğrulanır.
3. Dört tüzel kişiliğin resmî kimliği, eski dört kaydın sahibi, 23 özel tablonun RLS/FORCE politikaları ve 3 ortak/iç tablonun ayrı politikaları gözden geçirilir.
4. Gerçek Supabase sağlayıcı yedeği ve bağımsız geri yükleme kanıtlanır; uygulamanın yüksek ayrıcalıklı `DATABASE_URL` bağlantısı yerine ayrıcalıksız, gerçek LOGIN rolü kullanılır.
5. Tüm şartlar tamamlanınca **yalnızca okuma** canlı pilotu için ayrı açık onay alınır. Yazma yetkileri ayrıca onaylanır.

**Bu ön kontrolün başarılı sonucu `review_required` olur; asla `production_authorized=true` değildir.** Bu PR canlı SQL, kullanıcı değişikliği, yetki ataması, secrets güncellemesi veya dağıtım yapmaz.
