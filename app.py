
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, unquote

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Firma Bulucu", page_icon="🏭", layout="wide")

COUNTRIES = {
    "Almanya": {
        "name": "Germany",
        "terms": ["Nachfolge", "Ruhestand", "Altersnachfolge", "Firmenverkauf", "Unternehmen zu verkaufen"],
        "domains": ["nexxt-change.org", "dub.de", "deal-one.de"],
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

SECTORS = {
    "Gıda hammaddesi / Food ingredients": ["food ingredients", "Lebensmittelzutaten"],
    "Gıda katkı maddeleri": ["food additives", "Lebensmittelzusatzstoffe"],
    "Aroma / renk": ["flavour colour", "flavor color", "Aromen Farbstoffe"],
    "Emülgatör / stabilizer / hydrocolloid": ["emulsifier stabilizer hydrocolloid", "Emulgator Stabilisator Hydrokolloid"],
    "Premix / powder blending": ["premix powder blending", "dry blending", "Pulvermischung"],
    "Specialty chemicals": ["specialty chemicals", "Spezialchemikalien", "chemical blending"],
    "Pigment / coating / dye": ["pigments dyes coatings", "Pigmente Farbstoffe Beschichtungen"],
    "Detergent / cleaning chemicals": ["detergent cleaning chemicals", "Reinigungsmittel Chemie"],
    "Lubricant / industrial oils": ["lubricants industrial oils", "Schmierstoffe Industrieöle"],
    "Toll / contract manufacturing": ["toll manufacturing contract manufacturing", "Lohnherstellung Lohnmischung"],
}

STARTER = [
    {
        "Skor": 94, "Ülke": "İngiltere", "Sektör": "Specialty chemicals",
        "Başlık": "Long-Running Supplier And Distributor Of Industrial Chemicals",
        "Kaynak": "uk.businessesforsale.com", "Ciro": "£3.5m",
        "EBITDA/Kâr": "~£550k adjusted EBITDA", "Fiyat": "Undisclosed",
        "Satış nedeni": "retirement / lifestyle change", "E-posta": "", "Telefon": "",
        "Özet": "Industrial chemicals, decanting and bespoke mixtures; freehold property option.",
        "İlan / kaynak URL": "https://uk.businessesforsale.com/uk/long-running-supplier-and-distributor-of-industrial-chemicals.aspx",
        "Arama tipi": "Doğrulanmış başlangıç", "Satış ilanı": "Evet", "Üretici sinyali": "Evet",
    },
    {
        "Skor": 96, "Ülke": "İngiltere", "Sektör": "Pigment / coating / dye",
        "Başlık": "Manufacturer and supplier of dyes and pigments",
        "Kaynak": "rightbiz.co.uk", "Ciro": "£3.5m",
        "EBITDA/Kâr": "£615k adjusted EBITDA", "Fiyat": "Offers invited",
        "Satış nedeni": "retirement", "E-posta": "", "Telefon": "",
        "Özet": "Water-based dyes, pigment dispersions, coatings and toll manufacturing.",
        "İlan / kaynak URL": "https://www.rightbiz.co.uk/buy_business/for_sale/643296_undisclosed.html",
        "Arama tipi": "Doğrulanmış başlangıç", "Satış ilanı": "Evet", "Üretici sinyali": "Evet",
    },
    {
        "Skor": 90, "Ülke": "Almanya", "Sektör": "Gıda hammaddesi / Food ingredients",
        "Başlık": "Nachfolge für etabliertes Unternehmen im Lebensmittelbereich",
        "Kaynak": "dub.de", "Ciro": "€8.5m", "EBITDA/Kâr": "", "Fiyat": "",
        "Satış nedeni": "Nachfolge / Verkauf", "E-posta": "", "Telefon": "",
        "Özet": "In-house production, processing, packaging and industrial customers.",
        "İlan / kaynak URL": "https://www.dub.de/de/unternehmen-kaufen/expose/nachfolge-fuer-profitables-etabliertes-unternehmen-im-lebensmittelbereich/",
        "Arama tipi": "Doğrulanmış başlangıç", "Satış ilanı": "Evet", "Üretici sinyali": "Evet",
    },
]

EMAIL_RE = re.compile(r'[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}', re.I)
PHONE_RE = re.compile(r'(?:(?:\+\d{1,3}[\s().-]*)?(?:\d[\s().-]*){8,15})')

SALE_TERMS = [
    "business for sale", "company for sale", "offers invited", "asking price",
    "retirement", "retiring", "succession", "owner retiring",
    "nachfolge", "ruhestand", "altersnachfolge", "firmenverkauf",
    "unternehmen zu verkaufen", "kaufpreis", "verkaufsgrund",
    "bedrijf te koop", "opvolging", "pensioen",
    "entreprise à vendre", "cession entreprise", "retraite"
]

MANUFACTURING_TERMS = [
    "manufacturer", "manufacturing", "production", "producer", "factory", "plant",
    "blending", "formulation", "processing", "toll manufacturing", "contract manufacturing",
    "hersteller", "produktion", "produzent", "werk", "lohnherstellung", "lohnmischung",
    "fabricant", "production", "producent", "productie"
]

BLACKLIST_DOMAINS = {
    "wikipedia.org", "en.wikipedia.org", "fda.gov", "merriam-webster.com",
    "foodingredientsfirst.com", "creapure.com", "bareperformancenutrition.com",
    "britannica.com", "sciencedirect.com", "researchgate.net", "linkedin.com",
    "facebook.com", "instagram.com", "youtube.com"
}

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()

def get_domain(url):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""

def is_blacklisted(url):
    d = get_domain(url)
    return any(d == x or d.endswith("." + x) for x in BLACKLIST_DOMAINS)

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

def search_bing_rss(query, max_results):
    out = []
    r = safe_get("https://www.bing.com/search", params={"q": query, "format": "rss", "count": max_results})
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
                    "_provider": "Bing RSS"
                })
    except Exception:
        pass
    return out

