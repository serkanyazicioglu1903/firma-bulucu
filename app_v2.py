
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
        "terms": ["Nachfolge", "Ruhestand", "Firmenverkauf", "Unternehmen zu verkaufen", "Altersnachfolge"],
        "domains": ["nexxt-change.org", "dub.de", "deal-one.de"],
    },
    "İngiltere": {
        "name": "United Kingdom",
        "terms": ["business for sale", "retirement", "owner retiring", "succession", "offers invited"],
        "domains": ["uk.businessesforsale.com", "rightbiz.co.uk", "daltonsbusiness.com"],
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
    "Gıda hammaddesi / Food ingredients": [
        "food ingredients", "Lebensmittelzutaten", "ingredients alimentaires", "voedingsingrediënten"
    ],
    "Gıda katkı maddeleri": [
        "food additives", "Lebensmittelzusatzstoffe", "additifs alimentaires", "voedingsadditieven"
    ],
    "Aroma / renk": ["flavour colour", "flavor color", "Aromen Farbstoffe", "arômes colorants"],
    "Emülgatör / stabilizer / hydrocolloid": ["emulsifier stabilizer hydrocolloid", "Emulgator Stabilisator Hydrokolloid"],
    "Premix / powder blending": ["premix powder blending", "dry blending", "Pulvermischung"],
    "Specialty chemicals": ["specialty chemicals", "Spezialchemikalien", "chemical blending"],
    "Pigment / coating / dye": ["pigments dyes coatings", "Pigmente Farbstoffe Beschichtungen"],
    "Detergent / cleaning chemicals": ["detergent cleaning chemicals", "Reinigungsmittel Chemie"],
    "Lubricant / industrial oils": ["lubricants industrial oils", "Schmierstoffe Industrieöle"],
    "Toll / contract manufacturing": ["toll manufacturing contract manufacturing", "Lohnherstellung Lohnmischung"],
}

# Verified starter records. These are used only as a fallback / starter list,
# while the app also performs live web search.
STARTER = [
    {
        "Ülke":"Almanya","Sektör":"Gıda hammaddesi / Food ingredients",
        "Başlık":"Lebensmittelhersteller Feinkost | Eigene Produktion & LEH-Listungen in DACH",
        "Kaynak":"nexxt-change.org","Ciro":"ca. €600k","EBITDA/Kâr":"","Fiyat":"€0.5m–€2.5m ilan bandı",
        "Satış nedeni":"Altersnachfolge","E-posta":"","Telefon":"",
        "Özet":"Kendi üretimi, IFS Food sertifikası, DACH perakende listeleri. Yaşa bağlı halefiyet.",
        "İlan / kaynak URL":"https://www.nexxt-change.org/DE/Verkaufsangebot/Detailseite/detailseite_jsp?adId=648054",
        "Skor":90,"Arama tipi":"Doğrulanmış başlangıç"
    },
    {
        "Ülke":"Almanya","Sektör":"Gıda hammaddesi / Food ingredients",
        "Başlık":"Nachfolge für profitables, etabliertes Unternehmen im Lebensmittelbereich",
        "Kaynak":"dub.de","Ciro":"€8.5m","EBITDA/Kâr":"","Fiyat":"",
        "Satış nedeni":"Strategischer Verkauf","E-posta":"","Telefon":"",
        "Özet":"In-house üretim, işleme, paketleme ve sevkiyat; endüstriyel müşteri tabanı.",
        "İlan / kaynak URL":"https://www.dub.de/de/unternehmen-kaufen/expose/nachfolge-fuer-profitables-etabliertes-unternehmen-im-lebensmittelbereich/",
        "Skor":84,"Arama tipi":"Doğrulanmış başlangıç"
    },
    {
        "Ülke":"Almanya","Sektör":"Gıda hammaddesi / Food ingredients",
        "Başlık":"Etablierte B2B-Feinkost-Plattform mit starker Fachhandelsbasis",
        "Kaynak":"dub.de","Ciro":"€5.6m","EBITDA/Kâr":"bereinigte EBIT-Marge ~10%","Fiyat":"",
        "Satış nedeni":"Altersnachfolge","E-posta":"","Telefon":"",
        "Özet":"1,200–1,500 B2B müşteri; düzenli halefiyet süreci.",
        "İlan / kaynak URL":"https://www.dub.de/de/unternehmen-kaufen/expose/etablierte-b2b-feinkost-plattform-mit-starker-fachhandelsbasis-wachstumshebel/",
        "Skor":80,"Arama tipi":"Doğrulanmış başlangıç"
    },
    {
        "Ülke":"İngiltere","Sektör":"Specialty chemicals",
        "Başlık":"Long-Running Supplier And Distributor Of Industrial Chemicals",
        "Kaynak":"uk.businessesforsale.com","Ciro":"£3.5m YE25","EBITDA/Kâr":"~£550k adjusted EBITDA","Fiyat":"Undisclosed",
        "Satış nedeni":"retirement / lifestyle change","E-posta":"","Telefon":"",
        "Özet":"Asitler, solventler, cleaning agents, chloroalkalis; decanting ve bespoke mixtures; freehold opsiyonu.",
        "İlan / kaynak URL":"https://uk.businessesforsale.com/uk/long-running-supplier-and-distributor-of-industrial-chemicals.aspx",
        "Skor":92,"Arama tipi":"Doğrulanmış başlangıç"
    },
    {
        "Ülke":"İngiltere","Sektör":"Pigment / coating / dye",
        "Başlık":"Manufacturer and supplier of dyes and pigments",
        "Kaynak":"rightbiz.co.uk","Ciro":"£3.5m","EBITDA/Kâr":"£615k adjusted EBITDA YE25","Fiyat":"Offers invited",
        "Satış nedeni":"retirement","E-posta":"","Telefon":"",
        "Özet":"Water-based dyes, aqueous pigment dispersions, specialty coatings, toll manufacturing; 30,000 sq ft production site.",
        "İlan / kaynak URL":"https://www.rightbiz.co.uk/buy_business/for_sale/643296_undisclosed.html",
        "Skor":95,"Arama tipi":"Doğrulanmış başlangıç"
    },
    {
        "Ülke":"İngiltere","Sektör":"Specialty chemicals",
        "Başlık":"Manufacturer And Supplier Of Proprietary Chemical Solutions",
        "Kaynak":"uk.businessesforsale.com","Ciro":"£452k YE24","EBITDA/Kâr":"","Fiyat":"Offers invited",
        "Satış nedeni":"new ownership / growth","E-posta":"","Telefon":"",
        "Özet":"Antimicrobial, disinfectant, cleaner-disinfectant solutions; patents/IP and registrations included.",
        "İlan / kaynak URL":"https://uk.businessesforsale.com/uk/manufacturer-and-supplier-of-proprietary-chemical-solutions.aspx",
        "Skor":86,"Arama tipi":"Doğrulanmış başlangıç"
    },
]

