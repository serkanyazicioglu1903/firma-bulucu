# AS Control Tower — Ofiste Canlıya Geçiş Runbook

Tarih: 2026-10-08

## Hedef

Premium QA sürümünü güvenli biçimde canlıya almak; giriş/rolleri açmak; kalıcı veritabanına geçişi hazırlamak; ardından Outlook/Calendar entegrasyonunu yetkilendirmek.

## 1. Merge öncesi kapı

PR #7 için aşağıdakilerin tamamı SUCCESS olmalı:

- Legacy review regression tests
- Premium business flow tests
- Search quality tests
- Recommendation UI regression test
- Streamlit startup smoke test

Herhangi biri kırmızıysa merge yapılmaz.

## 2. Premium sürümü main'e alma

1. PR #7 son CI sonucunu kontrol et.
2. Yeşilse PR #7'yi main'e merge et.
3. Streamlit deployment'ın main commit'ini aldığını doğrula.
4. iPhone ve masaüstünden temel smoke test yap:
   - Firma Satın Alma
   - Üretici Bulucu
   - CRM
   - Ürün × Müşteri
   - Teklif
   - PO / Sevkiyat / Stok
   - Finans
   - Kalite
   - AI Yönetici

## 3. Production hardening

Production güvenlik PR'ı güncel main'e yeniden entegre edilmeden önce Streamlit Secrets hazır olmalı.

Minimum:

```toml
CONTROL_TOWER_PASSWORD = "GUCLU_BIR_SIFRE"
```

Tercih edilen çok kullanıcılı yapı:

```toml
APP_USERS_JSON = """[
  {"username":"serkan","display_name":"Serkan","role":"ADMIN","password_hash":"..."}
]"""
```

Roller:
- ADMIN
- SALES
- PURCHASING
- FINANCE
- QUALITY
- VIEWER

Secrets hazır olmadan login gate canlı main'e alınmaz.

## 4. Kalıcı veritabanı

Mevcut SQLite pilot veri modudur. Kritik gerçek şirket verisi girilmeden önce PostgreSQL/Supabase kullanılmalı.

Hazırlık:
1. PostgreSQL/Supabase instance oluştur.
2. DATABASE_URL secret olarak tanımla.
3. Şema/constraint/index tasarımını doğrula.
4. SQLite yedeği al.
5. migrate_sqlite_to_postgres.py ile kontrollü veri kopyası yap.
6. Satır sayıları ve kritik toplamları karşılaştır.
7. Uygulamayı PostgreSQL backend'e geçir.
8. Yeniden CI + smoke test.
9. Ancak doğrulama sonrası gerçek operasyon verisi gir.

Not: mevcut migration helper veri kopyalar; production constraint/index tasarımını tek başına garanti etmez.

## 5. Outlook / Calendar

Outlook PR doğrudan merge edilmez; önce güncel main'e rebase/entegrasyon ve test yapılır.

Gerekli Microsoft Entra bilgileri:
- MICROSOFT_CLIENT_ID
- MICROSOFT_TENANT_ID
- MICROSOFT_ALLOWED_EMAIL (opsiyonel ama önerilir)

İşlem:
1. Entra app registration doğrula.
2. Redirect URI ve Graph izinlerini kontrol et.
3. Streamlit Secrets'a client/tenant bilgilerini gir.
4. Serkan hesabıyla Microsoft kullanıcı onayı ver.
5. Test:
   - mail okuma/eşleştirme
   - müşteri/fırsat bağlama
   - takvim olayı
   - yanlış hesaba erişim engeli
6. Başarılıysa Outlook PR'ını güncel main'e entegre et.

## 6. Canlı kabul testi

Gerçek veri yerine kontrollü test kayıtlarıyla:

1. Test müşteri oluştur.
2. Ana kontak ekle.
3. Ürün eşleştir.
4. Fırsat oluştur.
5. Teklif Taslak -> pipeline değişmemeli.
6. Teklif Gönderildi -> Teklif aşaması.
7. Kabul -> Sipariş.
8. PO oluştur.
9. Kısmi shipment oluştur.
10. Stoğa al.
11. Lotun bir kısmını HOLD yap.
12. Net satılabilir stok doğru azalmalı.
13. Alacak oluştur.
14. Doğru dövizli hesaba kısmi tahsilat.
15. AI Yönetici risk/aksiyon ekranını kontrol et.

## 7. Go / No-Go

GO:
- Tüm CI yeşil
- Login/rol kontrolü çalışıyor
- Kalıcı DB yedeği ve geri dönüş planı var
- Finans ve stok toplamları doğrulandı
- Outlook yetkisi yalnız gerekli hesap/izinlerle çalışıyor

NO-GO:
- CI kırmızı
- Secrets eksik
- SQLite üzerinde kritik production veri girişi planlanıyor
- Migration sonrası satır/toplam farkı var
- Finans veya stokta döviz/miktar tutarsızlığı var
