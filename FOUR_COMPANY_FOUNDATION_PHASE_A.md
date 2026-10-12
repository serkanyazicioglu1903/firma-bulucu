# AS Control Tower — 4 Şirketi Ayırma / Aşama A (Kurulum Provası)

**Üretim veritabanına uygulanmadı.** Bu PR, `AS-CONTROL-TOWER` Supabase `ct_app` şeması için **23 şirket-sahipli operasyon/CRM tablosu** ile 5 erişim/denetim tablosunu oluşturan gerçek SQL'i hazırlar; sadece GitHub'ın izolasyonlu PostgreSQL testinde transaction içinde çalıştırır ve geri alır.

## Hazırlanan gerçek tablo yapısı
- `legal_entities`: yalnızca *doğrulanacak* hukuki şirket kimlikleri için boş registry.
- `company_read_grants` / `company_write_grants`: açık okuma/yazma izni, **DEFAULT FALSE**; bu PR hiçbir kullanıcı eklemez.
- `company_warehouse_scope`: depoların şirket ilişkileri için boş tablo.
- `company_operation_audit`: ilerideki şirket bazlı kayıt oluşturma ve değişiklikler için denetim tablosu.
- 23 şirkete özgü tabloda `legal_entity_id BIGINT NULL REFERENCES legal_entities(id)` ve indeks.

`product_catalog` ürün ana kataloğunda, `audit_log` ve `system_settings` iç yönetim tablolarında şirket sahipliği modeli ayrı hukuki/güvenlik kararı gerektirir. **Ortak ürün kataloğu ürün fiyatları, tedarikçi anlaşmaları veya ticari sırların otomatik olarak ortak görünmesi anlamına gelmez.** Herhangi bir şirket tüm gruba otomatik erişemez.

## 12 Ekim 2026 Salt-okunur Supabase kontrolü
26 tabloda toplam 4 satır (1 müşteri, 1 irtibat kişisi, 2 audit); 23 tablo boş. 26 tablonun hiçbirinde `legal_entity_id` veya RLS politikası bulunmadı. Ayrıca `anon` ve `authenticated` PostgreSQL rollerinin `ct_app` şeması için doğrudan USAGE/SELECT izinleri görülmedi. Bu, yönetici/server rolü gibi diğer bağlantıların güvenliği test edildi anlamına **gelmez**.

## Neden otomatik canlı SQL çalıştırılmadı?
**Mevcut güvenlik sistemi**, ilk şirket sahipliği alanı veya yeni şirket kayıt tablosunu görür görmez eski, şirket filtresiz Streamlit ekranlarını kapatır. Bu yüzden Aşama A'yı aktif uygulamaya bakım penceresi olmadan uygulamak uygulamayı durdurabilir.

Ayrıca:
1. Şirket isimleri yalnızca uygulama etiketleridir; her biri için resmî hukuki unvan ve tescil kanıtı gerekir. AS İleri Holding A.Ş.'nin en az 15 yıl önce kurulmuş olduğu şirket yetkilisi tarafından 12 Ekim 2026'da teyit edilmiştir; kuruluş aşamasında olduğu varsayılmamalıdır. Ancak tüm dört şirketin tam güncel ticaret sicili unvanı ve ayrı tüzel kişilik tanımlayıcıları, canlı veritabanı kimlik satırları oluşturulmadan önce yetkili belgelere karşı eşleştirilmelidir.
2. Dört mevcut kaydın gerçek/dummy durumu ve **hangi şirkete ait olduğu** kanıtla belirlenmelidir; tahmin edilmez ve silinmez.
3. Gerçek uygulama kullanıcıları, giriş kullanıcı adları ve her kişi için şirket bazında READ/WRITE kararları onaylanmalıdır. ADMIN veya holding etiketi otomatik `*` erişimi vermez.
4. Üretimin **gerçek sağlayıcı yedeği/geri yükleme tatbikatı**, tam rol/RLS snapshot'ı, eski API/UI yollarının kontrolü, negatif tenant testleri, 26 tabloda kayıt sahipliği mutabakatı ve ayrı kesinti/geri dönüş onayı gerekir.

## Uygulama sırası
1. Önce üretim şeması ve kayıt sayıları salt okunur tekrar doğrulanır.
2. Gerçek dış kaynak/saglayıcı yedeği ayrı izole ortamda geri yüklenerek test edilir.
3. Resmî şirket kimlikleri ve kullanıcı/şirket izinleri doğrulanır.
4. İzole CI testinde DDL uygulanır; **şirket/izin kayıtları BOŞ kalır**; eski ekranların fail-closed olduğu doğrulanır; rollback ile iz bırakılmaz.
5. Kanıtlanmış sahiplik dağılımından sonra **ayrı Aşama B** (FK, NOT NULL, RLS/sunucu erişim katmanı, rol/provizyon ve UI geçişi) güvenli şekilde denenir.
6. Yalnızca açık işletme onayı, bakım penceresi ve rollback planıyla canlı değişiklik yapılır.

**Bu PR hiçbir müşteri/kişi/finans kaydını atamaz, hiçbir gerçek kullanıcı izni oluşturmaz, şemayı veya sistemi canlıya dağıtmaz. Bu kurulum provasının başarıyla bitmesi canlıya geçiş onayı değildir.**
