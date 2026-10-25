"""Mobile-friendly meeting notebook embedded behind AS Control Tower login.

All meeting data remains in the current Streamlit session. No database writes.
"""
from __future__ import annotations

from datetime import date
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

from meeting_core import (
    compile_report, my_speech_text, prepare_chunks, summarize_meeting,
    transcript_text, transcribe_chunks, voice_reference,
)


def _config(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    try:
        return str(st.secrets.get(key, "") or "")
    except (FileNotFoundError, OSError, KeyError):
        return ""


def _reset() -> None:
    for key in (
        "meeting_audio_hash", "meeting_segments", "meeting_parts",
        "meeting_has_voice", "meeting_summary", "meeting_signature",
        "meeting_speaker_selection",
    ):
        st.session_state.pop(key, None)


def render_meeting_workspace(*, company_scope: str = "") -> None:
    """Render only after the caller's existing login/tenant gate."""
    st.header("🎙️ AS Toplantı Hafızası")
    st.caption("Ses kaydı → konuşmacıları ayır → toplantı özeti ve aksiyonlar → indir.")
    st.info(
        "📱 Uzun toplantılarda iPhone **Sesli Notlar** uygulamasını kullanıp "
        "kayıt dosyasını yükleyin. Tarayıcıdan kayıt, ekran kilitlenirse kesilebilir."
    )
    st.warning(
        "Kayıt ve rapor bu oturumda geçici olarak tutulur; şirket veritabanına "
        "otomatik kaydedilmez. Toplantı sonunda raporu cihazınıza indirin."
    )

    api_key = _config("OPENAI_API_KEY")
    if not api_key or api_key.startswith("sk-ORNEK"):
        st.error(
            "Toplantıların sesini işlemek için sunucuda OPENAI_API_KEY "
            "tanımlanması gerekiyor. Bu ayar tamamlanana kadar AI analizi kullanılamaz."
        )

    with st.expander("1 · Toplantı bilgileri", expanded=True):
        title = st.text_input("Görüşme konusu", placeholder="Örn. Pantur 1250 teknik görüşmesi", key="meeting_title")
        company = st.text_input("Karşı taraf / firma", value=company_scope, key="meeting_company")
        when = st.date_input("Toplantı tarihi", value=date.today(), key="meeting_date")
        participants = st.text_input("Katılımcılar", key="meeting_participants")
        my_name = st.text_input("Benim adım", value="Serkan", key="meeting_my_name")

    st.subheader("2 · Ses kaydını ekle")
    mode = st.radio(
        "Kayıt yöntemi",
        ("Ses dosyası yükle", "Mikrofonla şimdi kaydet"),
        key="meeting_mode",
    )
    if mode == "Ses dosyası yükle":
        audio = st.file_uploader(
            "M4A, MP3, WAV, MP4 veya WEBM yükleyin",
            type=["m4a", "mp3", "wav", "webm", "mp4", "ogg", "flac", "mpeg", "mpga"],
            key="meeting_file",
        )
    else:
        audio = st.audio_input(
            "Kaydı başlat / bitir (telefonu kilitlemeyin)",
            sample_rate=16000, key="meeting_microphone",
        )

    with st.expander("3 · Kendi sesimi tanı (isteğe bağlı)"):
        st.caption(
            "Sadece sizin konuştuğunuz 5–8 saniyelik bir kayıt tanımaya yardımcı olur. "
            "Ses olmadan da konuşmacıları konuşma dökümünden elle seçebilirsiniz."
        )
        sample_mode = st.radio(
            "Ses örneği yöntemi", ("Mikrofon", "Dosya yükle"), key="meeting_sample_mode"
        )
        if sample_mode == "Mikrofon":
            sample = st.audio_input(
                "Yalnızca siz konuşun", sample_rate=16000, key="meeting_sample_microphone"
            )
        else:
            sample = st.file_uploader(
                "Ses örneği dosyası",
                type=["m4a", "mp3", "wav", "webm", "mp4", "ogg", "flac"],
                key="meeting_sample_file",
            )

    consent = st.checkbox(
        "Katılımcıların ses kaydı ve bulut tabanlı yapay zekâ ile işleme için "
        "gerekli izinlerini aldım.",
        key="meeting_consent",
    )

    audio_bytes = audio.getvalue() if audio is not None else b""
    too_large = len(audio_bytes) > 180 * 1024 * 1024
    if too_large:
        st.error("Kayıt çok büyük. Daha küçük bir dosya yükleyin.")
    if audio_bytes:
        digest = hashlib.sha256(audio_bytes).hexdigest()
        if st.session_state.get("meeting_audio_hash") != digest:
            _reset()
            st.session_state["meeting_audio_hash"] = digest
        st.audio(audio_bytes, format=getattr(audio, "type", None) or "audio/wav")
        st.download_button(
            "Ses kaydını cihazıma indir",
            data=audio_bytes,
            file_name=getattr(audio, "name", "toplanti.wav"),
            mime="application/octet-stream",
            key="meeting_audio_download",
        )

    if st.button(
        "🔎 Konuşmaları yazıya dök",
        type="primary",
        key="meeting_transcribe_button",
        disabled=not (audio_bytes and consent and api_key and not too_large),
        use_container_width=True,
    ):
        try:
            with st.spinner("Ses işleniyor, konuşmacılar ayrılıyor..."):
                from openai import OpenAI
                with TemporaryDirectory(prefix="as_meeting_") as temp:
                    work = Path(temp)
                    suffix = Path(getattr(audio, "name", "") or "recording.wav").suffix.lower() or ".wav"
                    source = work / ("recording" + suffix)
                    source.write_bytes(audio_bytes)
                    parts = prepare_chunks(source, work / "parts")
                    ref = None
                    if sample is not None:
                        sample_ext = Path(getattr(sample, "name", "") or "voice.wav").suffix.lower() or ".wav"
                        voice_file = work / ("reference" + sample_ext)
                        voice_file.write_bytes(sample.getvalue())
                        ref = voice_reference(voice_file, work)
                    client = OpenAI(api_key=api_key, max_retries=2)
                    segments = transcribe_chunks(client, parts, ref)
                    st.session_state["meeting_segments"] = segments
                    st.session_state["meeting_parts"] = len(parts)
                    st.session_state["meeting_has_voice"] = bool(ref)
                    st.session_state.pop("meeting_summary", None)
                    st.session_state.pop("meeting_signature", None)
            st.success("Konuşmalar hazır. Önce sizin konuşmacı etiketinizi kontrol edin.")
        except (ValueError, TimeoutError) as error:
            st.error(str(error))
        except Exception:
            st.error("Ses işleme başarısız. Ses formatını, API ayarlarını ve bağlantıyı kontrol edin.")

    segments = st.session_state.get("meeting_segments")
    if not segments:
        st.caption(
            "Konuşmacı ayrımı kesin ses kimlik doğrulaması değildir. "
            "Fiyatları ve taahhütleri raporu kullanmadan önce kontrol edin."
        )
        return

    st.subheader("4 · Konuşmacıları kontrol et")
    speakers = sorted({segment.speaker for segment in segments})
    if st.session_state.get("meeting_parts", 1) > 1:
        st.warning(
            "Kayıt birkaç bölüme ayrıldı. B1:A, B2:A gibi konuşmacı "
            "etiketleri farklı kişileri temsil edebilir. Tek tek kontrol edin."
        )
    selected = st.multiselect(
        "Bana ait konuşmacılar",
        options=speakers,
        default=["BEN"] if "BEN" in speakers else [],
        key="meeting_speaker_selection",
        help="Emin olmadığınız bir konuşmacıyı seçmeyin.",
    )
    transcript = transcript_text(segments, set(selected), my_name.strip() or "Ben")
    mine = my_speech_text(segments, set(selected))
    tab_full, tab_mine = st.tabs(("🗣️ Tam konuşmalar", "🙋 Benim söylediklerim"))
    with tab_full:
        st.text_area("Tam transkript", value=transcript, height=320, key="meeting_transcript_preview")
        st.download_button("Transkripti indir", data=transcript, file_name="AS_toplanti_transkript.txt",
                           mime="text/plain", key="meeting_transcript_download")
    with tab_mine:
        st.text_area("Kendi konuşmalarım", value=mine or "Henüz eşleştirilen konuşmacı yok.",
                     height=260, key="meeting_mine_preview")

    metadata = {
        "Konu": title.strip() or "Belirtilmedi",
        "Firma": company.strip() or "Belirtilmedi",
        "Tarih": str(when),
        "Katılımcılar": participants.strip() or "Belirtilmedi",
        "Ben": my_name.strip() or "Ben",
    }
    signature = hashlib.sha256(
        (repr(metadata) + repr(sorted(selected)) + transcript).encode("utf-8")
    ).hexdigest()
    if st.session_state.get("meeting_summary") and st.session_state.get("meeting_signature") != signature:
        st.info("Toplantı bilgisi veya konuşmacı seçimi değişti. Özeti tekrar hazırlayın.")

    if st.button(
        "✨ Toplantı özetini ve aksiyonları hazırla",
        type="primary", key="meeting_summarize_button",
        disabled=not (api_key and consent),
        use_container_width=True,
    ):
        try:
            from openai import OpenAI
            with st.spinner("Kararlar, fiyatlar ve aksiyonlar ayrıştırılıyor..."):
                summary = summarize_meeting(
                    OpenAI(api_key=api_key, max_retries=2), transcript, metadata
                )
            st.session_state["meeting_summary"] = summary
            st.session_state["meeting_signature"] = signature
        except Exception:
            st.error("Özet oluşturulamadı. API ayarlarını ve bağlantıyı kontrol edin.")

    if st.session_state.get("meeting_summary") and st.session_state.get("meeting_signature") == signature:
        st.subheader("5 · Toplantı raporu")
        st.markdown(st.session_state["meeting_summary"])
        report = compile_report(metadata, st.session_state["meeting_summary"], transcript, mine)
        st.download_button(
            "⬇️ Tam raporu indir", report, file_name="AS_toplanti_raporu.md",
            mime="text/markdown", key="meeting_report_download",
            use_container_width=True,
        )
        st.download_button(
            "Metin sürümünü indir", report, file_name="AS_toplanti_raporu.txt",
            mime="text/plain", key="meeting_report_txt_download",
            use_container_width=True,
        )
        st.caption(
            "Toplantı raporu oturum kapanmadan indirilmeli. "
            "Ses kaydı ve konuşmalar OpenAI API'ye işleme için gönderilir."
        )