def ddg_final_url(href):
    try:
        if "duckduckgo.com/l/?" in href:
            q = parse_qs(urlparse(href).query)
            if "uddg" in q:
                return unquote(q["uddg"][0])
    except Exception:
        pass
    return href

def search_ddg_html(query, max_results):
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
                    "_provider": "DuckDuckGo HTML"
                })
            if len(out) >= max_results:
                break
    except Exception:
        pass
    return out

def live_search(query, max_results):
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

def fetch_page(url):
    r = safe_get(url, timeout=8)
    if r is None or r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
        return "", "", ""
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = clean(soup.get_text(" ", strip=True))
        emails = "; ".join(sorted(set(EMAIL_RE.findall(text)))[:5])
        phones = []
        for value in PHONE_RE.findall(text):
            digits = re.sub(r"\D", "", value)
            if 9 <= len(digits) <= 15:
                phones.append(clean(value))
        return text[:50000], emails, "; ".join(list(dict.fromkeys(phones))[:3])
    except Exception:
        return "", "", ""

def contains_any(text, terms):
    low = text.lower()
    return any(term.lower() in low for term in terms)

def is_preferred_domain(url, country):
    d = get_domain(url)
    return any(d == x or d.endswith("." + x) for x in COUNTRIES[country]["domains"])

def candidate_ok(title, snippet, body, url, country):
    text = f"{title} {snippet} {body[:10000]}"
    sale = contains_any(text, SALE_TERMS)
    maker = contains_any(text, MANUFACTURING_TERMS)
    preferred = is_preferred_domain(url, country)

    # Preferred M&A marketplaces need a sale signal OR a strong manufacturer signal.
    if preferred:
        return sale or maker, sale, maker

    # All other sites must clearly look like BOTH a sale and a manufacturer.
    return sale and maker, sale, maker

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

