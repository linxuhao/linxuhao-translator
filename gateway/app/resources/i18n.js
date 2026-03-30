// ==========================================
// 文件名: resources/i18n.js
// 架构定位: [Phase 5] 领域化多语言字典与渲染引擎 (全量 30 语种支持版)
// ==========================================

const SUPPORTED_LANGS = [
    {v: "zh", n: "中文 (zh)"}, {v: "en", n: "English (en)"}, {v: "yue", n: "粤语 (yue)"},
    {v: "ar", n: "العربية (ar)"}, {v: "de", n: "Deutsch (de)"}, {v: "fr", n: "Français (fr)"},
    {v: "es", n: "Español (es)"}, {v: "pt", n: "Português (pt)"}, {v: "id", n: "Bahasa Indonesia (id)"},
    {v: "it", n: "Italiano (it)"}, {v: "ko", n: "한국어 (ko)"}, {v: "ru", n: "Русский (ru)"},
    {v: "th", n: "ไทย (th)"}, {v: "vi", n: "Tiếng Việt (vi)"}, {v: "ja", n: "日本語 (ja)"},
    {v: "tr", n: "Türkçe (tr)"}, {v: "hi", n: "हिन्दी (hi)"}, {v: "ms", n: "Bahasa Melayu (ms)"},
    {v: "nl", n: "Nederlands (nl)"}, {v: "sv", n: "Svenska (sv)"}, {v: "da", n: "Dansk (da)"},
    {v: "fi", n: "Suomi (fi)"}, {v: "pl", n: "Polski (pl)"}, {v: "cs", n: "Čeština (cs)"},
    {v: "fil", n: "Filipino (fil)"}, {v: "fa", n: "فارسی (fa)"}, {v: "el", n: "Ελληνικά (el)"},
    {v: "hu", n: "Magyar (hu)"}, {v: "mk", n: "Македонски (mk)"}, {v: "ro", n: "Română (ro)"}
];

