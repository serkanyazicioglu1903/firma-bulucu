
import re
import time
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, unquote, urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="AS İleri Firma & Ürün Bulucu", page_icon="🏭", layout="wide")

# =========================================================
# ORTAK AYARLAR
# =========================================================

EMAIL_RE = re.compile(r'[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}', re.I)
PHONE_RE = re.compile(r'(?:(?:\+\d{1,3}[\s().-]*)?(?:\d[\s().-]*){8,15})')

MARKETPLACE_BLACKLIST = {
    "alibaba.com", "made-in-china.com", "indiamart.com", "tradekey.com",
    "globalsources.com", "ec21.com", "go4worldbusiness.com", "exporthub.com",
    "amazon.com", "ebay.com", "wikipedia.org", "en.wikipedia.org",
    "fda.gov", "merriam-webster.com", "britannica.com", "researchgate.net",
    "sciencedirect.com", "linkedin.com", "facebook.com", "instagram.com",
    "youtube.com", "foodingredientsfirst.com"
    , "healthline.com", "webmd.com", "health.com", "medicalnewstoday.com",
    "thenutritioninsider.com", "scienceinsights.org", "drugs.com", "verywellhealth.com"
}

def product_aliases(product):
    key = clean(product).lower()
    aliases = {
        "dekstroz": "dextrose", "dekstrose": "dextrose", "dextrose": "dextrose",
        "dekstroz monohidrat": "dextrose monohydrate",
        "dextrose monohydrate": "dextrose monohydrate",
    }
    value = aliases.get(key, key)
    return [value, "monohydrate dextrose"] if value == "dextrose monohydrate" else [value]

# Manually researched official sources, not fabricated live search results.
# Kept separate from automated candidates and dated visibly in the UI.
VERIFIED_DEXTROSE = [
    ("Gulshan Polyols Limited", "Hindistan", "https://www.gulshanindia.com/dextrose_monohydrate.html",
     "https://www.gulshanindia.com/manufacturing_unit.html",
     "Muzaffarnagar tesisinde pirinçten dekstroz monohidrat üretimi açıklanıyor."),
    ("The Sukhjit Starch & Chemicals Limited", "Hindistan", "https://www.sukhjitgroup.com/monohydrate-dextrose",
     "https://www.sukhjitgroup.com/company-profile",
     "Resmî şirket profili dört üretim konumunu ve monohidrat dekstroz üretimini belirtiyor."),
    ("Sanstar Limited", "Hindistan", "https://sanstar.in/product/dextrose-monohydrate/",
     "https://sanstar.in/about-us/",
     "Resmî şirket sayfası iki üretim tesisini ve dekstroz monohidrat ürününü açıklıyor."),
]

def editorial_result(title, url):
    value = (title + " " + urlparse(url).path).lower()
    return bool(re.search(r"side.effects|dosage|health.benefits|what.is|why.is|/blog/|/news/|/journal/|/article", value))

def official_supplier_pages(url):
    """Read at most three company/contact links from the same public website."""
    response = safe_get(url, timeout=8)
    if response is None or response.status_code != 200:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.select("a[href]"):
        target = urljoin(url, a["href"])
        label = (a.get_text(" ", strip=True) + " " + target).lower()
        if urlparse(target).scheme not in {"http", "https"} or get_domain(target) != get_domain(url):
            continue
        if re.search(r"contact|enquiry|about|company.profile|manufacturing", label) and target not in links and target != url:
            links.append(target)
    links.sort(key=lambda x: 0 if re.search(r"contact|enquiry", x, re.I) else 1)
    return [(link, *fetch_page(link)) for link in links[:3]]

MANUFACTURING_TERMS = [
    "manufacturer", "manufacturing", "manufacture", "producer", "production",
    "factory", "plant", "we produce", "we manufacture", "our production",
    "hersteller", "produktion", "produzent", "werk", "wir produzieren",
    "fabricant", "production", "nous fabriquons", "producent", "productie",
    "blending", "formulation", "toll manufacturing", "contract manufacturing",
    "private label", "oem"
]

SALES_CONTACT_HINTS = [
    "export", "sales", "commercial", "business development", "international",
    "global", "distributor", "distribution", "marketing"
]

TRADER_HINTS = [
    "trading company", "trader", "wholesaler only", "marketplace",
    "broker", "agent only", "reseller"
]

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()

def get_domain(url):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def is_blacklisted(url):
    d = get_domain(url)
    return any(d == x or d.endswith("." + x) for x in MARKETPLACE_BLACKLIST)

def safe_get(url, params=None, timeout=10):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
        )
    }
    try:
        return requests.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception:
        return None

def search_bing_rss(query, max_results=8):
    out = []
    r = safe_get(
        "https://www.bing.com/search",
        params={"q": query, "format": "rss", "count": max_results},
    )
    if r is None or r.status_code >= 400:
        return out
    try:
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:max_results]:
            link = clean(item.findtext("link"))
            if link:
                out.append({
                    "title": clean(item.findtext("title")),
                    "href": link,
                    "body": clean(item.findtext("description")),
                    "_provider": "Bing RSS",
                })
    except Exception:
        pass
    return out

def ddg_final_url(href):
    if href.startswith("//"):
        href = "https:" + href
    try:
        if "duckduckgo.com/l/?" in href:
            q = parse_qs(urlparse(href).query)
            if "uddg" in q:
                return unquote(q["uddg"][0])
    except Exception:
        pass
    return href

def search_ddg_html(query, max_results=8):
    out = []
    r = safe_get("https://html.duckduckgo.com/html/", params={"q": query})
    if r is None or r.status_code >= 400:
        return out
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for block in soup.select(".result"):
            a = block.select_one(".result__a")
            if not a:
                continue
            href = ddg_final_url(a.get("href", ""))
            snippet = block.select_one(".result__snippet")
            if href:
                out.append({
                    "title": clean(a.get_text(" ", strip=True)),
                    "href": href,
                    "body": clean(snippet.get_text(" ", strip=True) if snippet else ""),
                    "_provider": "DuckDuckGo HTML",
                })
            if len(out) >= max_results:
                break
    except Exception:
        pass
    return out

