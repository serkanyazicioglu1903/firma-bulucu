
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
