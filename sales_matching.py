"""Explainable sector matching; scores indicate leads, not confirmed demand."""
import re
import unicodedata


def normalize(value):
    text = str(value or "").casefold().replace("ı", "i")
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


SECTORS = {
    "Fırıncılık / unlu mamul": ("fırıncılık", "bakery", "bisküvi", "biscuit", "biscuits", "unlu mamul", "ekmek", "bread", "cake", "pasta", "pastacılık", "wafer"),
    "Şekerleme": ("şekerleme", "confectionery"),
    "Çikolata": ("çikolata", "chocolate"),
    "Süt ürünleri": ("süt", "dairy", "süt ürünleri"),
    "Dondurma": ("dondurma", "ice cream"),
    "İçecek": ("içecek", "beverage", "beverages", "toz içecek"),
    "Et": ("et", "meat"),
    "Bitkisel ürün": ("vegan", "plant based", "plant-based"),
    "Sos": ("sos", "sauce"),
}


def contains_phrase(text, phrase):
    return bool(re.search(r"(?<!\w)" + re.escape(normalize(phrase)) + r"(?!\w)", normalize(text)))


def matched_sectors(customer_profile, target_sectors):
    targets = [x.strip() for x in re.split(r"[;,\n|]+", str(target_sectors or "")) if x.strip()]
    matches = []
    grouped = set()
    for label, aliases in SECTORS.items():
        if any(normalize(t) == normalize(a) for t in targets for a in aliases):
            grouped.update(normalize(a) for a in aliases)
            if any(contains_phrase(customer_profile, a) for a in aliases):
                matches.append(label)
    for target in targets:
        if normalize(target) not in grouped and contains_phrase(customer_profile, target):
            matches.append(target)
    return list(dict.fromkeys(matches))
