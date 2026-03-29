// ==========================================
// 文件名: resources/i18n.js
// 架构定位: [Phase 5] 领域化多语言字典与渲染引擎 (模块化拆分)
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
    "de": { tab_trans: "Übersetzen", tab_tutor: "Tutor", tab_record: "Protokoll", tab_admin: "Einst.", status_sleep: "💤 Bereit", status_listen: "👂 Hört zu...", status_capture: "🎙️ Nimmt auf...", status_speak: "🔊 Spricht...", hint_encrypted: "Chats verschlüsselt, Verlauf lokal" }
};

// 2. 同传业务
const I18N_TRANSLATOR = {
    "zh": { title: "🗣️ 随身翻译", btn_start: "🎙️" },
    "en": { title: "🗣️ Translator", btn_start: "🎙️" },
    "yue": { title: "🗣️ 隨身翻譯", btn_start: "🎙️" },
    "ja": { title: "🗣️ 翻訳機", btn_start: "🎙️" },
    "fr": { title: "🗣️ Traducteur", btn_start: "🎙️" },
    "es": { title: "🗣️ Traductor", btn_start: "🎙️" },
    "de": { title: "🗣️ Übersetzer", btn_start: "🎙️" }
};

// 3. 外教业务
const I18N_TUTOR = {
    "zh": { title_tutor: "👨‍🏫 AI 外教", status_speak_tutor: "🔊 讲话中 (可随时打断)...", btn_native_on: "💡 双语教学: 开", btn_native_off: "💡 双语教学: 关" },
    "en": { title_tutor: "👨‍🏫 AI Tutor", status_speak_tutor: "🔊 Speaking (Interruptible)...", btn_native_on: "💡 Bilingual Mode: On", btn_native_off: "💡 Bilingual Mode: Off" },
    "yue": { title_tutor: "👨‍🏫 AI 外教", status_speak_tutor: "🔊 講話中 (可隨時打斷)...", btn_native_on: "💡 雙語教學: 開", btn_native_off: "💡 雙語教學: 關" },
    "ja": { title_tutor: "👨‍🏫 AI 講師", status_speak_tutor: "🔊 再生中 (割り込み可能)...", btn_native_on: "💡 バイリンガルモード: オン", btn_native_off: "💡 バイリンガルモード: オフ" },
    "fr": { title_tutor: "👨‍🏫 Prof IA", status_speak_tutor: "🔊 Parle (Interruption possible)...", btn_native_on: "💡 Mode Bilingue : ON", btn_native_off: "💡 Mode Bilingue : OFF" },
    "es": { title_tutor: "👨‍🏫 Tutor IA", status_speak_tutor: "🔊 Hablando (Puede interrumpir)...", btn_native_on: "💡 Modo Bilingüe: ON", btn_native_off: "💡 Modo Bilingüe: OFF" },
    "de": { title_tutor: "👨‍🏫 KI-Tutor", status_speak_tutor: "🔊 Spricht (Unterbrechen möglich)...", btn_native_on: "💡 Zweisprachig: An", btn_native_off: "💡 Zweisprachig: Aus" }
};

// 4. 会议记录业务 (包含所有弹窗和操作的文本)
const I18N_RECORD = {
    "zh": { title_record: "📝 会议记录", hint_record: "点击下方按钮开始持续监听", btn_new: "➕ 新建", btn_files: "📂 历史", modal_files_title: "本地会议记录", msg_empty_files: "暂无保存的记录", prompt_rename: "请输入新的会议名称：", prompt_delete: "确定删除此记录吗？不可恢复。", btn_export: "📄 导出", btn_clear: "🗑️ 清空", btn_load: "加载", btn_active: "当前", prompt_clear_all: "确认清空所有会议记录？（不可恢复）", msg_empty_export: "暂无记录可导出" },
    "en": { title_record: "📝 Transcript", hint_record: "Tap below to start continuous listening", btn_new: "➕ New", btn_files: "📂 Files", modal_files_title: "Local Transcripts", msg_empty_files: "No saved records", prompt_rename: "Enter new meeting name:", prompt_delete: "Delete this record permanently?", btn_export: "📄 Export", btn_clear: "🗑️ Clear", btn_load: "Load", btn_active: "Active", prompt_clear_all: "Clear all meeting records? (Cannot be undone)", msg_empty_export: "No transcript to export" },
    "yue": { title_record: "📝 會議記錄", hint_record: "點擊下方按鈕開始持續監聽", btn_new: "➕ 新建", btn_files: "📂 歷史", modal_files_title: "本地會議記錄", msg_empty_files: "暫無保存的記錄", prompt_rename: "請輸入新的會議名稱：", prompt_delete: "確定刪除此記錄嗎？不可恢復。", btn_export: "📄 導出", btn_clear: "🗑️ 清空", btn_load: "加載", btn_active: "當前", prompt_clear_all: "確認清空所有會議記錄？（不可恢復）", msg_empty_export: "暫無記錄可導出" },
    "ja": { title_record: "📝 議事録", hint_record: "下をタップして連続リスニングを開始", btn_new: "➕ 新規", btn_files: "📂 履歴", modal_files_title: "ローカル議事録", msg_empty_files: "記録がありません", prompt_rename: "新しい会議名を入力:", prompt_delete: "完全に削除しますか？", btn_export: "📄 出力", btn_clear: "🗑️ クリア", btn_load: "読込", btn_active: "現在", prompt_clear_all: "すべての記録をクリアしますか？", msg_empty_export: "出力する記録がありません" },
    "fr": { title_record: "📝 Transcription", hint_record: "Appuyez pour écouter en continu", btn_new: "➕ Nouveau", btn_files: "📂 Fichiers", modal_files_title: "Transcriptions locales", msg_empty_files: "Aucun enregistrement", prompt_rename: "Nouveau nom :", prompt_delete: "Supprimer définitivement ?", btn_export: "📄 Exporter", btn_clear: "🗑️ Effacer", btn_load: "Charger", btn_active: "Actif", prompt_clear_all: "Effacer tout ? (Irréversible)", msg_empty_export: "Rien à exporter" },
    "es": { title_record: "📝 Transcripción", hint_record: "Toque para escuchar continuamente", btn_new: "➕ Nuevo", btn_files: "📂 Archivos", modal_files_title: "Registros locales", msg_empty_files: "Sin registros", prompt_rename: "Nuevo nombre:", prompt_delete: "¿Eliminar permanentemente?", btn_export: "📄 Exportar", btn_clear: "🗑️ Borrar", btn_load: "Cargar", btn_active: "Actual", prompt_clear_all: "¿Borrar todos los registros?", msg_empty_export: "Nada que exportar" },
    "de": { title_record: "📝 Protokoll", hint_record: "Tippen zum kontinuierlichen Zuhören", btn_new: "➕ Neu", btn_files: "📂 Dateien", modal_files_title: "Lokale Protokolle", msg_empty_files: "Keine Datensätze", prompt_rename: "Neuer Name:", prompt_delete: "Endgültig löschen?", btn_export: "📄 Export", btn_clear: "🗑️ Leeren", btn_load: "Laden", btn_active: "Aktiv", prompt_clear_all: "Alle Protokolle unwiderruflich löschen?", msg_empty_export: "Nichts zu exportieren" }
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
        if (text.includes('休眠') || text.includes('Asleep') || text.includes('Veille') || text.includes('Standby') || text.includes('待機中')) {
            statusText.innerText = dict["status_sleep"];
        }
    }
};