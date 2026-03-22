// ==========================================
// 文件名: resources/i18n.js
// 架构定位: [Phase 5] 全局多语言静态字典与渲染引擎
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

const I18N_DICT = {
    "zh": { title: "🗣️ 随身翻译", detecting: "环境语种: 待检测", btn_start: "🎙️", status_sleep: "系统已休眠", status_listen: "👂 倾听中...", status_capture: "🎙️ 捕获中...", status_speak: "🔊 正在播报...", tab_trans: "同传", tab_tutor: "外教", tab_admin: "设置" },
    "en": { title: "🗣️ Translator", detecting: "Env Lang: Detecting", btn_start: "🎙️", status_sleep: "System Asleep", status_listen: "👂 Listening...", status_capture: "🎙️ Capturing...", status_speak: "🔊 Speaking...", tab_trans: "Translate", tab_tutor: "Tutor", tab_admin: "Settings" },
    "yue": { title: "🗣️ 隨身翻譯", detecting: "環境語言: 偵測中", btn_start: "🎙️", status_sleep: "系統已休眠", status_listen: "👂 聆聽中...", status_capture: "🎙️ 擷取中...", status_speak: "🔊 播放中...", tab_trans: "同傳", tab_tutor: "外教", tab_admin: "設定" },
    "ar": { title: "🗣️ المترجم", detecting: "لغة البيئة: جاري الكشف", btn_start: "🎙️", status_sleep: "وضع السكون", status_listen: "👂 يستمع...", status_capture: "🎙️ يسجل...", status_speak: "🔊 يتحدث...", tab_trans: "ترجمة", tab_tutor: "معلم", tab_admin: "إعدادات" },
    "de": { title: "🗣️ Übersetzer", detecting: "Umgebung: Erkennung", btn_start: "🎙️", status_sleep: "Ruhezustand", status_listen: "👂 Hört zu...", status_capture: "🎙️ Nimmt auf...", status_speak: "🔊 Spricht...", tab_trans: "Übersetzen", tab_tutor: "Tutor", tab_admin: "Einst." },
    "fr": { title: "🗣️ Traducteur", detecting: "Langue Env: Détection", btn_start: "🎙️", status_sleep: "En Veille", status_listen: "👂 Écoute...", status_capture: "🎙️ Capture...", status_speak: "🔊 Parle...", tab_trans: "Traduction", tab_tutor: "Prof", tab_admin: "Réglages" },
    "es": { title: "🗣️ Traductor", detecting: "Idioma Env: Detectando", btn_start: "🎙️", status_sleep: "En Reposo", status_listen: "👂 Escuchando...", status_capture: "🎙️ Capturando...", status_speak: "🔊 Hablando...", tab_trans: "Traducir", tab_tutor: "Tutor", tab_admin: "Ajustes" },
    "pt": { title: "🗣️ Tradutor", detecting: "Idioma Amb: Detectando", btn_start: "🎙️", status_sleep: "Em Espera", status_listen: "👂 Ouvindo...", status_capture: "🎙️ Capturando...", status_speak: "🔊 Falando...", tab_trans: "Traduzir", tab_tutor: "Tutor", tab_admin: "Ajustes" },
    "id": { title: "🗣️ Penerjemah", detecting: "Bahasa: Mendeteksi", btn_start: "🎙️", status_sleep: "Sistem Tidur", status_listen: "👂 Mendengarkan...", status_capture: "🎙️ Menangkap...", status_speak: "🔊 Berbicara...", tab_trans: "Terjemahan", tab_tutor: "Tutor", tab_admin: "Pengaturan" },
    "it": { title: "🗣️ Traduttore", detecting: "Lingua: Rilevamento", btn_start: "🎙️", status_sleep: "In Sospensione", status_listen: "👂 Ascoltando...", status_capture: "🎙️ Acquisizione...", status_speak: "🔊 Parlando...", tab_trans: "Traduci", tab_tutor: "Tutor", tab_admin: "Impost." },
    "ko": { title: "🗣️ 번역기", detecting: "언어: 감지 중", btn_start: "🎙️", status_sleep: "대기 중", status_listen: "👂 듣는 중...", status_capture: "🎙️ 녹음 중...", status_speak: "🔊 재생 중...", tab_trans: "번역", tab_tutor: "튜터", tab_admin: "설정" },
    "ru": { title: "🗣️ Переводчик", detecting: "Язык: Распознавание", btn_start: "🎙️", status_sleep: "Спящий режим", status_listen: "👂 Слушаю...", status_capture: "🎙️ Запись...", status_speak: "🔊 Говорю...", tab_trans: "Перевод", tab_tutor: "Репетитор", tab_admin: "Настройки" },
    "th": { title: "🗣️ นักแปล", detecting: "ภาษา: กำลังตรวจจับ", btn_start: "🎙️", status_sleep: "โหมดสลีป", status_listen: "👂 กำลังฟัง...", status_capture: "🎙️ กำลังบันทึก...", status_speak: "🔊 กำลังพูด...", tab_trans: "แปล", tab_tutor: "ติวเตอร์", tab_admin: "ตั้งค่า" },
    "vi": { title: "🗣️ Trình dịch", detecting: "Ngôn ngữ: Đang phát hiện", btn_start: "🎙️", status_sleep: "Đang ngủ", status_listen: "👂 Đang nghe...", status_capture: "🎙️ Đang thu...", status_speak: "🔊 Đang nói...", tab_trans: "Dịch", tab_tutor: "Gia sư", tab_admin: "Cài đặt" },
    "ja": { title: "🗣️ 翻訳機", detecting: "環境言語: 検出中", btn_start: "🎙️", status_sleep: "待機中", status_listen: "👂 リスニング...", status_capture: "🎙️ 録音中...", status_speak: "🔊 再生中...", tab_trans: "翻訳", tab_tutor: "講師", tab_admin: "設定" },
    "tr": { title: "🗣️ Çevirmen", detecting: "Dil: Algılanıyor", btn_start: "🎙️", status_sleep: "Uyku Modu", status_listen: "👂 Dinleniyor...", status_capture: "🎙️ Kaydediliyor...", status_speak: "🔊 Konuşuluyor...", tab_trans: "Çeviri", tab_tutor: "Eğitmen", tab_admin: "Ayarlar" },
    "hi": { title: "🗣️ अनुवादक", detecting: "भाषा: पता लगा रहा है", btn_start: "🎙️", status_sleep: "स्लीप मोड", status_listen: "👂 सुन रहा है...", status_capture: "🎙️ कैप्चर कर रहा है...", status_speak: "🔊 बोल रहा है...", tab_trans: "अनुवाद", tab_tutor: "शिक्षक", tab_admin: "सेटिंग्स" },
    "ms": { title: "🗣️ Penterjemah", detecting: "Bahasa: Mengesan", btn_start: "🎙️", status_sleep: "Tidur", status_listen: "👂 Mendengar...", status_capture: "🎙️ Menangkap...", status_speak: "🔊 Bercakap...", tab_trans: "Terjemah", tab_tutor: "Tutor", tab_admin: "Tetapan" },
    "nl": { title: "🗣️ Vertaler", detecting: "Taal: Detecteren", btn_start: "🎙️", status_sleep: "Slaapstand", status_listen: "👂 Luisteren...", status_capture: "🎙️ Opnemen...", status_speak: "🔊 Spreken...", tab_trans: "Vertalen", tab_tutor: "Docent", tab_admin: "Instellingen" },
    "sv": { title: "🗣️ Översättare", detecting: "Språk: Detekterar", btn_start: "🎙️", status_sleep: "Viloläge", status_listen: "👂 Lyssnar...", status_capture: "🎙️ Spelar in...", status_speak: "🔊 Talar...", tab_trans: "Översätt", tab_tutor: "Lärare", tab_admin: "Inställningar" },
    "da": { title: "🗣️ Oversætter", detecting: "Sprog: Detekterer", btn_start: "🎙️", status_sleep: "Dvale", status_listen: "👂 Lytter...", status_capture: "🎙️ Optager...", status_speak: "🔊 Taler...", tab_trans: "Oversæt", tab_tutor: "Tutor", tab_admin: "Indstillinger" },
    "fi": { title: "🗣️ Kääntäjä", detecting: "Kieli: Tunnistetaan", btn_start: "🎙️", status_sleep: "Lepotilassa", status_listen: "👂 Kuunnellaan...", status_capture: "🎙️ Nauhoitetaan...", status_speak: "🔊 Puhutaan...", tab_trans: "Käännä", tab_tutor: "Opettaja", tab_admin: "Asetukset" },
    "pl": { title: "🗣️ Tłumacz", detecting: "Język: Wykrywanie", btn_start: "🎙️", status_sleep: "W Uśpieniu", status_listen: "👂 Słuchanie...", status_capture: "🎙️ Nagrywanie...", status_speak: "🔊 Mówienie...", tab_trans: "Tłumacz", tab_tutor: "Nauczyciel", tab_admin: "Ustawienia" },
    "cs": { title: "🗣️ Překladatel", detecting: "Jazyk: Detekce", btn_start: "🎙️", status_sleep: "Režim Spánku", status_listen: "👂 Poslouchám...", status_capture: "🎙️ Nahrávání...", status_speak: "🔊 Mluvím...", tab_trans: "Překlad", tab_tutor: "Lektor", tab_admin: "Nastavení" },
    "fil": { title: "🗣️ Tagasalin", detecting: "Wika: Tinutukoy", btn_start: "🎙️", status_sleep: "Natutulog", status_listen: "👂 Nakikinig...", status_capture: "🎙️ Nagre-record...", status_speak: "🔊 Nagsasalita...", tab_trans: "Isalin", tab_tutor: "Tutor", tab_admin: "Mga Setting" },
    "fa": { title: "🗣️ مترجم", detecting: "زبان: تشخیص", btn_start: "🎙️", status_sleep: "حالت خواب", status_listen: "👂 در حال شنیدن...", status_capture: "🎙️ در حال ضبط...", status_speak: "🔊 در حال صحبت...", tab_trans: "ترجمه", tab_tutor: "معلم", tab_admin: "تنظیمات" },
    "el": { title: "🗣️ Μεταφραστής", detecting: "Γλώσσα: Ανίχνευση", btn_start: "🎙️", status_sleep: "Σε Αναστολή", status_listen: "👂 Ακούει...", status_capture: "🎙️ Καταγράφει...", status_speak: "🔊 Μιλάει...", tab_trans: "Μετάφραση", tab_tutor: "Καθηγητής", tab_admin: "Ρυθμίσεις" },
    "hu": { title: "🗣️ Fordító", detecting: "Nyelv: Észlelés", btn_start: "🎙️", status_sleep: "Alvó Mód", status_listen: "👂 Figyelés...", status_capture: "🎙️ Rögzítés...", status_speak: "🔊 Beszéd...", tab_trans: "Fordítás", tab_tutor: "Oktató", tab_admin: "Beállítások" },
    "mk": { title: "🗣️ Преведувач", detecting: "Јазик: Детектирање", btn_start: "🎙️", status_sleep: "Мирување", status_listen: "👂 Слушам...", status_capture: "🎙️ Снимам...", status_speak: "🔊 Зборувам...", tab_trans: "Преведи", tab_tutor: "Тутор", tab_admin: "Поставки" },
    "ro": { title: "🗣️ Traducător", detecting: "Limba: Detectare", btn_start: "🎙️", status_sleep: "În Așteptare", status_listen: "👂 Ascultă...", status_capture: "🎙️ Capturează...", status_speak: "🔊 Vorbește...", tab_trans: "Traducere", tab_tutor: "Profesor", tab_admin: "Setări" }
};

// 暴露为全局挂载函数
window.applyUILanguage = function(langCode) {
    const dict = I18N_DICT[langCode] || I18N_DICT["en"] || I18N_DICT["zh"];
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (dict[key]) el.innerText = dict[key];
    });
    
    // 寻找页面中可能存在的动态状态按钮，如果处于休眠期则刷新文字
    const statusText = document.getElementById('statusText');
    if (statusText && statusText.innerText.includes('休眠') || statusText.innerText.includes('Asleep') || statusText.innerText.includes('Veille')) {
        statusText.innerText = dict["status_sleep"];
    }
};