def live_search(query, max_results=8):
    merged, seen = [], set()
    for fn in (search_bing_rss, search_ddg_html):
        try:
            results = fn(query, max_results)
        except Exception:
            results = []
        for item in results:
            url = item.get("href", "")
            if not url or url in seen or is_blacklisted(url):
                continue
            seen.add(url)
            merged.append(item)
        if len(merged) >= max_results:
            break
    return merged[:max_results]

def fetch_page(url, timeout=8):
    r = safe_get(url, timeout=timeout)
    if r is None or r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
        return "", "", ""
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = clean(soup.get_text(" ", strip=True))
        emails = sorted(set(EMAIL_RE.findall(text)))
        phones = []
        for value in PHONE_RE.findall(text):
            digits = re.sub(r"\D", "", value)
            if 9 <= len(digits) <= 15:
                phones.append(clean(value))
        return text[:60000], "; ".join(emails[:8]), "; ".join(list(dict.fromkeys(phones))[:4])
    except Exception:
        return "", "", ""

def choose_sales_email(email_blob):
    emails = [x.strip() for x in email_blob.split(";") if x.strip()]
    if not emails:
        return ""
    scored = []
    for e in emails:
        low = e.lower()
        local_part = low.split("@", 1)[0]
        if any(k in local_part for k in ["purchase", "procurement", "buying", "career", "privacy", "noreply", "no-reply"]) or local_part in {"hr", "jobs", "legal"}:
            continue
        score = 0
        if any(k in low for k in ["export", "sales", "commercial", "business", "international", "global"]):
            score += 10
        if any(k in low for k in ["info", "contact", "office"]):
            score += 2
        if any(k in low for k in ["purchase", "procurement", "buying", "hr", "career", "privacy"]):
            score -= 8
        scored.append((score, e))
    if not scored:
        return ""
    scored.sort(reverse=True)
    return scored[0][1]

