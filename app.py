
import re
import time
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except Exception:
    from duckduckgo_search import DDGS

st.set_page_config(page_title="Firma Bulucu", page_icon="🏭", layout="wide")

COUNTRIES = {
    "Almanya": {
        "name": "Germany",
        "sale_terms": ["Nachfolge", "Unternehmensnachfolge", "Firmenverkauf", "Ruhestand", "Unternehmen zu verkaufen"],
        "domains": ["nexxt-change.org", "dub.de", "deal-one.de"],
    },
    "İngiltere": {
        "name": "United Kingdom",
        "sale_terms": ["business for sale", "owner retiring", "retirement", "succession", "acquisition opportunity"],
        "domains": ["uk.businessesforsale.com", "rightbiz.co.uk", "daltonsbusiness.com"],
    },
    "Hollanda": {
        "name": "Netherlands",
        "sale_terms": ["bedrijf te koop", "bedrijfsovername", "opvolging", "pensioen", "onderneming te koop"],
        "domains": ["brookz.nl", "bedrijventekoop.nl"],
    },
    "Fransa": {
        "name": "France",
        "sale_terms": ["entreprise à vendre", "cession entreprise", "retraite", "succession", "cession PME"],
        "domains": ["fusacq.com", "cessionpme.com"],
    },
}

SECTORS = {
    "Gıda hammaddesi / Food ingredients": ["food ingredients manufacturer", "Lebensmittelzutaten Hersteller"],
    "Gıda katkı maddeleri": ["food additives manufacturer", "Lebensmittelzusatzstoffe Hersteller"],
    "Aroma / renk": ["flavour colour manufacturer", "Aromen Farbstoffe Hersteller"],
    "Emülgatör / stabilizer / hydrocolloid": ["emulsifier stabilizer hydrocolloid manufacturer"],
    "Premix / powder blending": ["premix manufacturer", "powder blending manufacturer"],
    "Specialty chemicals": ["specialty chemicals manufacturer", "Spezialchemikalien Hersteller"],
    "Pigment / coating / dye": ["pigments manufacturer", "dyes manufacturer", "coatings manufacturer"],
    "Detergent / cleaning chemicals": ["detergent manufacturer", "cleaning chemicals manufacturer"],
    "Lubricant / industrial oils": ["lubricants manufacturer", "industrial oils manufacturer"],
    "Toll / contract manufacturing": ["toll manufacturing chemicals", "contract manufacturing food ingredients"],
}

EMAIL_RE = re.compile(r'[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}', re.I)
PHONE_RE = re.compile(r'(?:(?:\+\d{1,3}[\s().-]*)?(?:\d[\s().-]*){8,15})')

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def fetch_page(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, timeout=8, headers=headers, allow_redirects=True)
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
            return "", "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        text = clean(soup.get_text(" ", strip=True))
        emails = "; ".join(sorted(set(EMAIL_RE.findall(text)))[:5])
        phones = []
        for m in PHONE_RE.findall(text):
            digits = re.sub(r"\D", "", m)
            if 9 <= len(digits) <= 15:
                phones.append(clean(m))
        return text[:50000], emails, "; ".join(list(dict.fromkeys(phones))[:3])
    except Exception:
        return "", "", ""

def extract_reason(text):
    low = text.lower()
    for word in ["retirement", "retiring", "ruhestand", "altersbedingt", "pensioen", "retraite", "succession", "nachfolge"]:
        if word in low:
            return word
    return ""

def find_money(text, labels):
    for label in labels:
        m = re.search(
            rf"{label}\s*[:\-]?\s*((?:€|£|EUR|GBP)\s?[\d.,]+\s?(?:m|mn|million|k|thousand|Mio\.?)?|"
            r"[\d.,]+\s?(?:m|mn|million|k|thousand|Mio\.?)?\s?(?:€|£|EUR|GBP))",
            text, re.I
        )
        if m:
            return clean(m.group(1))
    return ""

def extract_metrics(text):
    return (
        find_money(text, [r"turnover", r"revenue", r"umsatz", r"omzet", r"chiffre d['’]affaires"]),
        find_money(text, [r"adjusted EBITDA", r"EBITDA", r"operating profit", r"profit", r"gewinn", r"winst"]),
        find_money(text, [r"asking price", r"price", r"kaufpreis", r"vraagprijs", r"prix"]),
    )

