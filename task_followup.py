"""Task and weekly tracking views for the existing Control Tower task records."""
import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from psycopg import Error as PostgresError
import streamlit as st


COMPANIES = ("AS İleri", "AS Food Global", "AS İleri / AS Food Global")
PRIORITIES = ("Kritik", "Yüksek", "Orta", "Düşük")
STATUSES = ("Açık", "Devam", "Takipte", "Bekliyor", "Tamamlandı")
WORKFLOWS = {
    "Genel görev": ("Takipte",),
    "Tedarik / numune": (
        "Takipte", "Üretici araştırması", "Şartname incelemesi", "Numune talebi",
        "Numune yolda", "Numune ulaştı", "Denemede", "Onaylandı", "Kapandı",
    ),
    "Sevkiyat": (
        "Takipte", "Sipariş teyidi", "Hazırlık", "Rezervasyon / evrak bekliyor",
        "Kalkış teyidi bekliyor", "Yolda", "Gümrükte", "Teslim edildi", "Gecikme / sorun", "İptal",
    ),
    "Fırsat": (
        "Takipte", "Araştırma", "İlk temas", "NDA", "Bilgi / dosya bekliyor",
        "Ön değerlendirme", "Görüşme planlandı", "Detaylı inceleme",
        "Teklif / müzakere", "Tamamlandı", "Kapanış / vazgeçildi",
    ),
}
BASE_FIELDS = ("title", "related_to", "owner", "priority", "due_date", "status", "notes")
DETAIL_FIELDS = (
    "company", "workflow", "stage", "last_contact_date", "pending_question",
    "next_action", "risk", "customer_impact", "decision", "draft_en", "context_note",
    "source_key",
)
TABLE_FIELDS = {
    "title": "Görev", "company": "Şirket", "related_to": "İlgili firma / ürün",
    "workflow": "İş akışı", "stage": "Aşama", "status": "Durum", "priority": "Öncelik",
    "owner": "Sorumlu", "due_date": "Son tarih", "last_contact_date": "Son temas",
    "pending_question": "Bekleyen soru", "next_action": "Bir sonraki aksiyon",
    "risk": "Risk", "customer_impact": "Müşteri etkisi", "display_note": "Not",
}
DETAIL_COLUMN = "followup_details"
DRAFT_NOTICE = "İncele ve gönder. Taslağı doğruladıktan sonra kendi e-posta uygulamanızı kullanın."
DATE_FILTERS = ("Tümü", "Geciken", "Önümüzdeki 7 gün", "Tarihsiz")
DATA_ERRORS = (sqlite3.Error, PostgresError)
LINK_NOTE = re.compile(r"(?:Satış pipeline|Cross-sell) fırsatı #\d+")
INSERT_TASK = """INSERT INTO tasks
    (title, related_to, owner, priority, due_date, status, notes, followup_details)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
KEY_PREFIX = "ct_followup_"


def _text(value):
    return value if isinstance(value, str) else ""


def _date(value):
    try:
        return date.fromisoformat(_text(value))
    except ValueError:
        return None


def _format_date(value):
    parsed = _date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else ""


def _today():
    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


def _search_key(value):
    return value.casefold().replace("\u0307", "").replace("ı", "i")


def _details(value):
    try:
        record = json.loads(value or "{}")
    except (ValueError, TypeError):
        record = {}
    if not isinstance(record, dict):
        record = {}
    fields = {name: _text(record.get(name)) for name in DETAIL_FIELDS}
    fields["production_risk"] = record.get("production_risk") is True
    return fields


def load_tasks(query_df):
    frame = query_df("SELECT * FROM tasks")
    rows = []
    extended = DETAIL_COLUMN in frame.columns
    for raw in frame.to_dict("records"):
        original = tuple(_text(raw.get(field)) for field in BASE_FIELDS)
        row = dict(zip(BASE_FIELDS, original))
        details = _details(raw.get(DETAIL_COLUMN))
        row.update(details)
        row["id"] = int(raw["id"])
        row["workflow"] = row["workflow"] or "Genel görev"
        row["stage"] = row["stage"] or "Takipte"
        row["linked"] = bool(LINK_NOTE.fullmatch(row["notes"]))
        row["display_note"] = row["context_note"] if row["linked"] else row["notes"]
        row["revision"] = original + ((_text(raw.get(DETAIL_COLUMN)),) if extended else ())
        rows.append(row)

    priority_order = {value: index for index, value in enumerate(PRIORITIES)}
    rows.sort(key=lambda row: (
        priority_order.get(row["priority"], len(PRIORITIES)),
        _date(row["due_date"]) or date.max,
        -row["id"],
    ))
    return rows, extended


def weekly_sections(rows, today):
    active = [row for row in rows if row["status"] != "Tamamlandı"]
    due = [(row, _date(row["due_date"])) for row in active]
    end = today + timedelta(days=6)
    dated = sorted(((row, day) for row, day in due if day), key=lambda pair: pair[1])
    return (
        ("Karar bekleyenler", [(row, row["decision"]) for row in active if row["decision"]]),
        ("Kritik terminler", [
            (row, _format_date(row["due_date"])) for row, day in dated
            if today <= day <= end and (row["priority"] in PRIORITIES[:2] or row["production_risk"])
        ]),
        ("Cevap bekleyenler", [
            (row, row["pending_question"]) for row in active if row["pending_question"]
        ]),
        ("Geciken takipler", [
            (row, f"{(today - day).days} gün gecikti · {_format_date(row['due_date'])}")
            for row, day in dated if day < today
        ]),
        ("Müşteri üretim riskleri", [
            (row, row["customer_impact"] or row["risk"]) for row in active if row["production_risk"]
        ]),
        ("Önerilen sonraki aksiyonlar", [
            (row, row["next_action"]) for row in active if row["next_action"]
        ]),
    )


def _weekly_group(title, items):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        if not items:
            st.caption("Kayıt yok")
            return
        for row, detail in items[:3]:
            st.text(row["title"])
            st.caption(detail or "Takipte")
        if len(items) > 3:
            with st.expander(f"{len(items) - 3} kayıt daha"):
                for row, detail in items[3:]:
                    st.text(row["title"])
                    st.caption(detail or "Takipte")


def render_weekly_followup(rows):
    today = _today()
    end = today + timedelta(days=6)
    st.markdown("#### Haftalık yönetici görünümü")
    st.caption(f"{today:%d.%m.%Y} – {end:%d.%m.%Y} · Türkiye saati")
    sections = weekly_sections(rows, today)
    for start in (0, 3):
        for column, (title, items) in zip(st.columns(3), sections[start:start + 3]):
            with column:
                _weekly_group(title, items)


def _choose(container, label, options, current, key):
    values = tuple(dict.fromkeys((*options, current))) if current else tuple(options)
    index = values.index(current) if current in values else 0
    return container.selectbox(label, values, index=index, key=key)


def _cards(rows):
    for row in rows:
        with st.container(border=True):
            st.text(row["title"])
            st.caption(" · ".join(filter(None, (
                row["company"], row["related_to"], row["workflow"], row["stage"],
                row["status"], row["priority"],
            ))))
            col1, col2, col3 = st.columns(3)
            col1.caption(f"Sorumlu · {row['owner'] or '—'}")
            col2.caption(f"Son tarih · {_format_date(row['due_date']) or '—'}")
            col3.caption(f"Son temas · {_format_date(row['last_contact_date']) or '—'}")
            for field in ("pending_question", "next_action", "risk", "customer_impact", "display_note"):
                if row[field]:
                    st.caption(TABLE_FIELDS[field])
                    st.text(row[field])
            if row["decision"]:
                st.caption("Karar konusu")
                st.text(row["decision"])
            if row["draft_en"]:
                st.warning(DRAFT_NOTICE)
                st.code(row["draft_en"], language=None, wrap_lines=True)


def _table(rows):
    table = [
        {label: _date(row[field]) if field in ("due_date", "last_contact_date") else row[field]
         for field, label in TABLE_FIELDS.items()}
        for row in rows
    ]
    columns = {TABLE_FIELDS[field]: st.column_config.DateColumn(format="DD.MM.YYYY")
               for field in ("due_date", "last_contact_date")}
    st.dataframe(table, width="stretch", hide_index=True, column_config=columns)


def _save_task(execute, row, base, details, extended):
    detail_values = (json.dumps(details, ensure_ascii=False),) if extended else ()
    params = tuple(base[field] for field in BASE_FIELDS) + detail_values
    fields = BASE_FIELDS + ((DETAIL_COLUMN,) if extended else ())
    if row is None:
        sql = INSERT_TASK if extended else (
            "INSERT INTO tasks (title, related_to, owner, priority, due_date, status, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        return execute(sql, params)
    assignments = ", ".join(f"{name}=?" for name in fields)
    original_matches = " AND ".join(f"COALESCE({name}, '')=?" for name in fields)
    return execute(
        f"UPDATE tasks SET {assignments} WHERE id=? AND {original_matches}",
        params + (row["id"],) + row["revision"],
    )


def _editor(row, execute, extended):
    current = row or {}
    if row is None:
        key = KEY_PREFIX + "new_"
    else:
        revision = sha256(repr(row["revision"]).encode()).hexdigest()[:12]
        key = f"{KEY_PREFIX}{row['id']}_{revision}_"
    workflow = "Genel görev"
    if extended:
        workflow = _choose(
            st, "İş akışı", WORKFLOWS, current.get("workflow", ""), key + "workflow"
        )
    stages = WORKFLOWS.get(workflow, ("Takipte",))
    with st.form(key + "form", clear_on_submit=row is None):
        title = st.text_input("Görev adı", value=current.get("title", ""), max_chars=240)
        related = st.text_input("İlgili firma / ürün", value=current.get("related_to", ""), max_chars=300)
        col1, col2 = st.columns(2)
        owner = col1.text_input("Sorumlu", value=current.get("owner", ""), max_chars=120)
        due = col2.date_input("Son tarih", value=_date(current.get("due_date")), format="DD.MM.YYYY")
        status = _choose(col1, "Durum", STATUSES, current.get("status", ""), key + "status")
        priority = _choose(col2, "Öncelik", PRIORITIES, current.get("priority") or "Orta", key + "priority")
        details = {"source_key": current.get("source_key", ""), "workflow": workflow}
        if extended:
            details["company"] = _choose(
                col1, "Şirket", ("", *COMPANIES), current.get("company", ""), key + "company"
            )
            contact = col2.date_input(
                "Son temas", value=_date(current.get("last_contact_date")), format="DD.MM.YYYY"
            )
            details["last_contact_date"] = contact.isoformat() if contact else ""
            previous_stage = current.get("stage", "") if workflow == current.get("workflow") else ""
            details["stage"] = _choose(st, "Aşama", stages, previous_stage, key + "stage_" + workflow)
            for field in ("pending_question", "next_action", "risk", "customer_impact", "decision"):
                label = TABLE_FIELDS.get(field, "Karar konusu")
                details[field] = st.text_area(
                    label, value=current.get(field, ""), height=72, max_chars=2400
                ).strip()
            details["production_risk"] = st.checkbox(
                "Müşteri üretimini etkileyebilir", value=current.get("production_risk", False)
            )
        if current.get("linked"):
            st.caption(current["notes"])
        note = st.text_area(
            "Not", value=current.get("display_note", ""), height=85, max_chars=4000,
            disabled=bool(current.get("linked") and not extended),
        ).strip()
        if extended:
            st.warning(DRAFT_NOTICE)
            details["draft_en"] = st.text_area(
                "İngilizce taslak cevap", value=current.get("draft_en", ""),
                height=160, max_chars=6000, help="Yanıtı İngilizce yazın.",
            ).strip()
        submitted = st.form_submit_button("Görevi kaydet", type="primary")
    if not submitted:
        return
    if not title.strip():
        st.error("Görev adını girin.")
        return
    if current.get("linked"):
        details["context_note"] = note
        note = current["notes"]
    base = dict(
        title=title.strip(), related_to=related.strip(), owner=owner.strip(),
        priority=priority, due_date=due.isoformat() if due else "", status=status, notes=note,
    )
    try:
        saved = _save_task(execute, row, base, details, extended)
    except DATA_ERRORS:
        st.error("Görev kaydedilemedi. Lütfen tekrar deneyin.")
        return
    if saved != 1:
        st.error("Görev bu işlem sırasında değişti. Sayfayı yenileyip tekrar deneyin.")
        return
    st.session_state[KEY_PREFIX + "notice"] = "Görev kaydedildi."
    st.rerun()


def _import_rows(payload):
    if len(payload) > 524_288:
        raise ValueError
    try:
        entries = json.loads(payload)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError from exc
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError
        base = {field: _text(entry.get(field)).strip() for field in BASE_FIELDS}
        details = {field: _text(entry.get(field)).strip() for field in DETAIL_FIELDS}
        details["production_risk"] = entry.get("production_risk") is True
        workflow = details["workflow"] or "Genel görev"
        stage = details["stage"] or "Takipte"
        if (
            not base["title"] or len(base["title"]) > 240
            or base["status"] not in STATUSES
            or base["priority"] not in PRIORITIES
            or workflow not in WORKFLOWS
            or stage not in WORKFLOWS[workflow]
            or (details["company"] and details["company"] not in COMPANIES)
            or (base["due_date"] and not _date(base["due_date"]))
            or (details["last_contact_date"] and not _date(details["last_contact_date"]))
            or any(len(value) > 6000 for value in (*base.values(), *(_text(v) for v in details.values())))
        ):
            raise ValueError
        details.update(workflow=workflow, stage=stage)
        result.append((base, details))
    return result


def import_tasks(payload, get_conn, *, live_postgres, audit_import):
    entries = _import_rows(payload)
    added = 0
    with get_conn() as conn:
        # Serialize the duplicate check and insert across concurrent imports.
        conn.execute("LOCK TABLE tasks IN SHARE ROW EXCLUSIVE MODE" if live_postgres else "BEGIN IMMEDIATE")
        existing = conn.execute("SELECT title, followup_details FROM tasks").fetchall()
        titles = {_search_key(_text(row[0]).strip()) for row in existing}
        source_keys = {_details(row[1])["source_key"] for row in existing}
        for base, details in entries:
            title = _search_key(base["title"])
            source_key = details["source_key"]
            if title in titles or (source_key and source_key in source_keys):
                continue
            conn.execute(INSERT_TASK, (
                *(base[field] for field in BASE_FIELDS), json.dumps(details, ensure_ascii=False)
            ))
            titles.add(title)
            source_keys.add(source_key)
            added += 1
        conn.commit()
    if added:
        audit_import(INSERT_TASK)
    return added, len(entries) - added


def render_task_followup(rows, extended, execute, get_conn, *, live_postgres, audit_import):
    st.markdown("#### Görev ve Takip")
    notice = st.session_state.pop(KEY_PREFIX + "notice", "")
    if notice:
        st.success(notice)
    if not extended:
        st.info("Ayrıntılı takip alanları veritabanı güncellemesinden sonra açılır.")
    with st.expander("Filtreler", expanded=True):
        first, second, third = st.columns(3)
        needle = _search_key(first.text_input("Görev, firma veya aksiyon ara", key=KEY_PREFIX + "search").strip())
        status = second.selectbox("Durum", ("Tümü", "Açık görevler", *STATUSES), key=KEY_PREFIX + "status")
        priority = third.selectbox("Öncelik", ("Tümü", *PRIORITIES), key=KEY_PREFIX + "priority")
        company = first.selectbox("Şirket", ("Tümü", *COMPANIES), key=KEY_PREFIX + "company")
        workflow = second.selectbox("İş akışı", ("Tümü", *WORKFLOWS), key=KEY_PREFIX + "workflow")
        owners = sorted({row["owner"] for row in rows if row["owner"]})
        owner = third.selectbox("Sorumlu", ("Tümü", "Atanmamış", *owners), key=KEY_PREFIX + "owner")
        stage_options = WORKFLOWS.get(workflow, ())
        stage = second.selectbox("Aşama", ("Tümü", *stage_options), key=KEY_PREFIX + "stage_" + workflow)
        term = third.selectbox("Termin", DATE_FILTERS, key=KEY_PREFIX + "term")
    today = _today()
    end = today + timedelta(days=6)

    def matches_term(row):
        day = _date(row["due_date"])
        return (term == "Tümü" or (term == "Tarihsiz" and day is None)
                or (term == "Geciken" and day and day < today and row["status"] != "Tamamlandı")
                or (term == "Önümüzdeki 7 gün" and day and today <= day <= end))

    filtered = [
        row for row in rows
        if (not needle or needle in _search_key(" ".join((row["title"], row["related_to"], row["next_action"]))))
        and (status == "Tümü" or row["status"] == status or
             (status == "Açık görevler" and row["status"] != "Tamamlandı"))
        and (priority == "Tümü" or row["priority"] == priority)
        and (company == "Tümü" or row["company"] in (company, COMPANIES[-1]))
        and (workflow == "Tümü" or row["workflow"] == workflow)
        and (stage == "Tümü" or row["stage"] == stage)
        and (owner == "Tümü" or row["owner"] == ("" if owner == "Atanmamış" else owner))
        and matches_term(row)
    ]
    view = st.radio("Görünüm", ("Kartlar", "Tablo"), horizontal=True, key=KEY_PREFIX + "view")
    st.caption(f"{len(filtered)} görev")
    if not filtered:
        st.info("Bu filtrelere uyan görev yok.")
    elif view == "Kartlar":
        _cards(filtered)
    else:
        _table(filtered)

    with st.expander("Görev ekle / düzenle"):
        by_id = {row["id"]: row for row in filtered}
        selected = st.selectbox(
            "Görev", (None, *by_id),
            format_func=lambda value: "Yeni görev" if value is None else by_id[value]["title"],
            key=KEY_PREFIX + "selected",
        )
        _editor(by_id.get(selected), execute, extended)
    if extended:
        with st.expander("Takipleri içe aktar"):
            upload = st.file_uploader("Görev listesi (JSON)", type="json", key=KEY_PREFIX + "upload")
            if upload is not None and st.button("Takipleri ekle", key=KEY_PREFIX + "import"):
                try:
                    added, skipped = import_tasks(
                        upload.getvalue(), get_conn, live_postgres=live_postgres, audit_import=audit_import
                    )
                except ValueError:
                    st.error("Görev dosyasındaki alanları ve tarih biçimlerini kontrol edin.")
                except DATA_ERRORS:
                    st.error("Takipler içe aktarılamadı. Lütfen tekrar deneyin.")
                else:
                    st.session_state[KEY_PREFIX + "notice"] = (
                        f"{added} görev eklendi. {skipped} eşleşen görev bulundu."
                    )
                    st.rerun()
