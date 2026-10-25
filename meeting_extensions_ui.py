"""Streamlit controls for encrypted user-owned meeting files and transcript editing."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

from meeting_archive import (
    ArchiveError, merge_records, new_record, pack_archive, unpack_archive,
    pack_voice, unpack_voice,
)
from meeting_core import timestamp, voice_reference


def archive_controls(company_scope: str = "") -> None:
    """Read existing or download a private encrypted device-owned archive."""
    st.session_state.setdefault("meeting_archive_records", [])
    with st.expander("🗂️ Firma bazlı şifreli toplantı arşivim", expanded=False):
        st.caption(
            "Dosyalar sunucuda kalıcı saklanmaz. Arşivi iPhone Dosyalar/iCloud Drive'a "
            "indirin; geri açmak için bu ekrana yükleyin. Şifre kaybedilirse kurtarılamaz."
        )
        uploaded = st.file_uploader(
            "Önceki .asmeeting arşivini aç", type=["asmeeting"],
            key="meeting_archive_upload",
        )
        secret = st.text_input(
            "Arşiv şifresi (en az 12 karakter)", type="password",
            key="meeting_archive_password",
        )
        if st.button("Şifreli arşivi aç", key="meeting_archive_restore",
                     disabled=uploaded is None, use_container_width=True):
            try:
                items = unpack_archive(uploaded.getvalue(), secret)
                # Signed company mode must not import/read records for other scopes.
                if company_scope and any(r["company"] != company_scope for r in items):
                    raise ArchiveError("Arşiv seçili şirket için değil.")
                st.session_state["meeting_archive_records"] = merge_records(
                    st.session_state["meeting_archive_records"], items
                )
                st.success(f"{len(items)} toplantı açıldı.")
            except ArchiveError as exc:
                st.error(str(exc))
        all_records = st.session_state["meeting_archive_records"]
        records = [r for r in all_records
                   if not company_scope or r["company"] == company_scope]
        firms = sorted({r["company"] for r in records})
        chosen_firm = st.selectbox(
            "Firma filtresi", ["Tüm firmalar", *firms],
            key="meeting_archive_company_filter",
        )
        visible = [r for r in records
                   if chosen_firm == "Tüm firmalar" or r["company"] == chosen_firm]
        st.caption(f"Bu oturumda {len(visible)} arşiv kaydı görüntülenebilir.")
        if visible:
            selected = st.selectbox(
                "Eski toplantıyı aç", [r["id"] for r in visible],
                format_func=lambda ident: next(
                    f"{r['date']} · {r['company']} · {r['title']}"
                    for r in visible if r["id"] == ident
                ),
                key="meeting_archive_select",
            )
            entry = next(r for r in visible if r["id"] == selected)
            st.markdown(entry["summary"])
            with st.expander("Eski görüşmenin konuşma dökümü"):
                st.text_area("Arşivlenmiş transkript", value=entry["transcript"],
                             height=240, disabled=True,
                             key="meeting_archive_old_transcript")
            st.download_button(
                "Bu transkripti indir", entry["transcript"],
                file_name="AS_Toplanti_Transkripti.txt", mime="text/plain",
                key="meeting_archive_old_export",
            )
        if all_records and len(secret) >= 12:
            try:
                archive_blob = pack_archive(all_records, secret)
                st.download_button(
                    "🔒 Güncel arşivimin tamamını indir",
                    archive_blob, file_name="AS_Toplanti_Arsivim.asmeeting",
                    mime="application/octet-stream",
                    key="meeting_archive_export", use_container_width=True,
                )
            except ArchiveError as exc:
                st.error(str(exc))
        elif all_records:
            st.info("Şifreli arşivi indirmek için en az 12 karakterli şifre yazın.")


def save_current_meeting(company: str, title: str, when: str, summary: str,
                         transcript: str, mine: str) -> None:
    st.divider()
    st.subheader("6 · Toplantıyı arşive ekle")
    st.caption(
        "Önce oturum arşivine ekleyin. Sonra sayfanın üstündeki **Güncel "
        "arşivimin tamamını indir** düğmesiyle şifreli dosyayı cihazınıza kaydedin."
    )
    if st.button("📁 Toplantıyı arşiv listeme ekle",
                 disabled=not bool(company.strip() and title.strip()),
                 key="meeting_archive_save", use_container_width=True):
        try:
            record = new_record(
                company, title, when, summary, transcript, mine,
                record_id=st.session_state.get("meeting_record_id"),
            )
            st.session_state["meeting_archive_records"] = merge_records(
                st.session_state.get("meeting_archive_records", []), [record]
            )
            st.session_state["meeting_record_id"] = record["id"]
            st.rerun()
        except ArchiveError as exc:
            st.error(str(exc))


def voice_profile_controls(sample) -> None:
    uploaded = st.file_uploader(
        "Kayıtlı şifreli ses profilimi yükle (.asvoice)",
        type=["asvoice"], key="meeting_voice_profile_upload",
    )
    secret = st.text_input(
        "Ses profili şifresi (en az 12 karakter)",
        type="password", key="meeting_voice_secret",
    )
    if st.button("Ses profilimi aç", key="meeting_voice_open",
                 disabled=uploaded is None):
        try:
            st.session_state["meeting_saved_voice"] = unpack_voice(
                uploaded.getvalue(), secret
            )
            st.success("Ses profiliniz bu oturumda kullanıma hazır.")
        except ArchiveError as exc:
            st.error(str(exc))
    if st.button("Yeni ses örneğimi hazırla", key="meeting_voice_prepare",
                 disabled=sample is None):
        try:
            with TemporaryDirectory(prefix="as_voice_") as tmp:
                work = Path(tmp)
                ext = Path(getattr(sample, "name", "") or "voice.wav").suffix.lower() or ".wav"
                path = work / ("reference" + ext)
                path.write_bytes(sample.getvalue())
                st.session_state["meeting_saved_voice"] = voice_reference(path, work)
            st.success("Ses profili hazır. Şifre girip dosyanızı indirin.")
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.get("meeting_saved_voice"):
        st.caption(
            "Ses profiliniz bu oturumda aktif. Sonraki girişlerde kullanmak için "
            "şifreli dosyasını indirin; ses tanıma yine hata yapabilir."
        )
        if len(secret) >= 12:
            try:
                blob = pack_voice(st.session_state["meeting_saved_voice"], secret)
                st.download_button(
                    "🔐 Ses profilimi şifreli indir", blob,
                    file_name="AS_Benim_Sesim.asvoice",
                    mime="application/octet-stream", key="meeting_voice_export",
                )
            except ArchiveError as exc:
                st.error(str(exc))


def edit_transcript(segments: list) -> None:
    with st.expander("✏️ Yanlış yazılan konuşmaları düzelt", expanded=False):
        i = st.selectbox(
            "Düzeltilecek cümle", range(len(segments)),
            format_func=lambda ix: (
                f"{timestamp(segments[ix].start)} · {segments[ix].speaker} · "
                f"{segments[ix].text[:65]}"
            ),
            key="meeting_edit_index",
        )
        line = segments[i]
        text = st.text_area(
            "Doğru metin", value=line.text, height=110,
            key=f"meeting_edit_text_{i}",
        )
        speaker_options = sorted({s.speaker for s in segments})
        speaker = st.selectbox(
            "Konuşmacı", speaker_options,
            index=speaker_options.index(line.speaker),
            key=f"meeting_edit_speaker_{i}",
        )
        if st.button("Cümleyi düzelt ve kaydet",
                     key="meeting_edit_save", use_container_width=True):
            if not text.strip() or len(text) > 6000:
                st.error("Metin boş olamaz veya 6000 karakteri aşamaz.")
            else:
                changed = list(segments)
                changed[i] = replace(line, text=text.strip(), speaker=speaker)
                st.session_state["meeting_segments"] = changed
                st.session_state.pop("meeting_summary", None)
                st.session_state.pop("meeting_signature", None)
                st.rerun()
