
import re
import time
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, unquote

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
}

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
        score = 0
        if any(k in low for k in ["export", "sales", "commercial", "business", "international", "global"]):
            score += 10
        if any(k in low for k in ["info", "contact", "office"]):
            score += 2
        if any(k in low for k in ["purchase", "procurement", "buying", "hr", "career", "privacy"]):
            score -= 8
        scored.append((score, e))
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

ACQ_SECTORS = {
    "Gıda hammaddesi / Food ingredients": ["food ingredients", "Lebensmittelzutaten"],
    "Gıda katkı maddeleri": ["food additives", "Lebensmittelzusatzstoffe"],
    "Aroma / renk": ["flavour colour", "flavor color", "Aromen Farbstoffe"],
    "Emülgatör / stabilizer / hydrocolloid": ["emulsifier stabilizer hydrocolloid"],
    "Premix / powder blending": ["premix powder blending", "dry blending"],
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

ACQ_STARTER = [
    {
        "Skor": 94, "Ülke": "İngiltere", "Sektör": "Specialty chemicals",
        "Başlık": "Long-Running Supplier And Distributor Of Industrial Chemicals",
        "Kaynak": "uk.businessesforsale.com", "Ciro": "£3.5m",
        "EBITDA/Kâr": "~£550k adjusted EBITDA", "Fiyat": "Undisclosed",
        "Satış nedeni": "retirement / lifestyle change", "E-posta": "", "Telefon": "",
        "Özet": "Industrial chemicals, decanting and bespoke mixtures; freehold property option.",
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
    {
        "Skor": 90, "Ülke": "Almanya", "Sektör": "Gıda hammaddesi / Food ingredients",
        "Başlık": "Nachfolge für etabliertes Unternehmen im Lebensmittelbereich",
        "Kaynak": "dub.de", "Ciro": "€8.5m", "EBITDA/Kâr": "", "Fiyat": "",
        "Satış nedeni": "Nachfolge / Verkauf", "E-posta": "", "Telefon": "",
        "Özet": "In-house production, processing, packaging and industrial customers.",
        "İlan / kaynak URL": "https://www.dub.de/de/unternehmen-kaufen/expose/nachfolge-fuer-profitables-etabliertes-unternehmen-im-lebensmittelbereich/",
        "Satış ilanı": "Evet", "Üretici sinyali": "Evet",
    },
]

def acq_preferred(url, country):
    d = get_domain(url)
    return any(d == x or d.endswith("." + x) for x in ACQ_COUNTRIES[country]["domains"])

def acq_build_queries(country, sector):
    c = ACQ_COUNTRIES[country]
    s = ACQ_SECTORS[sector][0]
    q = []
    for domain in c["domains"]:
        q.append(f'site:{domain} "{s}"')
        q.append(f'site:{domain} "{c["terms"][0]}" "{s}"')
    q.append(f'"{s}" "{c["terms"][0]}" manufacturer {c["name"]}')
    q.append(f'"{s}" "{c["terms"][1]}" manufacturer {c["name"]}')
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
    if any(x in text for x in ["restaurant", "takeaway", "cafe for sale", "franchise"]):
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
    rows = [r.copy() for r in ACQ_STARTER if r["Ülke"] in countries and r["Sektör"] in sectors]
    seen = {r["İlan / kaynak URL"] for r in rows}
    jobs = [(c, s, q) for c in countries for s in sectors for q in acq_build_queries(c, s)]
    progress = st.progress(0)
    status = st.empty()

    for i, (country, sector, query) in enumerate(jobs, start=1):
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
    text = f"{title} {snippet} {body}".lower()
    product_words = [w.lower() for w in re.split(r"[\s,/()+\-]+", product) if len(w) >= 3]
    product_hit = sum(1 for w in product_words if w in text)
    maker_hit = any(x in text for x in MANUFACTURING_TERMS)
    trader_hit = any(x in text for x in TRADER_HINTS)

    if is_blacklisted(url):
        return "unclear", 0
    if maker_hit and product_hit >= max(1, min(2, len(product_words))) and not trader_hit:
        return "confirmed", 30
    if maker_hit and product_hit >= 1:
        return "likely", 20
    if product_hit >= 1:
        return "unclear", 5
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
                hits.append(f"{title} — {snippet[:180]}")
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
    if turkey_presence:
        score += 10

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
    queries = supplier_queries(product, country_label, objective)
    seen_domains = set()
    rows = []
    progress = st.progress(0)
    status = st.empty()

    all_candidates = []
    for i, q in enumerate(queries, start=1):
        status.write(f"Aranıyor: **{product}** · `{q}`")
        results = live_search(q, max(6, min(12, max_companies)))
        for item in results:
            url = item.get("href", "")
            d = get_domain(url)
            if not url or not d or d in seen_domains or is_blacklisted(url):
                continue
            seen_domains.add(d)
            all_candidates.append(item)
        progress.progress(i / max(len(queries), 1))

    # Analyze only a manageable number of unique official-looking domains.
    for idx, item in enumerate(all_candidates[: max_companies * 3]):
        if len(rows) >= max_companies:
            break

        url = item.get("href", "")
        title = clean(item.get("title", ""))
        snippet = clean(item.get("body", ""))
        body = email_blob = phone = ""

        if deep_scan:
            body, email_blob, phone = fetch_page(url)
            time.sleep(0.04)

        status_value, base_score = supplier_manufacturer_status(product, title, snippet, body, url)

        # Strict mode: do not list obvious non-manufacturers.
        if status_value == "unclear" and not any(x in f"{title} {snippet}".lower() for x in MANUFACTURING_TERMS):
            continue

        company = company_guess(title, url)
        sales_email = choose_sales_email(email_blob)
        turkey_presence = turkey_presence_check(company, product) if turkey_check else ""
        text = f"{title} {snippet} {body}"
        score = supplier_score(status_value, sales_email, turkey_presence, text, objective)

        evidence = evidence_context(
            body or snippet,
            [product] + MANUFACTURING_TERMS,
            width=260,
        )

        rows.append({
            "Fit Score": score,
            "Firma": company,
            "Ülke / Pazar": country_label,
            "Website": f"https://{get_domain(url)}" if get_domain(url) else url,
            "Manufacturer Status": status_value,
            "Üretim Kanıtı": evidence,
            "Türkiye Varlığı": turkey_presence,
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
    return df

# =========================================================
# UI
# =========================================================

st.title("🏭 AS İleri – Firma & Ürün Bulucu")
st.caption("Şirket satın alma + yeni ürün / hammadde / üretici / distribütörlük araştırması tek uygulamada")

main_tab1, main_tab2 = st.tabs([
    "🏢 Firma Satın Alma / Halefiyet",
    "🧪 Ürün & Hammadde / Üretici Bulucu",
])

# -------------------------
# TAB 1: ACQUISITION
# -------------------------
with main_tab1:
    st.subheader("Satılık firma / halefiyet araştırması")

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

# -------------------------
# TAB 2: SOURCING / MANUFACTURER
# -------------------------
with main_tab2:
    st.subheader("Yeni ürün, hammadde, üretici ve temsilcilik araştırması")
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
                st.warning("Üretici sinyalini doğrulayabildiğim sonuç çıkmadı. Ürün adını İngilizce veya daha teknik isimle tekrar deneyin.")
            else:
                st.success(f"{len(st.session_state['supplier_results'])} üretici adayı bulundu.")

    supplier_df = st.session_state.get("supplier_results", pd.DataFrame())
    if not supplier_df.empty:
        min_fit = st.slider("Minimum üretici uygunluk skoru", 0, 100, 40, key="supplier_min_fit")
        supplier_view = supplier_df[supplier_df["Fit Score"] >= min_fit].copy()

        st.metric("Gösterilen üretici adayı", len(supplier_view))
        st.dataframe(
            supplier_view.drop(columns=["Taslak E-mail"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Kaynak URL": st.column_config.LinkColumn("Kaynak", display_text="Aç"),
                "Website": st.column_config.LinkColumn("Website", display_text="Site"),
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
        selected_firm = st.selectbox("Firma seç", firms, key="supplier_mail_firm")
        selected_row = supplier_view[supplier_view["Firma"] == selected_firm].iloc[0]
        st.text_input("Konu", value=selected_row["Taslak Konu"], key="supplier_subject")
        st.text_area("E-posta", value=selected_row["Taslak E-mail"], height=430, key="supplier_email_body")

st.markdown("---")
st.caption(
    "Sistem bilinmeyen veriyi uydurmaz. Kamuya açık sayfaları kullanır; CAPTCHA/giriş engellerini aşmaz. "
    "Üretici doğrulaması otomatik bir ön elemedir; sipariş veya sözleşme öncesinde resmi belge ve ticari due diligence gerekir."
)