EMAIL_RE = re.compile(r'[\w.\-+%]+@[\w.\-]+\.[A-Za-z]{2,}', re.I)
PHONE_RE = re.compile(r'(?:(?:\+\d{1,3}[\s().-]*)?(?:\d[\s().-]*){8,15})')

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def safe_get(url, params=None, timeout=12):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    }
    try:
        return requests.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception:
        return None

def search_bing_rss(query, max_results):
    out = []
    r = safe_get("https://www.bing.com/search", params={"q": query, "format": "rss", "count": max_results})
    if not r or r.status_code >= 400:
        return out
    try:
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:max_results]:
            title = clean(item.findtext("title"))
            link = clean(item.findtext("link"))
            desc = clean(item.findtext("description"))
            if link:
                out.append({"title": title, "href": link, "body": desc, "_provider":"Bing RSS"})
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
    if not r or r.status_code >= 400:
        return out
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for block in soup.select(".result"):
            a = block.select_one(".result__a")
            if not a:
                continue
            snippet = block.select_one(".result__snippet")
            href = ddg_final_url(a.get("href",""))
            if href:
                out.append({
                    "title": clean(a.get_text(" ", strip=True)),
                    "href": href,
                    "body": clean(snippet.get_text(" ", strip=True) if snippet else ""),
                    "_provider":"DuckDuckGo HTML"
                })
            if len(out) >= max_results:
                break
    except Exception:
        pass
    return out

def search_google_html(query, max_results):
    out = []
    r = safe_get("https://www.google.com/search", params={"q": query, "num": max_results, "hl":"en"})
    if not r or r.status_code >= 400:
        return out
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for h3 in soup.find_all("h3"):
            a = h3.find_parent("a")
            if not a:
                continue
            href = a.get("href","")
            if href.startswith("/url?q="):
                href = href.split("/url?q=",1)[1].split("&",1)[0]
            if href.startswith("http"):
                out.append({"title":clean(h3.get_text(" ", strip=True)),"href":href,"body":"","_provider":"Google HTML"})
            if len(out) >= max_results:
                break
    except Exception:
        pass
    return out

