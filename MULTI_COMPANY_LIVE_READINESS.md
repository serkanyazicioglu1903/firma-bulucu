# AS Control Tower — iki tüzel kişilik için canlı kabul engeli

Tarih: 11 Ekim 2026. Bu kontrol **salt okunurdur**; canlı veritabanında
şema/izin/değer değişikliği veya finans kaydı işlemi yapmaz.

AS İleri Gıda ve AS Food Global ayrı tüzel kişilerdir. İki şirketin banka/kasa,
stok sahipliği, alacak/borç, alış ve sevkiyat kayıtları birlikte kullanılırken
her belgenin **hangi tüzel kişiye ait olduğu** açıkça doğrulanmalıdır.

## Güncel güvenlik bulgusu

`ct_app` şemasındaki kritik 8 operasyon/finans tablosunda
`company_id`, `legal_entity_id` veya `owning_company_id` isimli doğrudan
bir sahiplik alanı bulunmadı. Bu, dolaylı/uygulama seviyesinde ayrımın
kesinlikle olmadığı anlamına gelmez; mevcut şema bunu kendi başına ispatlayamaz.
Bu nedenle gerçek iki şirketli muhasebe ve stok işlemleri için **GO verilmez**.

## Uygulanmadan önce tasarlanması gerekenler

1. Tüzel kişi/şirket ana tablosu ve ilgili şirket kimlikleri; iki şirketin
   gerçek ve onaylı ünvanları/vergi bilgilerinden oluşturulmalı. Demo kayıt yok.
2. Satın alma, sevkiyat, stok lotu, kalite vakası, banka hesabı, borç, alacak
   ve finans hareketinin hangi tüzel kişiye ait olduğu net, tutarlı ve zorunlu
   olmalı; dolaylı model kullanılacaksa uçtan uca kanıtlanmalı.
3. Kayıtların eski/yeni şema geçişi, mutabakat, yabancı anahtarlar, indeksler,
   rapor filtreleri ve audit log planlanmalı; ayrı test dalında denenmeli.
4. Yetkilendirme: yalnız `Streamlit` oturum rolüne güvenilmemeli;
   yetkisiz kullanıcı diğer şirketin kayıtlarına erişememeli. Supabase'in
   `anon`/`authenticated` grant ve RLS gereksinimleri ayrıca denetlenmeli.
5. İki şirket için ayrı banka mutabakatı, KDV/vergi ve para birimi senaryoları
   gerçek yetkililerce test edilip tutanak imzalanmalı.
6. Şema migrasyonu/gerçek veri dönüştürme öncesi güvenli şifreli yedek,
   izole restore testi, geri alma planı ve **ayrı yönetici onayı** gerekir.

## Mevcut denetim ekranı

`📋 Canlı kullanım kabul raporu — hızlı erişim` artık bu alanların metadata
kontrolünü de salt okunur yapar; eksik alan sayısını gösterir. Kolonlar
bulunsa bile uygulamanın yetki ve şirket bazlı muhasebe testi yapılmadan
"hazır" bildirimi verilmez.

Bu geliştirme yalnızca denetim ve kapı kontrolüdür. Canlı tabloya şirket
kolonu, veri, izin veya otomatik migration **eklemez**.
