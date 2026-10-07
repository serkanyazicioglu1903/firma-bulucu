# AS Control Tower — Production Setup

Bu branch şirket kullanımına hazırlık içindir.

## 1. Zorunlu giriş koruması

Streamlit Cloud > App > Settings > Secrets içine en az:

```toml
CONTROL_TOWER_PASSWORD = "GUCLU_BIR_SIFRE"
```

Bu durumda kullanıcı adı: `serkan`, rol: `ADMIN`.

Çok kullanıcılı kullanım için:

```toml
APP_USERS_JSON = """
{"users":[
  {"username":"serkan","display_name":"Serkan","role":"ADMIN","password_hash":"HASH","enabled":true},
  {"username":"satis1","display_name":"Satış 1","role":"SALES","password_hash":"HASH","enabled":true},
  {"username":"satinalma","display_name":"Satın Alma","role":"PURCHASING","password_hash":"HASH","enabled":true},
  {"username":"finans","display_name":"Finans","role":"FINANCE","password_hash":"HASH","enabled":true},
  {"username":"kalite","display_name":"Kalite","role":"QUALITY","password_hash":"HASH","enabled":true}
]}
"""
```

Hash üretmek için ADMIN ile giriş yaptıktan sonra:
AS Control Tower > Sistem > Rol Yapısı > "Hash üret".

## 2. Roller

- ADMIN: tam yetki
- SALES: CRM, ürün-fırsat, teklif, pipeline, takip, görev, AI
- PURCHASING: satın alma, stok, kalite, görev, AI
- FINANCE: teklif, finans, rapor, görev, AI
- QUALITY: kalite/regülasyon, CRM, görev, AI
- VIEWER: yönetici raporu, AI, CEO ekranı

Bu sürümde giriş ve audit aktiftir. İnce taneli ekran gizleme kademeli olarak geliştirilebilir.

## 3. Audit Log

INSERT / UPDATE / DELETE işlemleri:
- kullanıcı
- rol
- işlem
- tablo
- SQL özeti
- oturum kimliği

ile audit_log tablosuna yazılır.

## 4. Yedek

AS Control Tower > Sistem > Yedekleme bölümünden tam SQLite .db yedeği indirilebilir.

ÖNEMLİ: Streamlit dosya sistemi kalıcı veritabanı için ideal değildir.
Gerçek şirket kullanımına geçmeden önce yönetilen bulut veritabanına geçiş önerilir.

## 5. Bulut veritabanı geçişi

Hazır script: `migrate_sqlite_to_postgres.py`

Gerekli:
- PostgreSQL/Supabase connection string
- Streamlit Secrets veya yerel environment içinde DATABASE_URL

Örnek:
```
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres
```

Önce mevcut .db dosyasının yedeğini al.
Sonra migration scriptini çalıştır.
Cutover, bağlantı bilgileri doğrulandıktan sonra yapılmalıdır.

## 6. Outlook

Outlook entegrasyonu ayrı PR #2'de hazır bekliyor.
Microsoft Entra onayı kullanıcı tarafından yapılmadan main'e alınmamalıdır.