// 1. 公共组件 (Tabs, 状态栏, 全局提示)
const I18N_COMMON = {
    "zh": { tab_trans: "同传", tab_tutor: "外教", tab_record: "记录", tab_admin: "设置", status_sleep: "💤 待机中", status_listen: "👂 倾听中...", status_capture: "🎙️ 录音中...", status_speak: "🔊 播放中...", hint_encrypted: "对话已端到端加密，记录仅保存在本地" },
    "en": { tab_trans: "Translate", tab_tutor: "Tutor", tab_record: "Record", tab_admin: "Settings", status_sleep: "💤 Standby", status_listen: "👂 Listening...", status_capture: "🎙️ Recording...", status_speak: "🔊 Speaking...", hint_encrypted: "Chats encrypted, history saved locally" },
    "yue": { tab_trans: "同傳", tab_tutor: "外教", tab_record: "記錄", tab_admin: "設定", status_sleep: "💤 待機中", status_listen: "👂 聆聽中...", status_capture: "🎙️ 錄音中...", status_speak: "🔊 播放中...", hint_encrypted: "對話已加密，歷史記錄僅保存在本地" },
    "ja": { tab_trans: "翻訳", tab_tutor: "講師", tab_record: "記録", tab_admin: "設定", status_sleep: "💤 待機中", status_listen: "👂 リスニング...", status_capture: "🎙️ 録音中...", status_speak: "🔊 再生中...", hint_encrypted: "チャット暗号化済、履歴はローカル保存" },
    "fr": { tab_trans: "Traduction", tab_tutor: "Prof", tab_record: "Notes", tab_admin: "Réglages", status_sleep: "💤 En attente", status_listen: "👂 Écoute...", status_capture: "🎙️ Enregistrement...", status_speak: "🔊 Parle...", hint_encrypted: "Chats chiffrés, historique local" },
    "es": { tab_trans: "Traducir", tab_tutor: "Tutor", tab_record: "Registro", tab_admin: "Ajustes", status_sleep: "💤 En espera", status_listen: "👂 Escuchando...", status_capture: "🎙️ Grabando...", status_speak: "🔊 Hablando...", hint_encrypted: "Chats cifrados, historial local" },
    "de": { tab_trans: "Übersetzen", tab_tutor: "Tutor", tab_record: "Protokoll", tab_admin: "Einst.", status_sleep: "💤 Bereit", status_listen: "👂 Hört zu...", status_capture: "🎙️ Nimmt auf...", status_speak: "🔊 Spricht...", hint_encrypted: "Chats verschlüsselt, Verlauf lokal" },
    "pt": { tab_trans: "Traduzir", tab_tutor: "Tutor", tab_record: "Registro", tab_admin: "Ajustes", status_sleep: "💤 Em espera", status_listen: "👂 Ouvindo...", status_capture: "🎙️ Gravando...", status_speak: "🔊 Falando...", hint_encrypted: "Chats criptografados, histórico local" },
    "id": { tab_trans: "Terjemahan", tab_tutor: "Tutor", tab_record: "Catatan", tab_admin: "Pengaturan", status_sleep: "💤 Siap sedia", status_listen: "👂 Mendengarkan...", status_capture: "🎙️ Merekam...", status_speak: "🔊 Berbicara...", hint_encrypted: "Obrolan dienkripsi, riwayat lokal" },
    "it": { tab_trans: "Traduci", tab_tutor: "Tutor", tab_record: "Appunti", tab_admin: "Impost.", status_sleep: "💤 In attesa", status_listen: "👂 Ascoltando...", status_capture: "🎙️ Registrazione...", status_speak: "🔊 Parlando...", hint_encrypted: "Chat crittografate, cronologia locale" },
    "ko": { tab_trans: "번역", tab_tutor: "튜터", tab_record: "기록", tab_admin: "설정", status_sleep: "💤 대기 중", status_listen: "👂 듣는 중...", status_capture: "🎙️ 녹음 중...", status_speak: "🔊 재생 중...", hint_encrypted: "대화 암호화됨, 기록 로컬 저장" },
    "ru": { tab_trans: "Перевод", tab_tutor: "Репетитор", tab_record: "Запись", tab_admin: "Настройки", status_sleep: "💤 Ожидание", status_listen: "👂 Слушаю...", status_capture: "🎙️ Запись...", status_speak: "🔊 Говорю...", hint_encrypted: "Чаты зашифрованы, история локальна" },
    "th": { tab_trans: "แปล", tab_tutor: "ติวเตอร์", tab_record: "บันทึก", tab_admin: "ตั้งค่า", status_sleep: "💤 สแตนด์บาย", status_listen: "👂 กำลังฟัง...", status_capture: "🎙️ กำลังบันทึก...", status_speak: "🔊 กำลังพูด...", hint_encrypted: "แชทเข้ารหัส ประวัติบันทึกในเครื่อง" },
    "vi": { tab_trans: "Dịch", tab_tutor: "Gia sư", tab_record: "Ghi chép", tab_admin: "Cài đặt", status_sleep: "💤 Sẵn sàng", status_listen: "👂 Đang nghe...", status_capture: "🎙️ Đang thu...", status_speak: "🔊 Đang nói...", hint_encrypted: "Chat mã hóa, lịch sử lưu cục bộ" },
    "tr": { tab_trans: "Çeviri", tab_tutor: "Eğitmen", tab_record: "Kayıt", tab_admin: "Ayarlar", status_sleep: "💤 Beklemede", status_listen: "👂 Dinleniyor...", status_capture: "🎙️ Kaydediliyor...", status_speak: "🔊 Konuşuluyor...", hint_encrypted: "Sohbetler şifreli, geçmiş yerel" },
    "ar": { tab_trans: "ترجمة", tab_tutor: "معلم", tab_record: "سجل", tab_admin: "إعدادات", status_sleep: "💤 وضع الاستعداد", status_listen: "👂 يستمع...", status_capture: "🎙️ يسجل...", status_speak: "🔊 يتحدث...", hint_encrypted: "المحادثات مشفرة، السجل محلي" },
    "hi": { tab_trans: "अनुवाद", tab_tutor: "शिक्षक", tab_record: "रिकॉर्ड", tab_admin: "सेटिंग्स", status_sleep: "💤 तैयार", status_listen: "👂 सुन रहा है...", status_capture: "🎙️ रिकॉर्डिंग...", status_speak: "🔊 बोल रहा है...", hint_encrypted: "चैट एन्क्रिप्टेड, इतिहास स्थानीय" },
    "ms": { tab_trans: "Terjemah", tab_tutor: "Tutor", tab_record: "Rekod", tab_admin: "Tetapan", status_sleep: "💤 Sedia", status_listen: "👂 Mendengar...", status_capture: "🎙️ Merakam...", status_speak: "🔊 Bercakap...", hint_encrypted: "Sembang disulitkan, sejarah tempatan" },
    "nl": { tab_trans: "Vertalen", tab_tutor: "Docent", tab_record: "Notities", tab_admin: "Instellingen", status_sleep: "💤 Stand-by", status_listen: "👂 Luisteren...", status_capture: "🎙️ Opnemen...", status_speak: "🔊 Spreken...", hint_encrypted: "Chats versleuteld, lokale geschiedenis" },
    "sv": { tab_trans: "Översätt", tab_tutor: "Lärare", tab_record: "Anteckningar", tab_admin: "Inställningar", status_sleep: "💤 Redo", status_listen: "👂 Lyssnar...", status_capture: "🎙️ Spelar in...", status_speak: "🔊 Talar...", hint_encrypted: "Chattar krypterade, lokal historik" },
    "da": { tab_trans: "Oversæt", tab_tutor: "Tutor", tab_record: "Noter", tab_admin: "Indstillinger", status_sleep: "💤 Klar", status_listen: "👂 Lytter...", status_capture: "🎙️ Optager...", status_speak: "🔊 Taler...", hint_encrypted: "Chats krypteret, lokal historik" },
    "fi": { tab_trans: "Käännä", tab_tutor: "Opettaja", tab_record: "Muistiinpanot", tab_admin: "Asetukset", status_sleep: "💤 Valmiina", status_listen: "👂 Kuunnellaan...", status_capture: "🎙️ Nauhoitetaan...", status_speak: "🔊 Puhutaan...", hint_encrypted: "Chatit salattu, paikallinen historia" },
    "pl": { tab_trans: "Tłumacz", tab_tutor: "Nauczyciel", tab_record: "Zapis", tab_admin: "Ustawienia", status_sleep: "💤 Gotowy", status_listen: "👂 Słuchanie...", status_capture: "🎙️ Nagrywanie...", status_speak: "🔊 Mówienie...", hint_encrypted: "Czaty zaszyfrowane, historia lokalna" },
    "cs": { tab_trans: "Překlad", tab_tutor: "Lektor", tab_record: "Záznam", tab_admin: "Nastavení", status_sleep: "💤 Připraven", status_listen: "👂 Poslouchám...", status_capture: "🎙️ Nahrávání...", status_speak: "🔊 Mluvím...", hint_encrypted: "Chaty šifrovány, lokální historie" },
    "fil": { tab_trans: "Isalin", tab_tutor: "Tutor", tab_record: "Record", tab_admin: "Mga Setting", status_sleep: "💤 Standby", status_listen: "👂 Nakikinig...", status_capture: "🎙️ Nagre-record...", status_speak: "🔊 Nagsasalita...", hint_encrypted: "Naka-encrypt na chat, lokal na history" },
    "fa": { tab_trans: "ترجمه", tab_tutor: "معلم", tab_record: "ثبت", tab_admin: "تنظیمات", status_sleep: "💤 آماده به کار", status_listen: "👂 در حال شنیدن...", status_capture: "🎙️ در حال ضبط...", status_speak: "🔊 در حال صحبت...", hint_encrypted: "چت رمزگذاری شده، تاریخچه محلی" },
    "el": { tab_trans: "Μετάφραση", tab_tutor: "Καθηγητής", tab_record: "Καταγραφή", tab_admin: "Ρυθμίσεις", status_sleep: "💤 Σε Αναμονή", status_listen: "👂 Ακούει...", status_capture: "🎙️ Εγγραφή...", status_speak: "🔊 Μιλάει...", hint_encrypted: "Κρυπτογραφημένα, τοπικό ιστορικό" },
    "hu": { tab_trans: "Fordítás", tab_tutor: "Oktató", tab_record: "Jegyzet", tab_admin: "Beállítások", status_sleep: "💤 Készenlét", status_listen: "👂 Figyelés...", status_capture: "🎙️ Felvétel...", status_speak: "🔊 Beszéd...", hint_encrypted: "Titkosított chatek, helyi előzmények" },
    "mk": { tab_trans: "Преведи", tab_tutor: "Тутор", tab_record: "Запис", tab_admin: "Поставки", status_sleep: "💤 Подготвен", status_listen: "👂 Слушам...", status_capture: "🎙️ Снимам...", status_speak: "🔊 Зборувам...", hint_encrypted: "Шифрирани разговори, локална историја" },
    "ro": { tab_trans: "Traducere", tab_tutor: "Profesor", tab_record: "Note", tab_admin: "Setări", status_sleep: "💤 În așteptare", status_listen: "👂 Ascultă...", status_capture: "🎙️ Înregistrare...", status_speak: "🔊 Vorbește...", hint_encrypted: "Chat criptat, istoric local" }
};

