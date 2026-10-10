# AS Control Tower — devam geliştirmesi

10 Ekim 2026. PR #28 üzerindeki ilk pilotun devamıdır. Canlı veriler, main dalı ve dağıtım değiştirilmedi.

## Tamamlanan iş akışları

| İş | Davranış |
|---|---|
| Gerçek maliyet | Mal bedeli, navlun, gümrük, depo/elleçleme, finansman, kur farkı ve diğer masraflar belge referansı, para birimi ve belge kuru ile kaydedilir. |
| Maliyet mutabakatı | Mal bedeli girilmeden kapanamaz. Açık mutabakatta gerçekleşen katkı gösterilmez. Kapandıktan sonra masraf değişikliği için gerekçeli yeniden açma gerekir. |
| Masraf düzeltme | Asıl kayıt silinmez; aynı tutar ve kurla negatif ters kayıt oluşturulur. Aynı masraf ikinci kez ters çevrilemez. |
| Müşteri iadesi | Teslimat ve kalan miktar doğrulanır. İade ayrı HOLD lotuna alınır ve bağlı kalite dosyası otomatik açılır. |
| İadenin finans etkisi | Açık alacak iade tutarı kadar azalır. Önceden tahsil edilmiş kısmı varsa müşteriye geri ödeme borcu oluşur. Banka ancak ayrıca ödeme kaydedildiğinde değişir. |
| Finans ters kayıt | Hatalı ödeme/tahsilat silinmeden ters hareketle düzeltilir. Cari ve banka bakiyesi aynı transaction içinde güncellenir. |
| Çok kalemli sipariş | Aynı müşterinin kabul edilmiş teklifleri ortak başlıkta birleştirilir. Her ürünün alt PO, stok, borç ve maliyet takibi ayrıdır. Bir kalem başarısızsa bütün grup geri alınır. |
| Yönetici görünümü | Net sevk miktarı, iadeden sonraki net satış, teklif katkısı, gerçekleşen maliyet ve mutabakat sonrası gerçekleşen katkı ayrı izlenir. |

Yeni alanlar **Yönetici Paneli → Tekliften tahsilata** işlem merkezindedir. Gerçek maliyet, müşteri iadesi ve finans ters kayıt bölümleri sipariş oluşturulduktan sonra görünür. Çok kalemli form en az iki kabul edilmiş, henüz siparişe dönüşmemiş teklif olduğunda görünür.

## Önemli hesaplama ayrımları

- Masraf kaydı banka transferi ya da ikinci bir borç yaratmaz; maliyet defterini besler. Tedarikçi ödeme/tahsilatı mevcut Finans bölümünden takip edilir.
- Gerçek bir müşteriye para gönderilmez; uygulama muhasebe takibi için kayıt oluşturur.
- Gerçekleşen katkı, kapanmış mutabakatın toplam maliyetini sipariş miktarına dağıtır ve net sevk edilen miktara uygular. İade stoğu kalite onayı olmadan tekrar sevk edilemez.
- Farklı para birimleri kullanıcının belge kuru ile baz para birimine çevrilir; otomatik güncel kur alınmaz.
- İade mahsubu yapılmış tahsilat doğrudan ters çevrilemez; müşteriye geri ödeme borcu üzerinden ilerlenir. Böylece aynı tutarın iki kere geri verilmesi önlenir.

## PostgreSQL gelişmesi

Yeni iş akışı, masraf, iade, çok kalemli sipariş ve ters kayıt tabloları PostgreSQL şema üretimine eklendi. Teklif kilidi PostgreSQL trigger'ıyla da korunur.

`scripts/postgres_workflow.py` aynı iş servislerini gerçek PostgreSQL üzerinde çalıştıran test adaptörüdür. Yalnız açıkça belirtilen loopback adresindeki `ct_test` veritabanını kabul eder; canlı Supabase/PostgreSQL hesabına bağlanmaz.

`scripts/build_workflow_migration.py` mevcut `ct_staging` şeması için eklemeli migration SQL'i üretir. Var olan iş kayıtlarını silmez. Bu SQL kullanıcı ortamında uygulanmadı; yalnız geçici CI veritabanında sınanır.

**Sınır:** Bu aşama bütün Streamlit ekranlarının üretim PostgreSQL veri katmanına geçirilmesi değildir. Uygulamanın normal önizlemesi hâlâ SQLite kullanır. Tüm ekranların kalıcı PostgreSQL bağlantısı, yetki/backup yönetimi ve canlı geçiş ayrı tamamlanmalıdır.

## Doğrulama

- Yerel birleşik set: **135 test geçti, 27 alt senaryo geçti**. Yerel PostgreSQL kurulumu bulunmadığından beş gerçek sunucu testi burada atlanır; ayrı GitHub PostgreSQL 16 servisinde çalışır.
- Python derleme, diff kontrolü ve demo preflight: başarılı.
- Yeni ekran testi: formdan gerçek masraf girişi ve müşteri iadesi; veritabanı sonuçları doğrulandı.
- Testler: açık/tam/kısmi tahsilat sonrası iade, stok HOLD, otomatik kalite dosyası, tekrar referans, fazla iade, eşzamanlı iade, transaction rollback, masraf mutabakatı, ters kayıt, farklı para birimleri ve çok kalemli grup rollback.
- Gerçek PostgreSQL: tekliften tahsilata, iade/geri ödeme, maliyet, eşzamanlı stok/ödeme, ters kayıt, rollback, çok kalemli sipariş ve eklemeli migration veri koruma testi.
- Tarayıcı kabulü: Chromium ve WebKit motorlarında 1440×900 masaüstü, 390×844 telefon boyutu; giriş, korunan modül erişimi ve yatay taşma kontrolü. Fiziksel iPhone/MacBook testi değildir.

### Son doğrulama

Test edilen kod: `33f04c57f10cee3f11edcaf7569b15b08e150151`.

- [GitHub ana uygulama, gerçek PostgreSQL ve tarayıcı testleri](https://github.com/serkanyazicioglu1903/firma-bulucu/actions/runs/38075775169): **üç işin tamamı başarılı**.
- [Staging güvenlik kontrolleri](https://github.com/serkanyazicioglu1903/firma-bulucu/actions/runs/38075775170): **başarılı**.
- 135 yerel/ana uygulama testi + ayrı PostgreSQL sunucusunda 5 test geçti; 27 alt senaryo geçti.
- Chromium ve WebKit motorlarının her birinde masaüstü ve telefon boyutları geçti. Ekran görüntüleri çalışmadaki `browser-acceptance` artifact içinde.
- Sonraki teslim raporu güncellemesi uygulama kodunu değiştirmez.

## Devam eden sınırlar

1. Tam uygulama için üretim PostgreSQL veri katmanı ve kalıcı barındırma geçişi.
2. Gerçek iPhone/MacBook üzerinde kullanıcı kabulü; WebKit motor testi fiziksel cihaz testi değildir.
3. Resmî e-fatura, banka ve Outlook entegrasyonu; bunlar otomatik olarak bağlanmadı.
4. İade iptali/ters iade, tedarikçiye iade, imha/değer düşüklüğü ve otomatik muhasebe dönem kapanışı henüz bu akışta yok.
5. Çok kalemli başlık altındaki alt PO'lar ayrı izlenir; tek çok satırlı ticari belge/PDF çıktısı henüz eklenmedi.

PR birleştirme, canlıya dağıtım veya canlı veri aktarımı yapılmadı; bunlar için ayrıca onay gereklidir.
