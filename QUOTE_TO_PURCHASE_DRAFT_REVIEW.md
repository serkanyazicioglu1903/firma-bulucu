# AS Control Tower — Gerçek tekliften satın alma taslağı (PR adayı)

## Kapsam
Mevcut **Gerçek Teklif / Kârlılık** ekranında manuel fiyat, kur, navlun,
ithalat giderleri, finansman ve vadelerle yapılan geçerli hesaplamadan sonra
açılan **Tekliften satın alma talep taslağı** bölümü, tedarikçi adı, ürün ve
teslim deposu girilerek **onaysız CSV taslağı** hazırlar.

- Şirket etiketleri: AS İleri Gıda, Planet Ingredients, AS Food Global Ltd,
  AS İleri Holding A.Ş.
- Alış birim fiyatı, miktar, alış dövizi, manuel kur, alış tutarı, tahmini
  ithal ve finansmanlı maliyet, ön ödeme ve kalan ödeme vadesi hesaplamadan
  sabit olarak aktarılır; tahmini hedef satış fiyatı ayrı gösterilir.
- İsteğe bağlı manuel iç takip referansı oluşturulabilir.
- Taslak sadece kullanıcı açıkça "hazırla" dedikten sonra indirilir.
- Müşteri/ürün veritabanı kayıtları, demo veri, eski SQLite ve Supabase
  **kullanılmaz veya değiştirilmez**.
- Kullanıcı/oturum/şirket/para birimi değiştiğinde veya hesap yeniden
  yapıldığında önceki taslak iptal edilir.
- Serbest metinde CSV formül enjeksiyonları reddedilir.
- Üretilen dosya veritabanına kayıt değildir, numaralı PO değildir,
  muhasebe kaydı veya tedarikçiye bağlayıcı sipariş değildir.

## Dört şirket için henüz çözümlenmemiş zorunlu kontroller
Dört sabit şirket **etiketi**, doğrulanmış ticari sicil ID'si veya kullanıcı
erişim izni değildir. Bu PR şirket ayrımını **tamamlamaz**.

Gerçek veritabanı satın alma yazmaları için sırasıyla:

1. Şirketlerin doğrulanmış tam sicil unvanlarını, kimlik/vergisel ID'lerini
   ve mevcut kayıtların gerçek sahiplerini kayıt bazında teyit et.
2. Güncel, bağımsız şifreli PostgreSQL yedeğini al ve izole ortama geri
   yükleyerek doğrula; dört şirket eşleştirmesini orada test et.
3. 26 tablo ve tüm eski UI/CSV/rapor yollarının izolasyon tasarımını
   denetle; en az yetkili kullanıcı girişi, imzalı oturum, şirket bazlı
   DB rol izinleri ve RLS/alternatif sunucu satır güvenliği uygula.
4. Depo, müşteri, tedarikçi, ürün ve banka sahipliği ile şirket içi
   ilişkileri açıkça bağla; holding kullanıcıya otomatik erişim vermez.
5. Sipariş -> sevkiyat -> stok -> kalite -> fatura -> ödeme ilişkilerinde
   şirketler arası FK kaçışını engelleyen tek işlem/rollback ve denetim
   kayıtlarını izole PostgreSQL'de test et.
6. Sadece ayrıca onaylanan canlı migrasyon ve test edilmiş geri dönüş
   planı sonrasında kalıcı sipariş kaydı özelliğini etkinleştir.

**Bu değişiklik canlı veriye yazmaz, migrasyon içermez ve prod rollout değildir.**