def extract_reason(text):
    low = text.lower()
    for word in [
        "retirement", "retiring", "ruhestand", "altersbedingt", "altersnachfolge",
        "pensioen", "retraite", "succession", "nachfolge"
    ]:
        if word in low:
            return word
    return ""

def calc_score(title, snippet, body, url, country, sector):
    text = f"{title} {snippet} {body[:10000]}".lower()
    score = 0

    if is_preferred_domain(url, country):
        score += 30
    if contains_any(text, SALE_TERMS):
        score += 30
    if contains_any(text, MANUFACTURING_TERMS):
        score += 25

    sector_hits = 0
    for phrase in SECTORS[sector]:
        for word in phrase.lower().split():
            if len(word) > 4 and word in text:
                sector_hits += 1
    score += min(15, sector_hits * 3)

    if any(x in text for x in ["restaurant", "takeaway", "cafe for sale", "franchise"]):
        score -= 40

    return max(0, min(100, score))

def build_queries(country, sector):
    c = COUNTRIES[country]
    s = SECTORS[sector][0]

    # First: highly targeted M&A marketplace queries
    q = []
    for domain in c["domains"]:
        q.append(f'site:{domain} "{s}"')
        q.append(f'site:{domain} "{c["terms"][0]}" "{s}"')

    # Then: generic, but with explicit sale + manufacturing intent
    q.append(f'"{s}" "{c["terms"][0]}" manufacturer {c["name"]}')
    q.append(f'"{s}" "{c["terms"][1]}" manufacturer {c["name"]}')
    q.append(f'"{s}" "business for sale" manufacturer {c["name"]}')
    return list(dict.fromkeys(q))

def starter_rows(countries, sectors):
    out = []
    for row in STARTER:
        if row["Ülke"] in countries and row["Sektör"] in sectors:
            out.append(row.copy())
    return out

