# AS Control Tower — Gerçek Kullanıcı / PostgreSQL Rolü Ön Kontrolü (PR #84)

## Amaç
Dört şirketli uygulamaya geçerken gerçek insan hesabını güvenli, sınırlı PostgreSQL oturumuyla eşleştirmek. **Bugün yapılmış olan yalnızca doğrulama kodu ve geçici CI testidir; gerçek hesap, rol, kullanıcı şifresi veya canlı veritabanı yetkisi oluşturulmadı.**

## Mevcut tasarımın doğrulanan parçaları
1. `security_admin.py`, Streamlit'de `APP_USERS_JSON` kullanıcısını doğruluyor; eski tek parola yöntemi şirket bazlı oturuma uygun değil.
2. `company_session_principal.py`, sadece doğrulanmış parola, güçlü parola özeti, etkin hesap ve ayrı sunucu imza anahtarı bulunduğunda oturum sahibini imzalıyor. Bu imza kendi başına veritabanı izni vermez.
3. `company_access_manifest_review.py`, her gerçek kullanıcı için açık şirket bazlı okuma/yazma kararını bağımsız kanıtla inceleyebiliyor. ADMIN/HOLDING olma otomatik grup erişimi anlamına gelmiyor.
4. Şirket bazlı RLS için 23 tabloyu kapsayan, dört kurgusal PostgreSQL rolüne dayalı negatif testler PR #83 ile CI'da çalıştı.
5. Fakat uygulama hâlâ `DATABASE_URL` aracılığıyla geniş izinli bir PostgreSQL oturumu açabiliyor. Yönetici oturumu RLS'yi atlayabilir. Bu nedenle **gerçek şirket ayrımı canlıda etkin değildir.**

## PR #84 ne ekledi?
- `scripts/company_user_db_role_manifest.py`: gerçek uygulama kullanıcısı → benzersiz önerilen DB rolü eşleştirmesi için **çevrimdışı belge doğrulayıcı**. Kullanıcı listesi ve bağlama kanıtı **ayrı yetkili insan incelemesi** ile hazırlanmalı; bu kod kullanıcı adları, parolalar, hash'ler veya token'ları veritabanına taşımaz.
- `scripts/company_db_role_preflight.py`: yalnızca PostgreSQL rol sistem kataloğunu okur. Doğrudan bağlantıyla açılmış etkin `LOGIN` hesabını, sahibi olmadığı 23 iş tablosunu, RLS + FORCE ve SELECT/INSERT politika varlığını, en az bir açık iş tablosu okuma iznini ve başka rollerden yetki mirası olup olmadığını kontrol eder.
- `postgres`, `supabase_admin`, `service_role`, `anon`, `authenticated` gibi güçlü/varsayılan roller ve `rolsuper`, `BYPASSRLS`, `CREATEROLE`, `CREATEDB` ayrıcalıkları **reddedilir**.
- `CURRENT_USER` ile `SESSION_USER` eşit olmalıdır. `SET ROLE` ile bir başka kullanıcı kimliğine geçilmiş oturum, gerçek kişiye bağlanmış giriş olarak **kabul edilmez**.
- Bir kullanıcıya onaylanmamış başka PostgreSQL rolü mirası (membership) tanımlanması reddedilir; iki gerçek kullanıcıya tek DB hesabı otomatik atanmaz.
- Başarılı ön kontrolün sonucu `review_required` olur; hiçbir test `production_authorized=True` üretemez. Rol/politika sorguları **içerik güvenliğini değil, başlangıç katalog koşullarını** doğrular. Şirketlerin fiili veri paylaşımı ayrıca test edilmelidir.

## Gerçek kullanıma geçmeden önce uygulanacak kararlar
1. Kullanılacak **gerçek kullanıcı listesi** (kişi/rol/etkinlik durumu), `APP_USERS_JSON` içinde sunucu tarafında doğrulanır; kimlik bilgileri/şifreler GitHub'a veya görüşmeye yapıştırılmaz. Bu PR gerçek kişilerin listesini görmüş veya onaylamış değildir.
2. Her kişiye erişebileceği **AS İleri Gıda / Planet Ingredients / AS Food Global Ltd / AS İleri Holding A.Ş.** seçilir; okuma/yazma ayrı ve kanıtlıdır. Sadece onaylanan kullanıcı ve şirket için izin oluşturulacaktır.
3. Ayrıcalıksız, parola saklaması güvenli gerçek DB oturumu ve güvenilir sunucu yönlendirmesi tasarlanır; web arayüzünden rol veya şirket ID'si geçirerek yükseltme yapılmaz. Mevcut `DATABASE_URL` üstündeki yönetim yetkileri şirket operasyonu için kullanılmamalıdır.
4. Mevcut 4 kaydın şirket sahipliği, 26 tablo/üç iç ve ortak tablo politika kararı, FK kontrolleri, tüm eski şirket filtresiz uygulama yolları, gerçek Supabase yedek/geri yükleme doğrulaması ve bakım/geri dönüş planı tamamlanır.
5. En sonunda gerçek kullanıcılara giriş ve işlem yetkisi verilecek **ayrı canlı veri ve kullanıcı değişikliği** için kullanıcıdan yeni açık onay alınır.

## Kısıt
Bu PR Supabase DDL/DML çalıştırmaz, kullanıcı kaydı açmaz, PR merge/deploy yapmaz, şifre istemez veya mevcut canlı uygulamayı değiştirmez. PostgreSQL kataloğunu okuma kodu kullanıcı/veritabanı bağlantısı özelinde geliştirildi; uygulamanın mevcut gerçek `DATABASE_URL` bağlantısı henüz bununla değiştirilmedi.

**Gerçek kullanıcı kimlikleri ve şirket yetkileri dışarıdan doğrulanana kadar dört şirketli canlı sistem: NO-GO.**