// 2. 同传业务
const I18N_TRANSLATOR = {
    "zh": { title: "🗣️ 随身翻译", btn_start: "🎙️" },
    "en": { title: "🗣️ Translator", btn_start: "🎙️" },
    "yue": { title: "🗣️ 隨身翻譯", btn_start: "🎙️" },
    "ja": { title: "🗣️ 翻訳機", btn_start: "🎙️" },
    "fr": { title: "🗣️ Traducteur", btn_start: "🎙️" },
    "es": { title: "🗣️ Traductor", btn_start: "🎙️" },
    "de": { title: "🗣️ Übersetzer", btn_start: "🎙️" },
    "pt": { title: "🗣️ Tradutor", btn_start: "🎙️" },
    "id": { title: "🗣️ Penerjemah", btn_start: "🎙️" },
    "it": { title: "🗣️ Traduttore", btn_start: "🎙️" },
    "ko": { title: "🗣️ 번역기", btn_start: "🎙️" },
    "ru": { title: "🗣️ Переводчик", btn_start: "🎙️" },
    "th": { title: "🗣️ นักแปล", btn_start: "🎙️" },
    "vi": { title: "🗣️ Trình dịch", btn_start: "🎙️" },
    "tr": { title: "🗣️ Çevirmen", btn_start: "🎙️" },
    "ar": { title: "🗣️ المترجم", btn_start: "🎙️" },
    "hi": { title: "🗣️ अनुवादक", btn_start: "🎙️" },
    "ms": { title: "🗣️ Penterjemah", btn_start: "🎙️" },
    "nl": { title: "🗣️ Vertaler", btn_start: "🎙️" },
    "sv": { title: "🗣️ Översättare", btn_start: "🎙️" },
    "da": { title: "🗣️ Oversætter", btn_start: "🎙️" },
    "fi": { title: "🗣️ Kääntäjä", btn_start: "🎙️" },
    "pl": { title: "🗣️ Tłumacz", btn_start: "🎙️" },
    "cs": { title: "🗣️ Překladatel", btn_start: "🎙️" },
    "fil": { title: "🗣️ Tagasalin", btn_start: "🎙️" },
    "fa": { title: "🗣️ مترجم", btn_start: "🎙️" },
    "el": { title: "🗣️ Μεταφραστής", btn_start: "🎙️" },
    "hu": { title: "🗣️ Fordító", btn_start: "🎙️" },
    "mk": { title: "🗣️ Преведувач", btn_start: "🎙️" },
    "ro": { title: "🗣️ Traducător", btn_start: "🎙️" }
};