def evidence_context(text, keywords, width=220):
    low = text.lower()
    for k in keywords:
        idx = low.find(k.lower())
        if idx >= 0:
            start = max(0, idx - width // 2)
            end = min(len(text), idx + len(k) + width // 2)
            return clean(text[start:end])
    return ""

def company_guess(title, url):
    title = clean(title)
    for sep in [" | ", " - ", " – ", " — ", ":"]:
        if sep in title:
            part = title.split(sep)[0].strip()
            if 2 <= len(part) <= 80:
                return part
    d = get_domain(url).split(".")[0]
    return d.replace("-", " ").title()

# =========================================================
# 1) FİRMA SATIN ALMA / HALEFİYET BULUCU
# =========================================================

ACQ_COUNTRIES = {
    "Almanya": {
        "name": "Germany",
        "terms": [
            "Unternehmensnachfolge", "Altersnachfolge", "Ruhestand",
            "Verkaufsangebot", "Betriebsübergabe", "Unternehmen zu verkaufen",
        ],
        "domains": [
            "nexxt-change.org", "dub.de", "viaductus.de", "concess.de",
            "businessmakler.de", "ihk.de",
        ],
    },
    "İngiltere": {
        "name": "United Kingdom",
        "terms": ["business for sale", "retirement", "owner retiring", "succession", "offers invited"],
        "domains": ["uk.businessesforsale.com", "rightbiz.co.uk", "daltonsbusiness.com", "business-sale.com"],
    },
    "Hollanda": {
        "name": "Netherlands",
        "terms": ["bedrijf te koop", "pensioen", "opvolging", "bedrijfsovername"],
        "domains": ["brookz.nl", "bedrijventekoop.nl"],
    },
    "Fransa": {
        "name": "France",
        "terms": ["entreprise à vendre", "retraite", "succession", "cession entreprise"],
        "domains": ["fusacq.com", "cessionpme.com"],
    },
}

ACQ_SECTORS = {
    "Gıda hammaddesi / Food ingredients": [
        "food ingredients", "Lebensmittelzutaten", "Lebensmittelrohstoffe",
    ],
    "Gıda katkı maddeleri": [
        "food additives", "Lebensmittelzusatzstoffe", "Zusatzstoffe Lebensmittel",
    ],
    "Aroma / renk": ["flavour colour", "flavor color", "Aromen", "Farbstoffe"],
    "Emülgatör / stabilizer / hydrocolloid": [
        "emulsifier stabilizer hydrocolloid", "Emulgatoren Stabilisatoren Hydrokolloide",
    ],
    "Premix / powder blending": ["premix powder blending", "dry blending", "Pulvermischungen"],
    "Specialty chemicals": ["specialty chemicals", "Spezialchemikalien", "chemical blending"],
    "Pigment / coating / dye": ["pigments dyes coatings"],
    "Detergent / cleaning chemicals": ["detergent cleaning chemicals"],
    "Lubricant / industrial oils": ["lubricants industrial oils"],
    "Toll / contract manufacturing": ["toll manufacturing contract manufacturing"],
}

ACQ_SALE_TERMS = [
    "business for sale", "company for sale", "offers invited", "asking price",
    "retirement", "retiring", "succession", "owner retiring",
    "nachfolge", "ruhestand", "altersnachfolge", "firmenverkauf",
    "unternehmen zu verkaufen", "kaufpreis", "verkaufsgrund",
    "bedrijf te koop", "opvolging", "pensioen",
    "entreprise à vendre", "cession entreprise", "retraite"
]

ACQ_EXCLUSION_TERMS = [
    "restaurant", "takeaway", "cafe for sale", "café", "hotel", "guest house",
    "franchise", "kiosk", "imbiss", "gastronomie", "einzelhandel", "onlineshop",
    "e-commerce store", "beauty salon", "hair salon",
]

ACQ_SOURCE_GUIDE = [
    {"Kaynak": "nexxt-change", "Bölge": "Almanya", "Tip": "Resmî halefiyet borsası", "URL": "https://www.nexxt-change.org/"},
    {"Kaynak": "DUB", "Bölge": "DACH", "Tip": "Ticari M&A ilanları", "URL": "https://www.dub.de/de/unternehmen-kaufen/"},
    {"Kaynak": "Viaductus", "Bölge": "DACH", "Tip": "Seçilmiş ilanlar / danışmanlık", "URL": "https://www.viaductus.de/"},
    {"Kaynak": "con|cess", "Bölge": "DACH", "Tip": "M&A danışman ağı", "URL": "https://www.concess.de/"},
    {"Kaynak": "BusinessMakler", "Bölge": "Almanya", "Tip": "KOBİ satış ilanları", "URL": "https://www.businessmakler.de/"},
    {"Kaynak": "IHK", "Bölge": "Almanya / bölgesel", "Tip": "Devir ve halefiyet danışmanlığı", "URL": "https://www.ihk.de/"},
]

ACQ_REVIEW_QUESTIONS = [
    ("Kârlılık istikrarlı mı?", "Son 3–5 yıl Jahresabschluss, GuV ve güncel BWA", "Tek iyi yıl; ciro artarken kârın düşmesi"),
    ("Borç ve gizli yükler açık mı?", "Kredi/leasing listesi ve Pensionszusagen", "Açıklanmayan kefalet veya yüksek emeklilik karşılığı"),
    ("Makine ve yatırımlar güncel mi?", "Anlagenverzeichnis, makine yaşları ve bakım kayıtları", "Yıllardır yatırım yapılmaması"),
    ("Şirket patrondan bağımsız çalışabiliyor mu?", "Organizasyon ve satış süreçleri", "Tüm müşteri ve teklif ilişkilerinin patronda olması"),
    ("Müşteri yoğunlaşması kabul edilebilir mi?", "Anonim müşteri bazında ciro dağılımı", "Tek müşterinin cironun %25'inden fazla olması"),
    ("İkinci kademe yönetim var mı?", "Kilit personel ve iş sözleşmeleri", "Kilit kadronun da ayrılacak veya emekli olacak olması"),
    ("Çalışan yapısı sürdürülebilir mi?", "Personel, ücret, kıdem ve Tarifvertrag bilgisi", "Yüksek yaş ortalaması ve yedek kadro olmaması"),
    ("AS İleri ile ürün ve pazar sinerjisi var mı?", "Ürün gamı, tedarikçi listesi ve teknoloji", "Yalnızca 'Alman şirketi' olduğu için alım"),
    ("Sertifika ve onaylar devredilebilir mi?", "ISO/FSSC/BRCGS, ruhsatlar ve marka tescilleri", "Onayların kişiye bağlı veya devredilemez olması"),
    ("Lokasyon ve lojistik uygun mu?", "Kira/tapu, imar, çevre izinleri ve depo bilgisi", "Kısa kira veya devir için ev sahibi onayı gereği"),
    ("Share Deal / Asset Deal riski anlaşıldı mı?", "Handelsregisterauszug, dava ve vergi incelemeleri", "Açık dava, vergi veya sosyal güvenlik borcu"),
    ("Fiyat finansallarla destekleniyor mu?", "Değerleme gerekçesi ve normalleştirilmiş EBITDA", "Gerekçesiz fiyat ve 'başka alıcı var' baskısı"),
]

ACQ_STARTER = [
    {
        "Skor": 94, "Ülke": "İngiltere", "Sektör": "Specialty chemicals",
        "Başlık": "Long-Running Supplier And Distributor Of Industrial Chemicals",
        "Kaynak": "uk.businessesforsale.com", "Ciro": "£1m–£5m",
        "EBITDA/Kâr": "", "Fiyat": "Undisclosed",
        "Satış nedeni": "", "E-posta": "", "Telefon": "",
        "Özet": "Project Hinode; established supplier and distributor of industrial chemicals. Financial and legal details require NDA.",
        "İlan / kaynak URL": "https://uk.businessesforsale.com/uk/long-running-supplier-and-distributor-of-industrial-chemicals.aspx",
        "Satış ilanı": "Evet", "Üretici sinyali": "Evet",
    },
    {
        "Skor": 96, "Ülke": "İngiltere", "Sektör": "Pigment / coating / dye",
        "Başlık": "Manufacturer and supplier of dyes and pigments",
        "Kaynak": "rightbiz.co.uk", "Ciro": "£3.5m",
        "EBITDA/Kâr": "£615k adjusted EBITDA", "Fiyat": "Offers invited",
        "Satış nedeni": "retirement", "E-posta": "", "Telefon": "",
        "Özet": "Water-based dyes, pigment dispersions, coatings and toll manufacturing.",
        "İlan / kaynak URL": "https://www.rightbiz.co.uk/buy_business/for_sale/643296_undisclosed.html",
        "Satış ilanı": "Evet", "Üretici sinyali": "Evet",
    },
]

def acq_preferred(url, country):
    d = get_domain(url)
    return any(d == x or d.endswith("." + x) for x in ACQ_COUNTRIES[country]["domains"])

def acq_build_queries(country, sector):
    c = ACQ_COUNTRIES[country]
    sector_terms = ACQ_SECTORS[sector]
    s = sector_terms[1] if country == "Almanya" and len(sector_terms) > 1 else sector_terms[0]
    q = []
    for domain in c["domains"]:
        q.append(f'site:{domain} "{c["terms"][0]}" "{s}"')
    q.append(f'"{s}" "{c["terms"][0]}" manufacturer {c["name"]}')
    q.append(f'"{s}" "{c["terms"][1]}" manufacturer {c["name"]}')
    if country != "Almanya":
        q.append(f'"{s}" "business for sale" manufacturer {c["name"]}')
    return list(dict.fromkeys(q))

def acq_candidate_ok(title, snippet, body, url, country):
    text = f"{title} {snippet} {body[:10000]}".lower()
    sale = any(x in text for x in ACQ_SALE_TERMS)
    maker = any(x in text for x in MANUFACTURING_TERMS)
    preferred = acq_preferred(url, country)
    if preferred:
        return sale or maker, sale, maker
    return sale and maker, sale, maker

def acq_score(title, snippet, body, url, country, sector):
    text = f"{title} {snippet} {body[:10000]}".lower()
    score = 0
    if acq_preferred(url, country):
        score += 30
    if any(x in text for x in ACQ_SALE_TERMS):
        score += 30
    if any(x in text for x in MANUFACTURING_TERMS):
        score += 25
    for phrase in ACQ_SECTORS[sector]:
        for word in phrase.lower().split():
            if len(word) > 4 and word in text:
                score += 3
    if any(x in text for x in ACQ_EXCLUSION_TERMS):
        score -= 40
    return max(0, min(100, score))

def money(text, labels):
    for label in labels:
        pattern = (
            rf"{label}\s*[:\-]?\s*"
            r"((?:€|£|EUR|GBP)\s?[\d.,]+\s?(?:m|mn|million|k|thousand|Mio\.?)?|"
            r"[\d.,]+\s?(?:m|mn|million|k|thousand|Mio\.?)?\s?(?:€|£|EUR|GBP))"
        )
        m = re.search(pattern, text, re.I)
        if m:
            return clean(m.group(1))
    return ""

def extract_sale_reason(text):
    low = text.lower()
    for word in ["retirement", "retiring", "ruhestand", "altersbedingt", "altersnachfolge",
                 "pensioen", "retraite", "succession", "nachfolge"]:
        if word in low:
            return word
    return ""

def acq_scan(countries, sectors, per_query, deep_scan):
    started_at = time.monotonic()
    rows = [r.copy() for r in ACQ_STARTER if r["Ülke"] in countries and r["Sektör"] in sectors]
    seen = {r["İlan / kaynak URL"] for r in rows}
    jobs = [(c, s, q) for c in countries for s in sectors for q in acq_build_queries(c, s)]
    progress = st.progress(0)
    status = st.empty()

    for i, (country, sector, query) in enumerate(jobs, start=1):
        if time.monotonic() - started_at > 120:
            st.warning("Tarama süre sınırına ulaştı. O ana kadar bulunan adaylar gösteriliyor.")
            break
        status.write(f"Canlı arama: **{country} · {sector}**")
        for item in live_search(query, per_query):
            url = item.get("href", "")
            if not url or url in seen or is_blacklisted(url):
                continue

            title = clean(item.get("title", ""))
            snippet = clean(item.get("body", ""))
            body = email = phone = ""

            cheap_ok, _, _ = acq_candidate_ok(title, snippet, "", url, country)
            if deep_scan and (cheap_ok or acq_preferred(url, country)):
                body, email, phone = fetch_page(url)
                time.sleep(0.03)

            ok, sale, maker = acq_candidate_ok(title, snippet, body, url, country)
            if not ok:
                continue

            seen.add(url)
            text = f"{title} {snippet} {body}"
            rows.append({
                "Skor": acq_score(title, snippet, body, url, country, sector),
                "Ülke": country,
                "Sektör": sector,
                "Başlık": title,
                "Kaynak": get_domain(url),
                "Ciro": money(text, [r"turnover", r"revenue", r"umsatz", r"omzet", r"chiffre d['’]affaires"]),
                "EBITDA/Kâr": money(text, [r"adjusted EBITDA", r"EBITDA", r"operating profit", r"profit", r"gewinn"]),
                "Fiyat": money(text, [r"asking price", r"price", r"kaufpreis", r"vraagprijs", r"prix"]),
                "Satış nedeni": extract_sale_reason(text),
                "Satış ilanı": "Evet" if sale else "Belirsiz",
                "Üretici sinyali": "Evet" if maker else "Belirsiz",
                "E-posta": choose_sales_email(email),
                "Telefon": phone,
                "Özet": snippet[:500],
                "İlan / kaynak URL": url,
            })
        progress.progress(i / max(len(jobs), 1))

    progress.empty()
    status.empty()

    df = pd.DataFrame(rows)
    if not df.empty:
        df = (
            df.drop_duplicates(subset=["İlan / kaynak URL"])
              .sort_values(["Skor", "Ülke"], ascending=[False, True])
              .reset_index(drop=True)
        )
    return df

def german_acquisition_email(listing_title, listing_url):
    return f"""Betreff: Interesse an einer Unternehmensnachfolge – {listing_title}

Sehr geehrte Damen und Herren,

mit großem Interesse haben wir Ihr Verkaufsangebot „{listing_title}“ gelesen.

Wir sind mit AS İleri Gıda und AS Food Global Limited seit mehr als 25 Jahren im Import und Vertrieb von Lebensmittelzutaten und industriellen Rohstoffen tätig. Wir beliefern führende Lebensmittelhersteller in der Türkei und verfügen über eine Gesellschaft im Vereinigten Königreich.

Im Rahmen unserer europäischen Expansion suchen wir ein etabliertes Unternehmen, das wir langfristig fortführen und weiterentwickeln können. Der Erhalt des Standorts, der Belegschaft und der bestehenden Kundenbeziehungen ist für uns von besonderer Bedeutung.

Gerne unterzeichnen wir eine Vertraulichkeitsvereinbarung. Bitte senden Sie uns anschließend das Exposé sowie Informationen zu Kaufpreisvorstellung, Transaktionsstruktur, Umsatz, bereinigtem EBITDA, Mitarbeitern, Kunden- und Lieferantenstruktur und Verkaufsgrund.

Inserat: {listing_url}

Mit freundlichen Grüßen

Serkan Yazıcıoğlu
Managing Director
AS Food Global Limited / AS İleri Gıda
E-Mail: importstarch@outlook.com"""

# =========================================================
# 2) ÜRÜN / HAMMADDE / ÜRETİCİ / TEMSİLCİLİK BULUCU
# =========================================================

SOURCE_COUNTRIES = [
    "Dünya geneli", "Almanya", "İngiltere", "Hollanda", "Fransa", "İtalya",
    "İspanya", "Polonya", "Belçika", "Avusturya", "İsviçre", "ABD", "Kanada",
    "Çin", "Hindistan", "Tayland", "Malezya", "Endonezya", "Vietnam",
    "Japonya", "Güney Kore", "Brezilya", "Arjantin"
]

COUNTRY_MAP = {
    "Dünya geneli": "",
    "Almanya": "Germany", "İngiltere": "United Kingdom", "Hollanda": "Netherlands",
    "Fransa": "France", "İtalya": "Italy", "İspanya": "Spain", "Polonya": "Poland",
    "Belçika": "Belgium", "Avusturya": "Austria", "İsviçre": "Switzerland",
    "ABD": "USA", "Kanada": "Canada", "Çin": "China", "Hindistan": "India",
    "Tayland": "Thailand", "Malezya": "Malaysia", "Endonezya": "Indonesia",
    "Vietnam": "Vietnam", "Japonya": "Japan", "Güney Kore": "South Korea",
    "Brezilya": "Brazil", "Arjantin": "Argentina"
}

def supplier_queries(product, country_label, objective):
    product = product_aliases(product)[0]
    country = COUNTRY_MAP.get(country_label, "")
    c = f" {country}" if country else ""

    q = [
        f'"{product}" manufacturer{c}',
        f'"{product}" producer factory{c}',
        f'"{product}" manufacturing company{c}',
        f'"{product}" export sales manufacturer{c}',
    ]

    if "Distribütörlük / temsilcilik" in objective:
        q += [
            f'"{product}" manufacturer distributor wanted{c}',
            f'"{product}" manufacturer distribution partners{c}',
            f'"{product}" become distributor manufacturer{c}',
        ]

    if "Private label / fason üretim" in objective:
        q += [
            f'"{product}" contract manufacturer{c}',
            f'"{product}" private label manufacturer{c}',
            f'"{product}" toll manufacturing{c}',
        ]

    return list(dict.fromkeys(q))

def supplier_manufacturer_status(product, title, snippet, body, url):
    # Search titles/snippets are never evidence. Require fetched page content,
    # a product page and an explicit company manufacturing claim.
    text = body.lower()
    if is_blacklisted(url) or editorial_result(title, url) or not text:
        return "unclear", 0
    product_hit = any(re.search(r"\b" + re.escape(alias) + r"\b", text) for alias in product_aliases(product))
    product_page = any(alias in (title + " " + urlparse(url).path.replace("-", " ").replace("_", " ")).lower() for alias in product_aliases(product))
    maker_hit = bool(re.search(r"\bwe\s+(?:manufacture|produce)\b|\bour\s+(?:factory|factories|manufacturing|production facilities)\b|\b(?:company|group)\s+manufactures\b", text))
    trader_hit = any(x in text for x in TRADER_HINTS)
    if product_hit and product_page and maker_hit and not trader_hit:
        return "likely", 20
    return "unclear", 0

def turkey_presence_check(company, product):
    queries = [
        f'"{company}" Turkey distributor',
        f'"{company}" Türkiye distributor',
        f'"{company}" Turkey {product}',
    ]
    hits = []
    for q in queries[:2]:
        for r in live_search(q, 3):
            snippet = clean(r.get("body", ""))
            title = clean(r.get("title", ""))
            text = f"{title} {snippet}".lower()
            if "turkey" in text or "türkiye" in text or "turkish" in text:
                hits.append(f"Doğrulanması gereken arama bulgusu: {title} — {snippet[:180]} | {r.get('href', '')}")
                break
        if hits:
            break
    return hits[0] if hits else ""

def supplier_score(status, email, turkey_presence, text, objective):
    score = 0
    if status == "confirmed":
        score += 45
    elif status == "likely":
        score += 30
    else:
        score += 10

    if email:
        score += 15

    low = text.lower()
    if any(x in low for x in ["export", "international sales", "global sales", "business development"]):
        score += 10
    if "Distribütörlük / temsilcilik" in objective and any(
        x in low for x in ["distributor", "distribution partner", "become a distributor", "agents"]
    ):
        score += 15
    if "Private label / fason üretim" in objective and any(
        x in low for x in ["private label", "contract manufacturing", "toll manufacturing", "oem"]
    ):
        score += 15

    return max(0, min(100, score))

def make_intro_email(product, company, objective, sender_email):
    objective_line = ""
    if "Distribütörlük / temsilcilik" in objective:
        objective_line = (
            "We are also interested in discussing a potential distribution / representation "
            "partnership for Türkiye, subject to product and commercial fit."
        )
    elif "Private label / fason üretim" in objective:
        objective_line = (
            "We would also be interested in discussing contract manufacturing / private-label "
            "possibilities where relevant."
        )

    return f"""Dear Sales / Export Team,

My name is Serkan Yazıcıoğlu, representing AS İleri Gıda / AS Food Global Limited.

We are an established importer and distributor of food ingredients and industrial raw materials, supplying major manufacturers in Türkiye and working with international suppliers.

We are currently evaluating suppliers for {product} and would like to learn more about {company}'s manufacturing capabilities and export terms.

Could you please share:
• Product specification / TDS and SDS where applicable
• Available grades and packaging
• MOQ
• Export price and Incoterm
• Production lead time
• Certifications and country of origin
• Current distribution / representation status in Türkiye
• Sample availability

{objective_line}

Please reply to: {sender_email}

Kind regards,
Serkan Yazıcıoğlu
AS İleri Gıda / AS Food Global Limited"""

def supplier_scan(product, country_label, objective, max_companies, deep_scan, turkey_check):
    started_at = time.monotonic()
    queries = supplier_queries(product, country_label, objective)
    seen_domains = set()
    rows = []
    aliases = product_aliases(product)
    if any(a in {"dextrose", "dextrose monohydrate", "monohydrate dextrose"} for a in aliases):
        for name, country, product_url, factory_url, evidence in VERIFIED_DEXTROSE:
            if country_label not in {"Dünya geneli", country}:
                continue
            seen_domains.add(get_domain(product_url))
            rows.append({
                "Fit Score": 45, "Firma": name, "Hedef Pazar": country_label,
                "Üretici Ülkesi": country, "Website": "https://" + get_domain(product_url),
                "Manufacturer Status": "confirmed", "Üretim Kanıtı": evidence,
                "Üretim Kaynak URL": factory_url, "Kaynak URL": product_url,
                "Kayıt Türü": "Resmî kaynaklardan araştırılmış başlangıç kaydı · 06.10.2026",
                "Türkiye Varlığı": "Kontrol edilmedi; temsilcilik durumu bilinmiyor.",
                "Satış / Export E-mail": "", "Telefon": "", "İletişim URL": "",
                "Arama Özeti": "Ürün: Dextrose Monohydrate. Bu kayıt canlı arama sonucu değildir.",
                "Taslak Konu": "Dextrose Monohydrate inquiry – Türkiye",
                "Taslak E-mail": make_intro_email("Dextrose Monohydrate", name, objective, st.session_state.get("sender_email", "importstarch@outlook.com")),
            })
    progress = st.progress(0)
    status = st.empty()

    all_candidates = []
    for i, q in enumerate(queries, start=1):
        if time.monotonic() - started_at > 60:
            break
        status.write(f"Aranıyor: **{product}** · `{q}`")
        results = live_search(q, max(6, min(12, max_companies)))
        for item in results:
            url = item.get("href", "")
            d = get_domain(url)
            if not url or not d or d in seen_domains or is_blacklisted(url) or editorial_result(item.get("title", ""), url):
                continue
            all_candidates.append(item)
        progress.progress(i / max(len(queries), 1))

    # Analyze only a manageable number of unique official-looking domains.
    for idx, item in enumerate(all_candidates[: max_companies * 3]):
        if time.monotonic() - started_at > 120:
            st.warning("Canlı tarama süre sınırına ulaştı. Toplanan sonuçlar gösteriliyor; tüm adaylar incelenemedi.")
            break
        if len(rows) >= max_companies:
            break

        url = item.get("href", "")
        if get_domain(url) in seen_domains:
            continue
        title = clean(item.get("title", ""))
        snippet = clean(item.get("body", ""))
        body = email_blob = phone = ""

        if deep_scan:
            body, email_blob, phone = fetch_page(url)
        pages = official_supplier_pages(url) if body else []
        supporting_body = body + " " + " ".join(p[1] for p in pages)
        email_blob += ";" + ";".join(p[2] for p in pages)

        status_value, base_score = supplier_manufacturer_status(product, title, snippet, supporting_body, url)

        # Exclude traders and candidates without a product/manufacturing signal.
        if status_value == "unclear":
            continue

        # A domain label is honest when the legal company name is not verified.
        company = get_domain(url)
        seen_domains.add(get_domain(url))
        sales_email = choose_sales_email(email_blob)
        turkey_presence = turkey_presence_check(company, product) if turkey_check else ""
        text = f"{title} {snippet} {body}"
        score = supplier_score(status_value, sales_email, turkey_presence, text, objective)

        evidence = evidence_context(
            supporting_body,
            ["we manufacture", "we produce", "our factory", "our factories", "our manufacturing", "our production facilities", "company manufactures", "group manufactures"],
            width=260,
        )

        rows.append({
            "Fit Score": score,
            "Firma": company,
            "Hedef Pazar": country_label,
            "Üretici Ülkesi": "",
            "Website": f"https://{get_domain(url)}" if get_domain(url) else url,
            "Manufacturer Status": status_value,
            "Üretim Kanıtı": evidence,
            "Üretim Kaynak URL": next((p[0] for p in pages if any(t in p[1].lower() for t in ["we manufacture", "we produce", "our factory", "our manufacturing", "company manufactures"])), url),
            "Kayıt Türü": "Canlı arama adayı · şirket adı ve üretim teyidi bekleniyor",
            "İletişim URL": next((p[0] for p in pages if re.search(r"contact|enquiry", p[0], re.I)), ""),
            "Türkiye Varlığı": turkey_presence or ("Doğrulanamadı; temsilcisi olmadığı anlamına gelmez." if turkey_check else "Kontrol edilmedi"),
            "Satış / Export E-mail": sales_email,
            "Telefon": phone,
            "Kaynak URL": url,
            "Arama Özeti": snippet[:420],
            "Taslak Konu": f"Inquiry for {product} – Türkiye",
            "Taslak E-mail": make_intro_email(
                product,
                company,
                objective,
                st.session_state.get("sender_email", "importstarch@outlook.com"),
            ),
        })

    progress.empty()
    status.empty()

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Fit Score", ascending=False).reset_index(drop=True)
    st.session_state["supplier_diagnostics"] = {
        "Arama sorgusu": len(queries),
        "İncelenecek bağlantı": len(all_candidates),
        "Önceden araştırılmış kayıt": sum(r.get("Manufacturer Status") == "confirmed" for r in rows),
        "Canlı üretici adayı": sum(r.get("Manufacturer Status") == "likely" for r in rows),
    }
    return df

# =========================================================
# UI
# =========================================================

st.title("🏭 AS İleri – Firma & Ürün Bulucu")
st.caption("Şirket satın alma + yeni ürün / hammadde / üretici / distribütörlük araştırması tek uygulamada")

main_tab1, main_tab2 = st.tabs([
    "🏢 Firma Satın Alma / Halefiyet",
    "🧪 Satın Alma / Üretici Bulucu",
])

# -------------------------
# TAB 1: ACQUISITION
# -------------------------
with main_tab1:
    st.subheader("Satılık firma / halefiyet araştırması")
    st.info(
        "Almanya için gıda hammaddesi, katkı maddeleri ve B2B özel kimyasal şirketlerini arar. "
        "Restoran, kafe, perakende, franchise ve pazar yeri sonuçlarını eler."
    )

    with st.expander("Almanya kaynakları ve arama yöntemi"):
        st.dataframe(
            pd.DataFrame(ACQ_SOURCE_GUIDE),
            use_container_width=True,
            hide_index=True,
            column_config={"URL": st.column_config.LinkColumn("Kaynak", display_text="Aç")},
        )
        st.caption(
            "Platform ilanları başlangıç noktasıdır. Uygun adaylar için IHK, banka, Steuerberater "
            "ve M&A danışmanı üzerinden ilan dışı (off-market) arama da yapılmalıdır."
        )

    c1, c2 = st.columns([1, 2])
    with c1:
        acq_countries = st.multiselect(
            "Ülkeler",
            list(ACQ_COUNTRIES),
            default=["Almanya", "İngiltere"],
            key="acq_countries",
        )
    with c2:
        acq_sectors = st.multiselect(
            "Sektörler",
            list(ACQ_SECTORS),
            default=["Gıda hammaddesi / Food ingredients", "Gıda katkı maddeleri", "Specialty chemicals"],
            key="acq_sectors",
        )

    col_a, col_b = st.columns(2)
    with col_a:
        acq_per_query = st.slider("Her sorguda sonuç", 3, 10, 5, key="acq_per_query")
    with col_b:
        acq_deep = st.checkbox("İlan sayfasını açıp finansal/iletişim bilgisi çıkar", value=True, key="acq_deep")

    if st.button("SATILIK FİRMA TARA", type="primary", use_container_width=True):
        if not acq_countries or not acq_sectors:
            st.error("En az bir ülke ve sektör seçin.")
        else:
            st.session_state["acq_results"] = acq_scan(acq_countries, acq_sectors, acq_per_query, acq_deep)
            if st.session_state["acq_results"].empty:
                st.warning("Sıkı filtrelerden geçen aday bulunamadı.")
            else:
                st.success(f"{len(st.session_state['acq_results'])} aday bulundu.")

    acq_df = st.session_state.get("acq_results", pd.DataFrame())
    if not acq_df.empty:
        f1, f2, f3 = st.columns(3)
        with f1:
            min_score = st.slider("Minimum skor", 50, 100, 70, key="acq_min_score")
        with f2:
            only_sale = st.checkbox("Satış ilanı zorunlu", value=True, key="acq_sale")
        with f3:
            only_maker = st.checkbox("Üretici sinyali zorunlu", value=True, key="acq_maker")

        view = acq_df[acq_df["Skor"] >= min_score].copy()
        if only_sale:
            view = view[view["Satış ilanı"] == "Evet"]
        if only_maker:
            view = view[view["Üretici sinyali"] == "Evet"]

        st.metric("Gösterilen ciddi aday", len(view))
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "İlan / kaynak URL": st.column_config.LinkColumn("İlan", display_text="Aç"),
                "Skor": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100),
            },
        )
        st.download_button(
            "Satılık firma sonuçlarını CSV indir",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name="Satilik_Firma_Adaylari.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.divider()
        st.subheader("Seçilen firma için 12 soruluk ön değerlendirme")
        if view.empty:
            st.warning("Mevcut filtrelerle değerlendirilecek aday kalmadı. Minimum skoru düşürün.")
        else:
            selected_idx = st.selectbox(
                "Değerlendirilecek firma / ilan",
                options=view.index.tolist(),
                format_func=lambda idx: f"{view.loc[idx, 'Başlık']} · {view.loc[idx, 'Ülke']}",
                key="acq_review_candidate",
            )
            selected = view.loc[selected_idx]
            answers = []
            with st.expander("12 soruyu puanla: 0 = olumsuz/bilinmiyor, 1 = kısmen, 2 = olumlu", expanded=True):
                for number, (question, document, red_flag) in enumerate(ACQ_REVIEW_QUESTIONS, start=1):
                    left, right = st.columns([3, 1])
                    with left:
                        st.markdown(f"**{number}. {question}**")
                        st.caption(f"İstenecek belge: {document}  ·  Kırmızı bayrak: {red_flag}")
                    with right:
                        value = st.select_slider(
                            "Puan",
                            options=[0, 1, 2],
                            value=0,
                            key=f"acq_review_{selected_idx}_{number}",
                            label_visibility="collapsed",
                        )
                    answers.append(value)

            review_score = sum(answers)
            if review_score >= 18:
                review_result = "CİDDİ ADAY — LOI ve due diligence aşamasına geçilebilir."
                st.success(f"{review_score}/24 · {review_result}")
            elif review_score >= 12:
                review_result = "DİKKATLİ İLERLE — Zayıf noktalar fiyat ve sözleşmeye yansıtılmalı."
                st.warning(f"{review_score}/24 · {review_result}")
            else:
                review_result = "DUR — Bilgiler tamamlanmadan zaman ve inceleme maliyeti harcanmamalı."
                st.error(f"{review_score}/24 · {review_result}")

            assessment = {
                "firma_ilani": selected["Başlık"],
                "ulke": selected["Ülke"],
                "kaynak_url": selected["İlan / kaynak URL"],
                "puan": review_score,
                "sonuc": review_result,
                "cevaplar": [
                    {"soru": item[0], "puan": score, "istenecek_belge": item[1], "kirmizi_bayrak": item[2]}
                    for item, score in zip(ACQ_REVIEW_QUESTIONS, answers)
                ],
            }
            st.download_button(
                "Ön değerlendirmeyi JSON indir",
                json.dumps(assessment, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name="Firma_On_Degerlendirme.json",
                mime="application/json",
                use_container_width=True,
            )

            if selected["Ülke"] == "Almanya":
                st.subheader("Hazır Almanca ilk temas taslağı")
                email_text = german_acquisition_email(selected["Başlık"], selected["İlan / kaynak URL"])
                st.text_area("E-posta", email_text, height=430, key=f"acq_mail_{selected_idx}")
                st.download_button(
                    "Almanca e-postayı indir",
                    email_text.encode("utf-8"),
                    file_name="Almanca_Ilk_Temas.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

# -------------------------
# TAB 2: SOURCING / MANUFACTURER
# -------------------------
with main_tab2:
    st.subheader("Yeni ürün, hammadde, üretici ve temsilcilik araştırması")
    st.info("Sürüm 3 · Ücretli API kullanılmaz. Tarihli başlangıç kayıtları ile canlı arama adayları ayrı etiketlenir. Ücretsiz arama servisleri erişimi kısıtlayabilir; canlı adaylar ayrıca teyit gerektirir.")
    st.write(
        "Ürün adını yazın. Sistem üretici odaklı arama yapar, pazar yerlerini ve açık tüccar sonuçlarını eler; "
        "mümkünse resmi üretim sayfası, export/sales iletişimi ve Türkiye varlığını bulur."
    )

    q1, q2 = st.columns([2, 1])
    with q1:
        product = st.text_input(
            "Aranacak ürün / hammadde",
            placeholder="Örn: Vital Wheat Gluten, Dextrose Monohydrate, Topping Base, GMS, HPMC...",
            key="product_input",
        )
    with q2:
        source_country = st.selectbox("Hedef ülke / pazar", SOURCE_COUNTRIES, index=0, key="source_country")

    objective = st.multiselect(
        "Amaç",
        ["Hammadde satın alma", "Distribütörlük / temsilcilik", "Private label / fason üretim"],
        default=["Hammadde satın alma", "Distribütörlük / temsilcilik"],
        key="source_objective",
    )

    s1, s2, s3 = st.columns(3)
    with s1:
        max_companies = st.slider("Maksimum firma", 5, 20, 10, key="max_companies")
    with s2:
        supplier_deep = st.checkbox("Resmi siteyi açıp üretimi doğrulamaya çalış", value=True, key="supplier_deep")
    with s3:
        turkey_check = st.checkbox("Türkiye temsilci / distribütör varlığını kontrol et", value=True, key="turkey_check")

    sender_email = st.text_input(
        "Teklif isteme e-postasında dönüş adresi",
        value=st.session_state.get("sender_email", "importstarch@outlook.com"),
        key="sender_email",
    )

    if st.button("ÜRÜN / ÜRETİCİ ARA", type="primary", use_container_width=True):
        if not product.strip():
            st.error("Önce ürün veya hammadde adını yazın.")
        else:
            st.session_state["supplier_results"] = supplier_scan(
                product.strip(),
                source_country,
                objective,
                max_companies,
                supplier_deep,
                turkey_check,
            )
            if st.session_state["supplier_results"].empty:
                st.warning("Listelenecek üretici adayı bulunamadı. Bu, üretici olmadığı anlamına gelmez: arama servisine erişim, sayfa okuma veya filtreler nedeniyle sonuç alınamamış olabilir. Ürün adını İngilizce veya teknik adıyla deneyin.")
            else:
                st.success(f"{len(st.session_state['supplier_results'])} üretici adayı bulundu.")

    supplier_df = st.session_state.get("supplier_results", pd.DataFrame())
    if "supplier_diagnostics" in st.session_state:
        st.write("Arama özeti", st.session_state["supplier_diagnostics"])
        if st.session_state["supplier_diagnostics"]["Canlı üretici adayı"] == 0:
            st.warning("Canlı aramadan uygun yeni üretici adayı doğrulanamadı. Varsa aşağıdaki tarihli başlangıç kayıtları gösteriliyor; bu durum canlı aramanın başarılı olduğu anlamına gelmez.")
    if not supplier_df.empty:
        min_fit = st.slider("Minimum üretici uygunluk skoru", 0, 100, 0, key="supplier_min_fit")
        supplier_view = supplier_df[supplier_df["Fit Score"] >= min_fit].copy()

        st.metric("Gösterilen üretici adayı", len(supplier_view))
        st.dataframe(
            supplier_view.drop(columns=["Taslak E-mail"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Kaynak URL": st.column_config.LinkColumn("Kaynak", display_text="Aç"),
                "Website": st.column_config.LinkColumn("Website", display_text="Site"),
                "Üretim Kaynak URL": st.column_config.LinkColumn("Üretim kaynağı", display_text="Aç"),
                "İletişim URL": st.column_config.LinkColumn("İletişim", display_text="Aç"),
                "Fit Score": st.column_config.ProgressColumn("Fit Score", min_value=0, max_value=100),
            },
        )

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Üretici sonuçlarını CSV indir",
                supplier_view.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"Uretici_Adaylari_{re.sub(r'[^A-Za-z0-9]+','_',product)[:40]}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "Üretici sonuçlarını JSON indir",
                json.dumps(supplier_view.to_dict(orient="records"), ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"Uretici_Adaylari_{re.sub(r'[^A-Za-z0-9]+','_',product)[:40]}.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("### ✉️ Firma bazında hazır teklif / temsilcilik e-postası")
        firms = supplier_view["Firma"].tolist()
        if firms:
            selected_index = st.selectbox("Firma seç", list(range(len(supplier_view))), format_func=lambda i: supplier_view.iloc[i]["Firma"], key="supplier_mail_index")
            selected_row = supplier_view.iloc[selected_index]
            draft_key = f"{selected_row['Kaynak URL']}:{selected_row['Taslak Konu']}"
            st.text_input("Konu", value=selected_row["Taslak Konu"], key=f"subject:{draft_key}")
            st.text_area("E-posta", value=selected_row["Taslak E-mail"], height=430, key=f"body:{draft_key}")
            st.caption("Bu bir taslaktır. Program e-posta göndermez. Sonuçları saklamak için CSV veya JSON indirin; oturum verileri kalıcı kayıt değildir.")
        else:
            st.info("Seçtiğiniz minimum skoru geçen firma yok. Daha düşük bir skor seçebilirsiniz.")

st.markdown("---")
st.caption(
    "Sistem bilinmeyen veriyi uydurmaz. Kamuya açık sayfaları kullanır; CAPTCHA/giriş engellerini aşmaz. "
    "Üretici doğrulaması otomatik bir ön elemedir; sipariş veya sözleşme öncesinde resmi belge ve ticari due diligence gerekir."
)