def scan(countries, sectors, per_query, deep_scan):
    rows = starter_rows(countries, sectors)
    seen = {r["İlan / kaynak URL"] for r in rows}
    jobs = [(c, s, q) for c in countries for s in sectors for q in build_queries(c, s)]
    progress = st.progress(0)
    status = st.empty()

    for i, (country, sector, query) in enumerate(jobs, start=1):
        status.write(f"Canlı arama: **{country} · {sector}**")
        results = live_search(query, per_query)

        for item in results:
            url = item.get("href", "")
            if not url or url in seen or is_blacklisted(url):
                continue

            title = clean(item.get("title", ""))
            snippet = clean(item.get("body", ""))
            body = email = phone = ""

            # First do a cheap title/snippet filter.
            cheap_ok, cheap_sale, cheap_maker = candidate_ok(title, snippet, "", url, country)

            # On preferred M&A domains we can inspect the page even if snippet is weak.
            if deep_scan and (cheap_ok or is_preferred_domain(url, country)):
                body, email, phone = fetch_page(url)
                time.sleep(0.05)

            ok, sale, maker = candidate_ok(title, snippet, body, url, country)
            if not ok:
                continue

            seen.add(url)
            fulltext = f"{title} {snippet} {body}"
            turnover = money(fulltext, [r"turnover", r"revenue", r"umsatz", r"omzet", r"chiffre d['’]affaires"])
            ebitda = money(fulltext, [r"adjusted EBITDA", r"EBITDA", r"operating profit", r"profit", r"gewinn", r"winst"])
            price = money(fulltext, [r"asking price", r"price", r"kaufpreis", r"vraagprijs", r"prix"])

            rows.append({
                "Skor": calc_score(title, snippet, body, url, country, sector),
                "Ülke": country,
                "Sektör": sector,
                "Başlık": title,
                "Kaynak": get_domain(url),
                "Ciro": turnover,
                "EBITDA/Kâr": ebitda,
                "Fiyat": price,
                "Satış nedeni": extract_reason(fulltext),
                "Satış ilanı": "Evet" if sale else "Belirsiz",
                "Üretici sinyali": "Evet" if maker else "Belirsiz",
                "E-posta": email,
                "Telefon": phone,
                "Özet": snippet[:550],
                "İlan / kaynak URL": url,
                "Arama tipi": item.get("_provider", "Canlı arama"),
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

st.title("🏭 Firma Bulucu")
st.caption("AS İleri / AS Food · Gerçek satılık üretici / halefiyet fırsatlarını filtreleyen sürüm")

with st.sidebar:
    countries = st.multiselect("Ülkeler", list(COUNTRIES), default=["Almanya", "İngiltere"])
    sectors = st.multiselect(
        "Sektörler",
        list(SECTORS),
        default=["Gıda hammaddesi / Food ingredients", "Gıda katkı maddeleri", "Specialty chemicals"],
    )
    per_query = st.slider("Her sorguda sonuç", 3, 10, 5)
    deep_scan = st.checkbox("İlan sayfasını açıp finansal/iletişim bilgisi çıkarmaya çalış", value=True)

tab1, tab2, tab3 = st.tabs(["🔎 Tara", "📊 Sonuçlar", "✉️ İlk temas"])

with tab1:
    st.info(
        "Bu sürüm bilgi sitelerini, Wikipedia/FDA/haber sayfalarını ve satış niyeti taşımayan sonuçları otomatik eler. "
        "Öncelik M&A / business-for-sale platformlarıdır."
    )
    if st.button("ŞİMDİ TARA", type="primary", use_container_width=True):
        if not countries or not sectors:
            st.error("En az bir ülke ve sektör seçin.")
        else:
            df = scan(countries, sectors, per_query, deep_scan)
            st.session_state["results"] = df
            if df.empty:
                st.warning("Sıkı filtrelerden geçen aday bulunamadı.")
            else:
                st.success(f"{len(df)} ciddi aday bulundu. Sonuçlar sekmesine geçin.")

with tab2:
    df = st.session_state.get("results", pd.DataFrame())
    if df.empty:
        st.info("Önce Tara sekmesinden arama yapın.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            min_score = st.slider("Minimum skor", 50, 100, 70)
        with c2:
            only_sale = st.checkbox("Satış ilanı sinyali zorunlu", value=True)
        with c3:
            only_maker = st.checkbox("Üretici sinyali zorunlu", value=True)

        view = df.copy()
        view = view[view["Skor"] >= min_score]
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
                "İlan / kaynak URL": st.column_config.LinkColumn("İlan / kaynak URL", display_text="Aç"),
                "Skor": st.column_config.ProgressColumn("Skor", min_value=0, max_value=100),
            },
        )

        st.download_button(
            "CSV indir",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name="Firma_Bulucu_Ciddi_Adaylar.csv",
            mime="text/csv",
            use_container_width=True,
        )

with tab3:
    st.text_input(
        "Konu",
        value="Acquisition / Succession Opportunity – Request for NDA and Information Memorandum",
    )
    st.text_area(
        "Mail",
        value="""Dear Sir/Madam,

We are an established food ingredients and raw materials importer and distributor with operations in the United Kingdom and Türkiye. We are currently evaluating strategic acquisition opportunities in Europe, particularly established manufacturing businesses whose owners are considering retirement, succession or a full/partial exit.

We would be pleased to sign an NDA and receive the Information Memorandum, including recent financials, normalized EBITDA, customer and supplier concentration, working-capital requirements, net debt, production capacity, property status, certifications, regulatory matters and the seller's valuation expectations.

We are also open to structured transactions, including deferred consideration, seller financing or an earn-out where appropriate.

Kind regards,
Serkan Yazıcıoğlu
AS Food Global Limited / AS İleri Gıda""",
        height=420,
    )

st.caption("Bilinmeyen veriyi uydurmaz. Kamuya açık sayfaları kullanır; CAPTCHA veya giriş engellerini aşmaz.")
