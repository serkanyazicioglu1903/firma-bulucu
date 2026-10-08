# AS İleri Control Tower — Premium QA Raporu

Tarih: 2026-10-07

## Kapsam

Aşağıdaki alanlar iş mantığı, veri bütünlüğü, mobil kullanım ve hata senaryoları açısından kontrol edildi:

- Firma Satın Alma / Halefiyet
- Üretici / Hammadde Bulucu
- CRM / Müşteri 360
- Ürün × Müşteri satış zekâsı
- Satış Pipeline
- Teklif & Kârlılık
- Satın Alma / PO / Sevkiyat
- Stok / Yeniden Sipariş
- Finans / Alacak / Borç / Nakit
- Kalite / Claim / HOLD / Sertifika / Regülasyon
- AI Yönetici / CEO özeti
- Mobil Streamlit görünümü

## Premium düzeltmeler

### Arayüz / mobil
- Streamlit development chrome azaltıldı.
- Mobil başlık, metrik, tablo, buton ve form yoğunluğu sadeleştirildi.
- iPhone/iPad için daha sıkı boşluklar ve tam genişlik butonlar eklendi.
- Pilot SQLite veri modu açıkça belirtildi.

### Ürün × Müşteri
- Satır index'i yerine sabit customer_id / product_id seçimi.
- Fat Powder -> Pakmaya stale Ülker seçimi regresyon testi.
- Aktif fırsat / Mevcut / Uygun Değil nedeniyle önerilmeyen kayıtlar açıklanıyor.
- Öneri seviyesi: Güçlü / Orta / Keşif.
- Duplicate aktif fırsat engeli.

### CRM
- Duplicate firma ekleme engeli.
- Ana kontak, e-posta ve telefon müşteri kartından düzenlenebilir.
- Ana kontak işaretlenen kişi müşteri ana iletişim bilgilerine senkron olur.
- Veri kalitesi ekranı eksik sektör/profil/kontakları raporlar.

### Teklif / Pipeline
- Taslak teklif artık fırsatı Teklif aşamasına taşımaz.
- Gönderildi / Revizyon -> Teklif takibi.
- Kabul -> Sipariş ve hızlı teyit/sevkiyat aksiyonu.
- Red -> red nedeni/revizyon takip aksiyonu.
- Kazanıldı/Kaybedildi fırsatlarda açık takip alanları temizlenir.
- Yeniden açılan fırsatta eski kayıp nedeni temizlenir.
- Aktif weighted pipeline Kazanıldı/Kaybedildi fırsatları içermez.

### Satın Alma / Sevkiyat / Stok
- Open PO = sipariş miktarı - stoğa alınmış miktar.
- Reorder projection açık PO bakiyesini dikkate alır.
- Shipment formu sadece kalan PO miktarını sevk ettirir.
- İptal shipment/PO stoğa alınamaz.
- PO miktarını aşan stok girişi engellenir.
- Shipment receiving tek transaction.
- Rezervasyon mevcut stoktan büyük olamaz.
- Çok küçük parsiyel sevkiyatlar desteklenir.

### Kalite
- Kısmî kalite HOLD miktarı desteklenir.
- Etkilenen miktar yoksa güvenli tarafta tam lot HOLD.
- Legacy HOLD lotlar yanlışlıkla serbest sayılmaz.
- Kapanmış vaka + halen HOLD lot varsa CEO uyarısı.
- Yeniden açılan kalite dosyasında eski kapanış tarihi temizlenir.

### Finans
- Tahsilat/ödeme işlemleri atomik.
- Yanlış dövizli banka hesabına tahsilat/ödeme engellenir.
- Fazla tahsilat/ödeme engellenir.
- Duplicate müşteri/tedarikçi fatura numarası kontrolü.
- 30+ gün geciken alacak ve borçlar KRİTİK.
- Nakit tahmini base currency sınırını korur.

### Arama motorları
- Restoran/cafe/franchise/perakende ilanları M&A adayından elenir.
- Preferred M&A kaynağı tek başına yeterli değildir; sektör sinyali gerekir.
- Generic sonuç için satış + üretim + sektör sinyali gerekir.
- Güçlü resmî factory/plant/manufacturing facility kanıtı manufacturer=confirmed.
- Trader/broker kayıtları manufacturer seviyesine yükseltilmez.
- Export/Sales e-postası procurement e-postasına tercih edilir.

### AI Yönetici
- Açık PO ve kalite HOLD stok riskinde dikkate alınır.
- Veri kalitesi teşhis ekranı eklendi.
- Türkçe veri kalitesi soruları genişletildi.
- Weighted pipeline sadece aktif fırsatlardan hesaplanır.

## Otomatik test kapsamı

- Python compile
- Premium business flow testleri
- Search quality testleri
- Recommendation UI regression testi
- Streamlit startup smoke test

Business-flow testleri:
- Ürün-müşteri eşleşmesi
- Duplicate fırsat
- Uygun değil ürünü eleme
- Gerçek maliyet / finansman
- HOLD stok
- Kısmi/tam sevkiyat
- İptal/aşırı PO sevkiyat
- Döviz güvenli tahsilat
- Cash forecast
- Sertifika uyarısı
- AI yönetici
- Data quality
- Partial HOLD
- Open PO stok riski
- Won pipeline dışlama

## Canlıya alınmaması gereken bağımlı parçalar

### Outlook PR
Microsoft Entra kullanıcı onayı ve secret bilgileri bekleniyor.

### Production hardening / roller
Streamlit Secrets içine CONTROL_TOWER_PASSWORD veya APP_USERS_JSON girilmeden canlıya alınmamalı.

### Kalıcı veritabanı
Gerçek production verisi için PostgreSQL/Supabase bağlantısı tamamlanmalı.
SQLite pilot kullanım içindir.