def live_search(query, max_results):
    merged, seen = [], set()
    diagnostics = []
    for fn in [search_bing_rss, search_ddg_html, search_google_html]:
        try:
            res = fn(query, max_results)
        except Exception:
            res = []
        diagnostics.append((fn.__name__, len(res)))
        for x in res:
            u = x.get("href","")
            if u and u not in seen:
                seen.add(u)
                merged.append(x)
        if len(merged) >= max_results:
            break
    return merged[:max_results], diagnostics

def fetch_page(url):
    r = safe_get(url, timeout=9)
    if not r or r.status_code >= 400 or "text/html" not in r.headers.get("content-type",""):
        return "", "", ""
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script","style","noscript","svg"]):
            tag.decompose()
        text = clean(soup.get_text(" ", strip=True))
        emails = "; ".join(sorted(set(EMAIL_RE.findall(text)))[:5])
        phones = []
        for m in PHONE_RE.findall(text):
            digits = re.sub(r"\D","",m)
            if 9 <= len(digits) <= 15:
                phones.append(clean(m))
        return text[:50000], emails, "; ".join(list(dict.fromkeys(phones))[:3])
    except Exception:
        return "", "", ""

def money(text, labels):
    for label in labels:
        m = re.search(
            rf"{label}\s*[:\-]?\s*((?:€|£|EUR|GBP)\s?[\d.,]+\s?(?:m|mn|million|k|thousand|Mio\.?)?|"
            r"[\d.,]+\s?(?:m|mn|million|k|thousand|Mio\.?)?\s?(?:€|£|EUR|GBP))",
            text, re.I
        )
        if m:
            return clean(m.group(1))
    return ""

def reason(text):
    low = text.lower()
    for w in ["retirement","retiring","ruhestand","altersbedingt","altersnachfolge","pensioen","retraite","succession","nachfolge"]:
        if w in low:
            return w
    return ""

def calc_score(title, snippet, body, sector):
    txt = f"{title} {snippet} {body[:7000]}".lower()
    score = 0
    if any(w in txt for w in ["manufacturer","manufacturing","production","producer","factory","plant","hersteller","produktion","produzent","fabricant","producent","blending","formulation"]):
        score += 35
    if any(w in txt for w in ["retirement","retiring","succession","nachfolge","ruhestand","altersbedingt","pensioen","opvolging","retraite","cession","for sale","te koop","à vendre"]):
        score += 30
    for phrase in SECTORS[sector]:
        for w in phrase.lower().split():
            if len(w) > 4 and w in txt:
                score += 3
    if any(x in txt for x in ["restaurant","takeaway","cafe for sale","franchise"]):
        score -= 30
    return max(0, min(100, score))

def queries(country_label, sector):
    c = COUNTRIES[country_label]
    # Less restrictive than v1.
    sector_terms = SECTORS[sector][:2]
    q = []
    for sp in sector_terms:
        q.append(f'{sp} {c["name"]} retirement succession manufacturer for sale')
        q.append(f'{sp} {c["name"]} acquisition opportunity')
        for term in c["terms"][:2]:
            q.append(f'{sp} {term} {c["name"]}')
    for domain in c["domains"]:
        q.append(f'site:{domain} {sector_terms[0]}')
        q.append(f'site:{domain} {c["terms"][0]}')
    return list(dict.fromkeys(q))

def starter_rows(countries, sectors):
    out = []
    for row in STARTER:
        if row["Ülke"] in countries and (row["Sektör"] in sectors or "Specialty chemicals" in sectors or "Gıda hammaddesi / Food ingredients" in sectors):
            out.append(row.copy())
    return out

def scan(countries, sectors, per_query, deep_scan):
    rows = starter_rows(countries, sectors)
    seen = {r["İlan / kaynak URL"] for r in rows}
    diag = []
    qlist = [(c,s,q) for c in countries for s in sectors for q in queries(c,s)]
    total = len(qlist)
    bar = st.progress(0)
    status = st.empty()

    for i,(c,s,q) in enumerate(qlist, start=1):
        status.write(f"Canlı arama: **{c} · {s}**")
        results, d = live_search(q, per_query)
        diag.append((q,d,len(results)))

        for r in results:
            url = r.get("href","")
            if not url or url in seen:
                continue
            seen.add(url)
            title = clean(r.get("title",""))
            snippet = clean(r.get("body",""))
            body = email = phone = ""
            if deep_scan:
                body, email, phone = fetch_page(url)
                time.sleep(0.05)
            text = f"{title} {snippet} {body}"
            turnover = money(text,[r"turnover",r"revenue",r"umsatz",r"omzet",r"chiffre d['’]affaires"])
            ebitda = money(text,[r"adjusted EBITDA",r"EBITDA",r"operating profit",r"profit",r"gewinn",r"winst"])
            price = money(text,[r"asking price",r"price",r"kaufpreis",r"vraagprijs",r"prix"])
            rows.append({
                "Skor":calc_score(title,snippet,body,s),
                "Ülke":c,"Sektör":s,"Başlık":title,
                "Kaynak":urlparse(url).netloc.replace("www.",""),
                "Ciro":turnover,"EBITDA/Kâr":ebitda,"Fiyat":price,
                "Satış nedeni":reason(text),"E-posta":email,"Telefon":phone,
                "Özet":snippet[:550],
                "İlan / kaynak URL":url,
                "Arama tipi":r.get("_provider","Canlı arama")
            })
        bar.progress(i/max(total,1))

    bar.empty()
    status.empty()
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["İlan / kaynak URL"]).sort_values(["Skor","Ülke"],ascending=[False,True]).reset_index(drop=True)
    return df, diag