def score(title, snippet, body, sector):
    txt = f"{title} {snippet} {body[:6000]}".lower()
    n = 0
    if any(w in txt for w in ["manufacturer","manufacturing","production","producer","factory","plant","hersteller","produktion","produzent","fabricant","producent","blending","formulation"]):
        n += 30
    if any(w in txt for w in ["retirement","retiring","succession","nachfolge","ruhestand","altersbedingt","pensioen","opvolging","retraite","cession","for sale","te koop","à vendre"]):
        n += 30
    for phrase in SECTORS[sector]:
        for w in phrase.lower().split():
            if len(w) > 4 and w in txt:
                n += 3
    if any(x in txt for x in ["restaurant", "takeaway", "cafe for sale"]):
        n -= 30
    return max(0, min(100, n))

def search_web(query, max_results):
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []

def build_queries(country_label, sector):
    c = COUNTRIES[country_label]
    sp = SECTORS[sector][0]
    queries = []
    for d in c["domains"]:
        queries.append(f'site:{d} "{sp}"')
        queries.append(f'site:{d} "{c["sale_terms"][0]}" "{sp}"')
    for sale in c["sale_terms"][:3]:
        queries.append(f'"{sp}" "{sale}" {c["name"]}')
    return list(dict.fromkeys(queries))

def scan(countries, sectors, per_query, deep_scan):
    rows, seen = [], set()
    total = sum(len(build_queries(c, s)) for c in countries for s in sectors)
    done = 0
    bar = st.progress(0)
    status = st.empty()

    for c in countries:
        for s in sectors:
            for q in build_queries(c, s):
                done += 1
                status.write(f"Aranıyor: **{c}** · **{s}**")
                for r in search_web(q, per_query):
                    url = r.get("href") or r.get("url") or ""
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    title = clean(r.get("title", ""))
                    snippet = clean(r.get("body", r.get("snippet", "")))
                    body = email = phone = ""
                    if deep_scan:
                        body, email, phone = fetch_page(url)
                        time.sleep(0.1)
                    text = f"{title} {snippet} {body}"
                    turnover, ebitda, price = extract_metrics(text)
                    rows.append({
                        "Skor": score(title, snippet, body, s),
                        "Ülke": c,
                        "Sektör": s,
                        "Başlık": title,
                        "Kaynak": urlparse(url).netloc.replace("www.", ""),
                        "Ciro": turnover,
                        "EBITDA/Kâr": ebitda,
                        "Fiyat": price,
                        "Satış nedeni": extract_reason(text),
                        "E-posta": email,
                        "Telefon": phone,
                        "Özet": snippet[:500],
                        "İlan / kaynak URL": url,
                    })
                bar.progress(min(1.0, done / max(total, 1)))

    status.empty()
    bar.empty()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Skor", ascending=False).reset_index(drop=True)

st.title("🏭 Firma Bulucu")
st.caption("AS İleri / AS Food · Almanya ve İngiltere öncelikli satın alma / halefiyet araştırması")

with st.sidebar:
    countries = st.multiselect("Ülkeler", list(COUNTRIES), default=["Almanya", "İngiltere"])
    sectors = st.multiselect(
        "Sektörler",
        list(SECTORS),
        default=["Gıda hammaddesi / Food ingredients", "Gıda katkı maddeleri", "Specialty chemicals"]
    )
    per_query = st.slider("Her sorguda sonuç", 3, 15, 7)
    deep_scan = st.checkbox("İlan sayfalarından finansal ve iletişim bilgisi çıkarmaya çalış", value=True)

tab1, tab2, tab3 = st.tabs(["🔎 Tara", "📊 Sonuçlar", "✉️ İlk temas"])

with tab1:
    st.write("Satılık / emeklilik / halefiyet ilanlarını otomatik arar ve mümkün olan alanları çıkarır.")
    if st.button("ŞİMDİ TARA", type="primary", use_container_width=True):
        if not countries or not sectors:
            st.error("En az bir ülke ve sektör seçin.")
        else:
            st.session_state["results"] = scan(countries, sectors, per_query, deep_scan)
            if st.session_state["results"].empty:
                st.warning("Sonuç bulunamadı veya arama motoru geçici olarak yanıt vermedi.")
            else:
                st.success(f"{len(st.session_state['results'])} aday bulundu.")

with tab2:
    df = st.session_state.get("results", pd.DataFrame())
    if df.empty:
        st.info("Önce Tara sekmesinde arama yapın.")
    else:
        min_score = st.slider("Minimum skor", 0, 100, 35)
        view = df[df["Skor"] >= min_score]
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
            file_name="Firma_Bulucu_Sonuclari.csv",
            mime="text/csv",
            use_container_width=True,
        )

with tab3:
    st.text_input("Konu", value="Acquisition / Succession Opportunity – Request for NDA and Information Memorandum")
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

st.caption("Kamuya açık sayfaları kullanır; CAPTCHA/giriş engellerini aşmaz ve bilinmeyen bilgileri uydurmaz.")