// 3. 外教业务
const I18N_TUTOR = {
    "zh": { title_tutor: "👨‍🏫 AI 外教", status_speak_tutor: "🔊 讲话中 (可随时打断)...", btn_native_on: "💡 双语教学: 开", btn_native_off: "💡 双语教学: 关" },
    "en": { title_tutor: "👨‍🏫 AI Tutor", status_speak_tutor: "🔊 Speaking (Interruptible)...", btn_native_on: "💡 Bilingual Mode: On", btn_native_off: "💡 Bilingual Mode: Off" },
    "yue": { title_tutor: "👨‍🏫 AI 外教", status_speak_tutor: "🔊 講話中 (可隨時打斷)...", btn_native_on: "💡 雙語教學: 開", btn_native_off: "💡 雙語教學: 關" },
    "ja": { title_tutor: "👨‍🏫 AI 講師", status_speak_tutor: "🔊 再生中 (割り込み可能)...", btn_native_on: "💡 バイリンガルモード: オン", btn_native_off: "💡 バイリンガルモード: オフ" },
    "fr": { title_tutor: "👨‍🏫 Prof IA", status_speak_tutor: "🔊 Parle (Interruption possible)...", btn_native_on: "💡 Mode Bilingue : ON", btn_native_off: "💡 Mode Bilingue : OFF" },
    "es": { title_tutor: "👨‍🏫 Tutor IA", status_speak_tutor: "🔊 Hablando (Puede interrumpir)...", btn_native_on: "💡 Modo Bilingüe: ON", btn_native_off: "💡 Modo Bilingüe: OFF" },
    "de": { title_tutor: "👨‍🏫 KI-Tutor", status_speak_tutor: "🔊 Spricht (Unterbrechen möglich)...", btn_native_on: "💡 Zweisprachig: An", btn_native_off: "💡 Zweisprachig: Aus" },
    "pt": { title_tutor: "👨‍🏫 Tutor IA", status_speak_tutor: "🔊 Falando (Pode interromper)...", btn_native_on: "💡 Modo Bilíngue: ON", btn_native_off: "💡 Modo Bilíngue: OFF" },
    "id": { title_tutor: "👨‍🏫 Tutor AI", status_speak_tutor: "🔊 Berbicara (Bisa disela)...", btn_native_on: "💡 Mode Dwibahasa: Nyala", btn_native_off: "💡 Mode Dwibahasa: Mati" },
    "it": { title_tutor: "👨‍🏫 Tutor IA", status_speak_tutor: "🔊 Parlando (Interrompibile)...", btn_native_on: "💡 Modo Bilingue: ON", btn_native_off: "💡 Modo Bilingue: OFF" },
    "ko": { title_tutor: "👨‍🏫 AI 튜터", status_speak_tutor: "🔊 말하는 중 (끼어들기 가능)...", btn_native_on: "💡 이중언어 모드: 켜짐", btn_native_off: "💡 이중언어 모드: 꺼짐" },
    "ru": { title_tutor: "👨‍🏫 ИИ-Репетитор", status_speak_tutor: "🔊 Говорю (Можно перебить)...", btn_native_on: "💡 Двуязычный режим: Вкл", btn_native_off: "💡 Двуязычный режим: Выкл" },
    "th": { title_tutor: "👨‍🏫 AI ติวเตอร์", status_speak_tutor: "🔊 กำลังพูด (พูดแทรกได้)...", btn_native_on: "💡 โหมดสองภาษา: เปิด", btn_native_off: "💡 โหมดสองภาษา: ปิด" },
    "vi": { title_tutor: "👨‍🏫 Gia sư AI", status_speak_tutor: "🔊 Đang nói (Có thể ngắt lời)...", btn_native_on: "💡 Chế độ Song ngữ: Bật", btn_native_off: "💡 Chế độ Song ngữ: Tắt" },
    "tr": { title_tutor: "👨‍🏫 Yapay Zeka Eğitmeni", status_speak_tutor: "🔊 Konuşuluyor (Söze girilebilir)...", btn_native_on: "💡 İki Dilli Mod: Açık", btn_native_off: "💡 İki Dilli Mod: Kapalı" },
    "ar": { title_tutor: "👨‍🏫 المعلم الذكي", status_speak_tutor: "🔊 يتحدث (يمكنك المقاطعة)...", btn_native_on: "💡 وضع ثنائي اللغة: تشغيل", btn_native_off: "💡 وضع ثنائي اللغة: إيقاف" },
    "hi": { title_tutor: "👨‍🏫 AI ट्यूटर", status_speak_tutor: "🔊 बोल रहा है (बीच में टोकें)...", btn_native_on: "💡 द्विभाषी मोड: चालू", btn_native_off: "💡 द्विभाषी मोड: बंद" },
    "ms": { title_tutor: "👨‍🏫 Tutor AI", status_speak_tutor: "🔊 Bercakap (Boleh sampuk)...", btn_native_on: "💡 Mod Dwibahasa: Hidup", btn_native_off: "💡 Mod Dwibahasa: Mati" },
    "nl": { title_tutor: "👨‍🏫 AI Docent", status_speak_tutor: "🔊 Spreken (Onderbreken mogelijk)...", btn_native_on: "💡 Tweetalige Modus: Aan", btn_native_off: "💡 Tweetalige Modus: Uit" },
    "sv": { title_tutor: "👨‍🏫 AI Lärare", status_speak_tutor: "🔊 Talar (Avbrytbar)...", btn_native_on: "💡 Tvåspråkigt Läge: På", btn_native_off: "💡 Tvåspråkigt Läge: Av" },
    "da": { title_tutor: "👨‍🏫 AI Tutor", status_speak_tutor: "🔊 Taler (Kan afbrydes)...", btn_native_on: "💡 Tosproget Tilstand: Til", btn_native_off: "💡 Tosproget Tilstand: Fra" },
    "fi": { title_tutor: "👨‍🏫 AI Opettaja", status_speak_tutor: "🔊 Puhuu (Keskeytettävissä)...", btn_native_on: "💡 Kaksikielinen Tila: Päällä", btn_native_off: "💡 Kaksikielinen Tila: Pois" },
    "pl": { title_tutor: "👨‍🏫 Nauczyciel AI", status_speak_tutor: "🔊 Mówi (Można przerwać)...", btn_native_on: "💡 Tryb Dwujęzyczny: Wł", btn_native_off: "💡 Tryb Dwujęzyczny: Wył" },
    "cs": { title_tutor: "👨‍🏫 AI Lektor", status_speak_tutor: "🔊 Mluví (Lze přerušit)...", btn_native_on: "💡 Bilingvní Režim: Zap", btn_native_off: "💡 Bilingvní Režim: Vyp" },
    "fil": { title_tutor: "👨‍🏫 AI Tutor", status_speak_tutor: "🔊 Nagsasalita (Pwedeng sumingit)...", btn_native_on: "💡 Bilingual Mode: On", btn_native_off: "💡 Bilingual Mode: Off" },
    "fa": { title_tutor: "👨‍🏫 معلم هوش مصنوعی", status_speak_tutor: "🔊 در حال صحبت (امکان قطع)...", btn_native_on: "💡 حالت دوزبانه: روشن", btn_native_off: "💡 حالت دوزبانه: خاموش" },
    "el": { title_tutor: "👨‍🏫 AI Καθηγητής", status_speak_tutor: "🔊 Μιλάει (Διακοπή δυνατή)...", btn_native_on: "💡 Δίγλωσση Λειτουργία: On", btn_native_off: "💡 Δίγλωσση Λειτουργία: Off" },
    "hu": { title_tutor: "👨‍🏫 AI Oktató", status_speak_tutor: "🔊 Beszéd (Félbeszakítható)...", btn_native_on: "💡 Kétnyelvű Mód: Be", btn_native_off: "💡 Kétnyelvű Mód: Ki" },
    "mk": { title_tutor: "👨‍🏫 AI Тутор", status_speak_tutor: "🔊 Зборувам (Може да се прекине)...", btn_native_on: "💡 Двојазичен Режим: Вкл", btn_native_off: "💡 Двојазичен Режим: Искл" },
    "ro": { title_tutor: "👨‍🏫 Tutor AI", status_speak_tutor: "🔊 Vorbește (Poate fi întrerupt)...", btn_native_on: "💡 Mod Bilingv: Pornit", btn_native_off: "💡 Mod Bilingv: Oprit" }
};

