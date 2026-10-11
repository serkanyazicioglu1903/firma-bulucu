# AS Control Tower — dört şirket / canlıya geçiş durumu

**KAPSAM:** AS İleri Gıda, Planet Ingredients, AS Food Global Ltd,
AS İleri Holding A.Ş. Dört şirketin kurulu olduğu kullanıcı tarafından
bildirilmiştir; bunlar sicilden kontrol edilmiş tam ticaret unvanları ve
PostgreSQL anahtarları olarak değerlendirilmemelidir.

## Bu PR ile eklenen (henüz kapalı)

- Güvenli, şirket bazlı salt okunur **Yönetici Özeti** ekranı
  (`scoped_company_workspace_ui.py`).
- Kullanıcının imzalı sunucu oturumu + `company_read_grants` tablosunda
  seçilen aktif şirket için **açık okuma izni** zorunlu.
- Sekiz kritik ct_app operasyon/finans tablosundaki
  `legal_entity_id NOT NULL` kontrol edilmeden hiçbir özet hesaplanmıyor.
- Sipariş, sevkiyat, stok lotu, kalite, alacak, borç, kasa ve finans
  hareketlerinin **her şirkete ait kayıt adetleri** hesaplanıyor.
- Stok müsait miktarı ve kalite HOLD miktarı kg olarak raporlanıyor.
- Banka/kasa bakiyesi, açık alacak ve açık borç EUR / USD / GBP / TRY olarak
  **ayrı** raporlanıyor. Para birimleri toplanmıyor; kur dönüştürülmüyor.
  `İptal` durumundaki açık alacak/borçlar toplama alınmıyor.
- Birleştirilmiş grup tutarı / mali konsolidasyon **üretilmiyor**.
  Ortak müşteri ve ürün katalogları şirket bazlı sayılmıyor.
- Tamamı salt okunur ve `CT_COMPANY_SCOPED_VIEW_MODE` açık onay olmadan
  etkinleştirilmiyor.

## 4 şirketin gerçek verileriyle çalışabilmek için blokajlar

1. **Kimlik:** Dört şirketin sicil unvanları/vergi no/tescil ülkesini
   doğrula; kullanıcıların hangi şirketlerde rolü olduğunu incele.
2. **Geri yükleme:** Şifreli, bağımsız, güncel PostgreSQL yedeği al;
   AYRI test veritabanına **gerçek geri yükleme tatbikatı** yap; hash ve
   kayıt adetlerini kontrol et. Bu adım yalnızca ZIP doğrulama değildir.
3. **Şirket sahipliği:** Sekiz operasyon/finans tablosunu, depo,
   müşteri ve sözleşme sahipliği dahil tüm kayıtları güvenli eşleştir.
   Kayıtları otomatik veya isim benzerliğiyle şirkete atama.
4. **Şema ve yetkiler:** Testte onaylanan `legal_entities`,
   `legal_entity_id`, bileşik FK, `company_read_grants` ve gerçek
   kimlik/rol eşleştirmelerini canlıda ayrı onaylı migrasyonla uygula.
   Mevcut diğer ekranlar ve export/raporlama yolları için sunucu yetkisi
   + PostgreSQL RLS veya eşdeğeri tam kapsamlı denetim yap.
5. **Yazma işlemleri:** PO, sevkiyat, stok giriş/çıkış, kalite HOLD,
   fatura, tahsilat ve ödemelerde tüm FK'lerin aynı şirkete ait olmasını
   atomik testlerle doğrula. Mevcut `postgres_operational_write.py`
   şirket bilgisi almıyor; çok şirketli kullanım için **uygun değil**.
6. **Finans:** Banka hesaplarının şirket sahipliği, vadeler,
   borç/alacakların teyidi, KDV, kur, grup içi işlemlerin eliminasyonu,
   her şirket için ayrı kâr/zarar ve genel konsolidasyon mali onay gerektirir.
7. **Kullanıcı kabul testi:** Ayrı rol ve şirket oturumlarıyla yetki,
   iptal edilen erişimler, iki eşzamanlı kullanıcının hareketleri, mobil
   ve MacBook formları uçtan uca denenmeden gerçek veri aktarımı yok.
8. **Canlı değişiklik:** Önce tamamlanmış rollback planı, bakım penceresi
   ve ayrı açık **migrasyon ve canlıya geçiş onayı** alınmalı.

**Bu PR canlıya geçiş değildir.** Test PostgreSQL'i geçmesi, Supabase'de
yetkilerin veya gerçek dört şirket kaydının bulunduğunu kanıtlamaz.
Eski şirket filtresiz iş ekranları çok şirketli gerçek finans verisi için
kullanılmamalıdır.