st.title("🏭 Firma Bulucu")
st.caption("AS İleri / AS Food · Almanya ve İngiltere öncelikli satın alma / halefiyet araştırması")

with st.sidebar:
    countries = st.multiselect("Ülkeler", list(COUNTRIES), default=["Almanya","İngiltere"])
    sectors = st.multiselect("Sektörler", list(SECTORS), default=[
        "Gıda hammaddesi / Food ingredients","Gıda katkı maddeleri","Specialty chemicals"
    ])
    per_query = st.slider("Her sorguda sonuç", 3, 12, 6)
    deep_scan = st.checkbox("İlan sayfalarından finansal ve iletişim bilgisi çıkarmaya çalış", value=True)

tab1, tab2, tab3 = st.tabs(["🔎 Tara","📊 Sonuçlar","✉️ İlk temas"])

with tab1:
    st.write("Canlı arama motorlarını ve seçili M&A platformlarını tarar. Canlı arama engellenirse doğrulanmış başlangıç adaylarını da gösterir.")
    if st.button("ŞİMDİ TARA", type="primary", use_container_width=True):
        if not countries or not sectors:
            st.error("En az bir ülke ve sektör seçin.")
        else:
            df, diag = scan(countries,sectors,per_query,deep_scan)
            st.session_state["results"] = df
            st.session_state["diag"] = diag
            if df.empty:
                st.error("Hiç sonuç alınamadı.")
            else:
                live_count = int((df["Arama tipi"] != "Doğrulanmış başlangıç").sum())
                st.success(f"{len(df)} aday hazır. Canlı aramadan {live_count}, doğrulanmış başlangıç listesinden {len(df)-live_count} kayıt.")
            with st.expander("Arama bağlantı testi / teknik durum"):
                for q,d,n in diag[:30]:
                    st.write(q)
                    st.caption(f"Sonuç: {n} · " + " | ".join([f"{name}:{cnt}" for name,cnt in d]))

with tab2:
    df = st.session_state.get("results", pd.DataFrame())
    if df.empty:
        st.info("Önce Tara sekmesinden arama yapın.")
    else:
        min_score = st.slider("Minimum skor",0,100,35)
        view = df[df["Skor"]>=min_score].copy()
        st.metric("Gösterilen aday",len(view))
        st.dataframe(
            view,use_container_width=True,hide_index=True,
            column_config={
                "İlan / kaynak URL": st.column_config.LinkColumn("İlan / kaynak URL",display_text="Aç"),
                "Skor": st.column_config.ProgressColumn("Skor",min_value=0,max_value=100)
            }
        )
        st.download_button("CSV indir",view.to_csv(index=False).encode("utf-8-sig"),
                           file_name="Firma_Bulucu_Sonuclari.csv",mime="text/csv",use_container_width=True)

with tab3:
    st.text_input("Konu",value="Acquisition / Succession Opportunity – Request for NDA and Information Memorandum")
    st.text_area("Mail",value="""Dear Sir/Madam,

We are an established food ingredients and raw materials importer and distributor with operations in the United Kingdom and Türkiye. We are currently evaluating strategic acquisition opportunities in Europe, particularly established manufacturing businesses whose owners are considering retirement, succession or a full/partial exit.

We would be pleased to sign an NDA and receive the Information Memorandum, including recent financials, normalized EBITDA, customer and supplier concentration, working-capital requirements, net debt, production capacity, property status, certifications, regulatory matters and the seller's valuation expectations.

We are also open to structured transactions, including deferred consideration, seller financing or an earn-out where appropriate.

Kind regards,
Serkan Yazıcıoğlu
AS Food Global Limited / AS İleri Gıda""",height=420)

st.caption("Bilinmeyen veriyi uydurmaz. Kamuya açık sayfaları kullanır; CAPTCHA veya giriş engellerini aşmaz.")