// 4. 会议记录业务 
const I18N_RECORD = {
    "zh": { title_record: "📝 会议记录", hint_record: "点击下方按钮开始持续监听", btn_new: "➕ 新建", btn_files: "📂 历史", modal_files_title: "本地会议记录", msg_empty_files: "暂无保存的记录", prompt_rename: "请输入新的会议名称：", prompt_delete: "确定删除此记录吗？不可恢复。", btn_export: "📄 导出", btn_clear: "🗑️ 清空", btn_load: "加载", btn_active: "当前", prompt_clear_all: "确认清空所有会议记录？（不可恢复）", msg_empty_export: "暂无记录可导出", default_meeting_name: "会议", word_items: "条记录", title_rename: "点击重命名", msg_storage_full: "本地存储空间已满，请导出并删除一些旧记录。" },
    "en": { title_record: "📝 Transcript", hint_record: "Tap below to start continuous listening", btn_new: "➕ New", btn_files: "📂 Files", modal_files_title: "Local Transcripts", msg_empty_files: "No saved records", prompt_rename: "Enter new meeting name:", prompt_delete: "Delete this record permanently?", btn_export: "📄 Export", btn_clear: "🗑️ Clear", btn_load: "Load", btn_active: "Active", prompt_clear_all: "Clear all meeting records? (Cannot be undone)", msg_empty_export: "No transcript to export", default_meeting_name: "Meeting", word_items: "items", title_rename: "Click to rename", msg_storage_full: "Local storage full. Please export and delete old records." },
    "yue": { title_record: "📝 會議記錄", hint_record: "點擊下方按鈕開始持續監聽", btn_new: "➕ 新建", btn_files: "📂 歷史", modal_files_title: "本地會議記錄", msg_empty_files: "暫無保存的記錄", prompt_rename: "請輸入新的會議名稱：", prompt_delete: "確定刪除此記錄嗎？不可恢復。", btn_export: "📄 導出", btn_clear: "🗑️ 清空", btn_load: "加載", btn_active: "當前", prompt_clear_all: "確認清空所有會議記錄？（不可恢復）", msg_empty_export: "暫無記錄可導出", default_meeting_name: "會議", word_items: "條記錄", title_rename: "點擊重命名", msg_storage_full: "本地存儲空間已滿，請導出並刪除一些舊記錄。" },
    "ja": { title_record: "📝 議事録", hint_record: "下をタップして連続リスニングを開始", btn_new: "➕ 新規", btn_files: "📂 履歴", modal_files_title: "ローカル議事録", msg_empty_files: "記録がありません", prompt_rename: "新しい会議名を入力:", prompt_delete: "完全に削除しますか？", btn_export: "📄 出力", btn_clear: "🗑️ クリア", btn_load: "読込", btn_active: "現在", prompt_clear_all: "すべての記録をクリアしますか？", msg_empty_export: "出力する記録がありません", default_meeting_name: "会議", word_items: "件", title_rename: "名前を変更", msg_storage_full: "ストレージがいっぱいです。古い記録を削除してください。" },
    "fr": { title_record: "📝 Transcription", hint_record: "Appuyez pour écouter en continu", btn_new: "➕ Nouveau", btn_files: "📂 Fichiers", modal_files_title: "Transcriptions locales", msg_empty_files: "Aucun enregistrement", prompt_rename: "Nouveau nom :", prompt_delete: "Supprimer définitivement ?", btn_export: "📄 Exporter", btn_clear: "🗑️ Effacer", btn_load: "Charger", btn_active: "Actif", prompt_clear_all: "Effacer tout ? (Irréversible)", msg_empty_export: "Rien à exporter", default_meeting_name: "Réunion", word_items: "éléments", title_rename: "Renommer", msg_storage_full: "Stockage plein. Veuillez exporter et supprimer d'anciens fichiers." },
    "es": { title_record: "📝 Transcripción", hint_record: "Toque para escuchar continuamente", btn_new: "➕ Nuevo", btn_files: "📂 Archivos", modal_files_title: "Registros locales", msg_empty_files: "Sin registros", prompt_rename: "Nuevo nombre:", prompt_delete: "¿Eliminar permanentemente?", btn_export: "📄 Exportar", btn_clear: "🗑️ Borrar", btn_load: "Cargar", btn_active: "Actual", prompt_clear_all: "¿Borrar todos los registros?", msg_empty_export: "Nada que exportar", default_meeting_name: "Reunión", word_items: "elementos", title_rename: "Renombrar", msg_storage_full: "Almacenamiento lleno. Exporte y elimine registros antiguos." },
    "de": { title_record: "📝 Protokoll", hint_record: "Tippen zum kontinuierlichen Zuhören", btn_new: "➕ Neu", btn_files: "📂 Dateien", modal_files_title: "Lokale Protokolle", msg_empty_files: "Keine Datensätze", prompt_rename: "Neuer Name:", prompt_delete: "Endgültig löschen?", btn_export: "📄 Export", btn_clear: "🗑️ Leeren", btn_load: "Laden", btn_active: "Aktiv", prompt_clear_all: "Alle Protokolle unwiderruflich löschen?", msg_empty_export: "Nichts zu exportieren", default_meeting_name: "Meeting", word_items: "Einträge", title_rename: "Umbenennen", msg_storage_full: "Speicher voll. Bitte alte Protokolle exportieren und löschen." },
    "pt": { title_record: "📝 Transcrição", hint_record: "Toque abaixo para ouvir continuamente", btn_new: "➕ Novo", btn_files: "📂 Arquivos", modal_files_title: "Registros locais", msg_empty_files: "Sem registros", prompt_rename: "Novo nome:", prompt_delete: "¿Excluir permanentemente?", btn_export: "📄 Exportar", btn_clear: "🗑️ Apagar", btn_load: "Carregar", btn_active: "Atual", prompt_clear_all: "¿Apagar todos os registros?", msg_empty_export: "Nada para exportar", default_meeting_name: "Reunião", word_items: "itens", title_rename: "Renomear", msg_storage_full: "Armazenamento cheio. Exporte e apague registros antigos." },
    "id": { title_record: "📝 Transkrip", hint_record: "Ketuk di bawah untuk mulai mendengarkan", btn_new: "➕ Baru", btn_files: "📂 File", modal_files_title: "Transkrip Lokal", msg_empty_files: "Tidak ada catatan", prompt_rename: "Masukkan nama baru:", prompt_delete: "Hapus catatan ini permanen?", btn_export: "📄 Ekspor", btn_clear: "🗑️ Bersihkan", btn_load: "Muat", btn_active: "Aktif", prompt_clear_all: "Bersihkan semua catatan?", msg_empty_export: "Tidak ada yang bisa diekspor", default_meeting_name: "Rapat", word_items: "item", title_rename: "Ganti nama", msg_storage_full: "Penyimpanan penuh. Harap ekspor dan hapus file lama." },
    "it": { title_record: "📝 Trascrizione", hint_record: "Tocca in basso per ascolto continuo", btn_new: "➕ Nuovo", btn_files: "📂 File", modal_files_title: "Trascrizioni locali", msg_empty_files: "Nessun record", prompt_rename: "Nuovo nome:", prompt_delete: "Eliminare definitivamente?", btn_export: "📄 Esporta", btn_clear: "🗑️ Svuota", btn_load: "Carica", btn_active: "Attivo", prompt_clear_all: "Svuotare tutti i record?", msg_empty_export: "Niente da esportare", default_meeting_name: "Riunione", word_items: "elementi", title_rename: "Rinomina", msg_storage_full: "Memoria piena. Esporta e cancella i vecchi record." },
    "ko": { title_record: "📝 회의록", hint_record: "아래를 눌러 연속 듣기 시작", btn_new: "➕ 새 파일", btn_files: "📂 파일", modal_files_title: "로컬 회의록", msg_empty_files: "저장된 기록 없음", prompt_rename: "새 회의 이름 입력:", prompt_delete: "영구적으로 삭제하시겠습니까?", btn_export: "📄 내보내기", btn_clear: "🗑️ 지우기", btn_load: "불러오기", btn_active: "현재", prompt_clear_all: "모든 기록을 지우시겠습니까?", msg_empty_export: "내보낼 기록이 없습니다", default_meeting_name: "회의", word_items: "항목", title_rename: "이름 변경", msg_storage_full: "저장소 용량이 꽉 찼습니다. 오래된 기록을 삭제하세요." },
    "ru": { title_record: "📝 Транскрипция", hint_record: "Нажмите ниже для непрерывного прослушивания", btn_new: "➕ Новый", btn_files: "📂 Файлы", modal_files_title: "Локальные записи", msg_empty_files: "Нет сохраненных записей", prompt_rename: "Новое название:", prompt_delete: "Удалить запись навсегда?", btn_export: "📄 Экспорт", btn_clear: "🗑️ Очистить", btn_load: "Загрузить", btn_active: "Текущий", prompt_clear_all: "Очистить все записи?", msg_empty_export: "Нет данных для экспорта", default_meeting_name: "Встреча", word_items: "записей", title_rename: "Переименовать", msg_storage_full: "Память заполнена. Пожалуйста, удалите старые записи." },
    "th": { title_record: "📝 บันทึกการประชุม", hint_record: "แตะด้านล่างเพื่อเริ่มฟังอย่างต่อเนื่อง", btn_new: "➕ ใหม่", btn_files: "📂 ไฟล์", modal_files_title: "บันทึกในเครื่อง", msg_empty_files: "ไม่มีบันทึก", prompt_rename: "ใส่ชื่อการประชุมใหม่:", prompt_delete: "ลบบันทึกนี้อย่างถาวรหรือไม่?", btn_export: "📄 ส่งออก", btn_clear: "🗑️ ล้าง", btn_load: "โหลด", btn_active: "ปัจจุบัน", prompt_clear_all: "ล้างบันทึกทั้งหมดหรือไม่?", msg_empty_export: "ไม่มีข้อมูลให้ส่งออก", default_meeting_name: "การประชุม", word_items: "รายการ", title_rename: "เปลี่ยนชื่อ", msg_storage_full: "พื้นที่จัดเก็บเต็ม โปรดลบบันทึกเก่า" },
    "vi": { title_record: "📝 Bản ghi", hint_record: "Chạm vào bên dưới để nghe liên tục", btn_new: "➕ Mới", btn_files: "📂 Tệp", modal_files_title: "Bản ghi cục bộ", msg_empty_files: "Không có bản ghi", prompt_rename: "Nhập tên mới:", prompt_delete: "Xóa vĩnh viễn bản ghi này?", btn_export: "📄 Xuất", btn_clear: "🗑️ Xóa", btn_load: "Tải", btn_active: "Hiện tại", prompt_clear_all: "Xóa tất cả bản ghi?", msg_empty_export: "Không có dữ liệu để xuất", default_meeting_name: "Cuộc họp", word_items: "mục", title_rename: "Đổi tên", msg_storage_full: "Bộ nhớ đầy. Vui lòng xuất và xóa các tệp cũ." },
    "tr": { title_record: "📝 Transkript", hint_record: "Sürekli dinleme için aşağıya dokunun", btn_new: "➕ Yeni", btn_files: "📂 Dosyalar", modal_files_title: "Yerel Kayıtlar", msg_empty_files: "Kayıt bulunamadı", prompt_rename: "Yeni ad girin:", prompt_delete: "Kalıcı olarak silinsin mi?", btn_export: "📄 Dışa Aktar", btn_clear: "🗑️ Temizle", btn_load: "Yükle", btn_active: "Aktif", prompt_clear_all: "Tüm kayıtlar silinsin mi?", msg_empty_export: "Dışa aktarılacak kayıt yok", default_meeting_name: "Toplantı", word_items: "öğe", title_rename: "Yeniden adlandır", msg_storage_full: "Depolama dolu. Lütfen eski kayıtları silin." },
    "ar": { title_record: "📝 سجل الاجتماع", hint_record: "اضغط أدناه لبدء الاستماع المستمر", btn_new: "➕ جديد", btn_files: "📂 ملفات", modal_files_title: "سجلات محلية", msg_empty_files: "لا توجد سجلات", prompt_rename: "أدخل الاسم الجديد:", prompt_delete: "حذف هذا السجل نهائيًا؟", btn_export: "📄 تصدير", btn_clear: "🗑️ مسح", btn_load: "تحميل", btn_active: "الحالي", prompt_clear_all: "مسح جميع السجلات؟", msg_empty_export: "لا يوجد شيء للتصدير", default_meeting_name: "اجتماع", word_items: "عنصر", title_rename: "إعادة تسمية", msg_storage_full: "المساحة ممتلئة. يرجى حذف السجلات القديمة." },
    "hi": { title_record: "📝 ट्रांसक्रिप्ट", hint_record: "लगातार सुनने के लिए नीचे टैप करें", btn_new: "➕ नया", btn_files: "📂 फ़ाइलें", modal_files_title: "स्थानीय रिकॉर्ड", msg_empty_files: "कोई रिकॉर्ड नहीं", prompt_rename: "नया नाम दर्ज करें:", prompt_delete: "स्थायी रूप से हटा दें?", btn_export: "📄 निर्यात", btn_clear: "🗑️ साफ़ करें", btn_load: "लोड", btn_active: "सक्रिय", prompt_clear_all: "सभी रिकॉर्ड साफ़ करें?", msg_empty_export: "निर्यात करने के लिए कुछ नहीं", default_meeting_name: "मीटिंग", word_items: "आइटम", title_rename: "नाम बदलें", msg_storage_full: "स्टोरेज फुल हो गया है। कृपया पुराने रिकॉर्ड हटाएँ।" },
    "ms": { title_record: "📝 Transkrip", hint_record: "Ketik di bawah untuk mula mendengar", btn_new: "➕ Baru", btn_files: "📂 Fail", modal_files_title: "Transkrip Tempatan", msg_empty_files: "Tiada rekod disimpan", prompt_rename: "Masukkan nama baharu:", prompt_delete: "Padam rekod ini secara kekal?", btn_export: "📄 Eksport", btn_clear: "🗑️ Padam", btn_load: "Muat", btn_active: "Aktif", prompt_clear_all: "Padam semua rekod?", msg_empty_export: "Tiada data untuk dieksport", default_meeting_name: "Mesyuarat", word_items: "item", title_rename: "Namakan semula", msg_storage_full: "Storan penuh. Sila eksport dan padam rekod lama." },
    "nl": { title_record: "📝 Transcriptie", hint_record: "Tik hieronder om continu te luisteren", btn_new: "➕ Nieuw", btn_files: "📂 Bestanden", modal_files_title: "Lokale Bestanden", msg_empty_files: "Geen opgeslagen records", prompt_rename: "Nieuwe naam:", prompt_delete: "Definitief verwijderen?", btn_export: "📄 Exporteren", btn_clear: "🗑️ Wissen", btn_load: "Laden", btn_active: "Actief", prompt_clear_all: "Alle records wissen?", msg_empty_export: "Niets om te exporteren", default_meeting_name: "Vergadering", word_items: "items", title_rename: "Hernoemen", msg_storage_full: "Opslag vol. Exporteer en verwijder oude records." },
    "sv": { title_record: "📝 Utskrift", hint_record: "Tryck nedan för kontinuerlig lyssning", btn_new: "➕ Ny", btn_files: "📂 Filer", modal_files_title: "Lokala utskrifter", msg_empty_files: "Inga sparade poster", prompt_rename: "Nytt namn:", prompt_delete: "Ta bort permanent?", btn_export: "📄 Exportera", btn_clear: "🗑️ Rensa", btn_load: "Ladda", btn_active: "Aktiv", prompt_clear_all: "Rensa alla poster?", msg_empty_export: "Inget att exportera", default_meeting_name: "Möte", word_items: "objekt", title_rename: "Byt namn", msg_storage_full: "Lagringen är full. Vänligen ta bort gamla poster." },
    "da": { title_record: "📝 Udskrift", hint_record: "Tryk forneden for at lytte kontinuerligt", btn_new: "➕ Ny", btn_files: "📂 Filer", modal_files_title: "Lokale udskrifter", msg_empty_files: "Ingen gemte poster", prompt_rename: "Nyt navn:", prompt_delete: "Slet permanent?", btn_export: "📄 Eksporter", btn_clear: "🗑️ Ryd", btn_load: "Indlæs", btn_active: "Aktiv", prompt_clear_all: "Ryd alle poster?", msg_empty_export: "Intet at eksportere", default_meeting_name: "Møde", word_items: "emner", title_rename: "Omdøb", msg_storage_full: "Lagerplads fuld. Slet venligst gamle poster." },
    "fi": { title_record: "📝 Literaatio", hint_record: "Napauta alta jatkuvaa kuuntelua varten", btn_new: "➕ Uusi", btn_files: "📂 Tiedostot", modal_files_title: "Paikalliset tallenteet", msg_empty_files: "Ei tallenteita", prompt_rename: "Uusi nimi:", prompt_delete: "Poistetaanko pysyvästi?", btn_export: "📄 Vie", btn_clear: "🗑️ Tyhjennä", btn_load: "Lataa", btn_active: "Aktiivinen", prompt_clear_all: "Tyhjennetäänkö kaikki?", msg_empty_export: "Ei vietyävää", default_meeting_name: "Kokous", word_items: "kohdetta", title_rename: "Nimeä uudelleen", msg_storage_full: "Tallennustila täynnä. Poista vanhoja tiedostoja." },
    "pl": { title_record: "📝 Transkrypcja", hint_record: "Dotknij poniżej, aby rozpocząć ciągłe słuchanie", btn_new: "➕ Nowy", btn_files: "📂 Pliki", modal_files_title: "Lokalne nagrania", msg_empty_files: "Brak zapisanych nagrań", prompt_rename: "Nowa nazwa:", prompt_delete: "Usunąć trwale?", btn_export: "📄 Eksport", btn_clear: "🗑️ Wyczyść", btn_load: "Wczytaj", btn_active: "Aktywny", prompt_clear_all: "Wyczyścić wszystkie nagrania?", msg_empty_export: "Brak danych do eksportu", default_meeting_name: "Spotkanie", word_items: "el.", title_rename: "Zmień nazwę", msg_storage_full: "Brak pamięci. Usuń stare pliki." },
    "cs": { title_record: "📝 Přepis", hint_record: "Klepnutím níže zahájíte nepřetržitý poslech", btn_new: "➕ Nový", btn_files: "📂 Soubory", modal_files_title: "Lokální záznamy", msg_empty_files: "Žádné záznamy", prompt_rename: "Nové jméno:", prompt_delete: "Trvale smazat?", btn_export: "📄 Exportovat", btn_clear: "🗑️ Vymazat", btn_load: "Načíst", btn_active: "Aktivní", prompt_clear_all: "Vymazat všechny záznamy?", msg_empty_export: "Žádná data k exportu", default_meeting_name: "Schůzka", word_items: "pol.", title_rename: "Přejmenovat", msg_storage_full: "Úložiště plné. Prosím smažte staré soubory." },
    "fil": { title_record: "📝 Transcript", hint_record: "I-tap sa ibaba para sa tuluy-tuloy na pakikinig", btn_new: "➕ Bago", btn_files: "📂 Files", modal_files_title: "Lokal na Records", msg_empty_files: "Walang records", prompt_rename: "Bagong pangalan:", prompt_delete: "Permamenteng burahin?", btn_export: "📄 I-export", btn_clear: "🗑️ I-clear", btn_load: "I-load", btn_active: "Aktibo", prompt_clear_all: "Burahin lahat?", msg_empty_export: "Walang data na i-export", default_meeting_name: "Meeting", word_items: "mga item", title_rename: "Palitan ang pangalan", msg_storage_full: "Puno na ang storage. Paki-delete ng mga lumang files." },
    "fa": { title_record: "📝 متن جلسات", hint_record: "برای گوش دادن پیوسته پایین را لمس کنید", btn_new: "➕ جدید", btn_files: "📂 فایل‌ها", modal_files_title: "سوابق محلی", msg_empty_files: "هیچ رکوردی ذخیره نشده", prompt_rename: "نام جدید را وارد کنید:", prompt_delete: "آیا برای همیشه حذف شود؟", btn_export: "📄 خروجی", btn_clear: "🗑️ پاک کردن", btn_load: "بارگذاری", btn_active: "فعال", prompt_clear_all: "همه سوابق پاک شوند؟", msg_empty_export: "داده‌ای برای خروجی نیست", default_meeting_name: "جلسه", word_items: "مورد", title_rename: "تغییر نام", msg_storage_full: "حافظه پر است. لطفاً سوابق قدیمی را حذف کنید." },
    "el": { title_record: "📝 Πρακτικά", hint_record: "Πατήστε παρακάτω για συνεχή ακρόαση", btn_new: "➕ Νέο", btn_files: "📂 Αρχεία", modal_files_title: "Τοπικά αρχεία", msg_empty_files: "Κανένα αρχείο", prompt_rename: "Νέο όνομα:", prompt_delete: "Μόνιμη διαγραφή;", btn_export: "📄 Εξαγωγή", btn_clear: "🗑️ Εκκαθάριση", btn_load: "Φόρτωση", btn_active: "Ενεργό", prompt_clear_all: "Εκκαθάριση όλων;", msg_empty_export: "Τίποτα για εξαγωγή", default_meeting_name: "Συνάντηση", word_items: "αντικείμενα", title_rename: "Μετονομασία", msg_storage_full: "Πλήρης αποθηκευτικός χώρος. Διαγράψτε παλιά αρχεία." },
    "hu": { title_record: "📝 Átirat", hint_record: "Koppintson alul a folyamatos hallgatáshoz", btn_new: "➕ Új", btn_files: "📂 Fájlok", modal_files_title: "Helyi rekordok", msg_empty_files: "Nincs mentett rekord", prompt_rename: "Új név:", prompt_delete: "Végleges törlés?", btn_export: "📄 Exportálás", btn_clear: "🗑️ Törlés", btn_load: "Betöltés", btn_active: "Aktív", prompt_clear_all: "Minden rekord törlése?", msg_empty_export: "Nincs exportálható adat", default_meeting_name: "Találkozó", word_items: "elem", title_rename: "Átnevezés", msg_storage_full: "Betelt a tárhely. Töröljön régi fájlokat." },
    "mk": { title_record: "📝 Транскрипт", hint_record: "Допрете долу за континуирано слушање", btn_new: "➕ Ново", btn_files: "📂 Датотеки", modal_files_title: "Локални записи", msg_empty_files: "Нема записи", prompt_rename: "Ново име:", prompt_delete: "Трајно избриши?", btn_export: "📄 Извези", btn_clear: "🗑️ Исчисти", btn_load: "Вчитај", btn_active: "Активно", prompt_clear_all: "Избриши ги сите записи?", msg_empty_export: "Нема што да се извезе", default_meeting_name: "Состанок", word_items: "ставки", title_rename: "Преименувај", msg_storage_full: "Меморијата е полна. Ве молиме избришете стари записи." },
    "ro": { title_record: "📝 Transcriere", hint_record: "Atingeți jos pentru ascultare continuă", btn_new: "➕ Nou", btn_files: "📂 Fișiere", modal_files_title: "Înregistrări locale", msg_empty_files: "Fără înregistrări", prompt_rename: "Nume nou:", prompt_delete: "Ștergere definitivă?", btn_export: "📄 Export", btn_clear: "🗑️ Golire", btn_load: "Încărcare", btn_active: "Activ", prompt_clear_all: "Goliți toate înregistrările?", msg_empty_export: "Nimic de exportat", default_meeting_name: "Întâlnire", word_items: "elemente", title_rename: "Redenumire", msg_storage_full: "Memorie plină. Vă rugăm să ștergeți fișiere vechi." }
};

// 🎯 核心黑科技：运行时动态缝合引擎 (自动兼容所有遗留旧页面)
const I18N_DICT = {};
SUPPORTED_LANGS.forEach(l => {
    const lang = l.v;
    I18N_DICT[lang] = {
        // 如果当前语种未提供某些维度的翻译，平滑回退（Fallback）到英文
        ...(I18N_COMMON[lang] || I18N_COMMON["en"]),
        ...(I18N_TRANSLATOR[lang] || I18N_TRANSLATOR["en"]),
        ...(I18N_TUTOR[lang] || I18N_TUTOR["en"]),
        ...(I18N_RECORD[lang] || I18N_RECORD["en"])
    };
});

window.applyUILanguage = function(langCode) {
    const dict = I18N_DICT[langCode] || I18N_DICT["en"] || I18N_DICT["zh"];
    
    // 渲染所有带 data-i18n 的静态 HTML 元素
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (dict[key]) el.innerText = dict[key];
    });
    
    // 处理动态状态文本 (防止短路 Bug)
    const statusText = document.getElementById('statusText');
    if (statusText) {
        const text = statusText.innerText;
        if (text.includes('休眠') || text.includes('Asleep') || text.includes('Veille') || text.includes('Standby') || text.includes('待機中') || text.includes('Ожидание') || text.includes('Stand-by')) {
            statusText.innerText = dict["status_sleep"];
        }
    }
};