// ==========================================
// 文件名: resources/app.js
// 架构定位: [Phase 5] 随身翻译官 - 核心引擎与前端状态机
// 包含: VAD 音频采集、流式 SSE 处理、UI 国际化(i18n)、本地存储与播放
// ==========================================

// --- 1. 国际化 (i18n) 静态字典 ---
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
    "zh": { title: "🗣️ 随身翻译官", detecting: "环境语种: 待检测", btn_play: "▶️ 播放", btn_export: "💾 导出", btn_clear: "🗑️ 清空", btn_start: "点击开启同传", status_sleep: "系统已休眠", status_listen: "👂 倾听中...", status_capture: "🎙️ 捕获中...", status_speak: "🔊 正在播报..." },
    "en": { title: "🗣️ AI Translator", detecting: "Env Lang: Detecting", btn_play: "▶️ Play", btn_export: "💾 Export", btn_clear: "🗑️ Clear", btn_start: "Tap to Start", status_sleep: "System Asleep", status_listen: "👂 Listening...", status_capture: "🎙️ Capturing...", status_speak: "🔊 Speaking..." },
    "yue": { title: "🗣️ AI 隨身翻譯", detecting: "環境語言: 偵測中", btn_play: "▶️ 播放", btn_export: "💾 匯出", btn_clear: "🗑️ 清除", btn_start: "點擊開始", status_sleep: "系統已休眠", status_listen: "👂 聆聽中...", status_capture: "🎙️ 擷取中...", status_speak: "🔊 播放中..." },
    "ar": { title: "🗣️ المترجم الذكي", detecting: "لغة البيئة: جاري الكشف", btn_play: "▶️ تشغيل", btn_export: "💾 تصدير", btn_clear: "🗑️ مسح", btn_start: "اضغط للبدء", status_sleep: "النظام في وضع السكون", status_listen: "👂 يستمع...", status_capture: "🎙️ يسجل...", status_speak: "🔊 يتحدث..." },
    "de": { title: "🗣️ AI-Übersetzer", detecting: "Umgebungsspr.: Erkennung", btn_play: "▶️ Abspielen", btn_export: "💾 Exportieren", btn_clear: "🗑️ Löschen", btn_start: "Starten", status_sleep: "System im Ruhezustand", status_listen: "👂 Hört zu...", status_capture: "🎙️ Nimmt auf...", status_speak: "🔊 Spricht..." },
    "fr": { title: "🗣️ Traducteur IA", detecting: "Langue Env: Détection", btn_play: "▶️ Jouer", btn_export: "💾 Exporter", btn_clear: "🗑️ Effacer", btn_start: "Démarrer", status_sleep: "En Veille", status_listen: "👂 Écoute...", status_capture: "🎙️ Capture...", status_speak: "🔊 Parle..." },
    "es": { title: "🗣️ Traductor IA", detecting: "Idioma Env: Detectando", btn_play: "▶️ Reproducir", btn_export: "💾 Exportar", btn_clear: "🗑️ Borrar", btn_start: "Iniciar", status_sleep: "Sistema en Reposo", status_listen: "👂 Escuchando...", status_capture: "🎙️ Capturando...", status_speak: "🔊 Hablando..." },
    "pt": { title: "🗣️ Tradutor IA", detecting: "Idioma Amb: Detectando", btn_play: "▶️ Reproduzir", btn_export: "💾 Exportar", btn_clear: "🗑️ Limpar", btn_start: "Iniciar", status_sleep: "Sistema em Espera", status_listen: "👂 Ouvindo...", status_capture: "🎙️ Capturando...", status_speak: "🔊 Falando..." },
    "id": { title: "🗣️ Penerjemah AI", detecting: "Bahasa Sekitar: Mendeteksi", btn_play: "▶️ Putar", btn_export: "💾 Ekspor", btn_clear: "🗑️ Hapus", btn_start: "Mulai", status_sleep: "Sistem Tidur", status_listen: "👂 Mendengarkan...", status_capture: "🎙️ Menangkap...", status_speak: "🔊 Berbicara..." },
    "it": { title: "🗣️ Traduttore IA", detecting: "Lingua Amb: Rilevamento", btn_play: "▶️ Riproduci", btn_export: "💾 Esporta", btn_clear: "🗑️ Cancella", btn_start: "Inizia", status_sleep: "Sistema in Sospensione", status_listen: "👂 Ascoltando...", status_capture: "🎙️ Acquisizione...", status_speak: "🔊 Parlando..." },
    "ko": { title: "🗣️ AI 번역기", detecting: "환경 언어: 감지 중", btn_play: "▶️ 재생", btn_export: "💾 내보내기", btn_clear: "🗑️ 지우기", btn_start: "시작하기", status_sleep: "시스템 대기 중", status_listen: "👂 듣는 중...", status_capture: "🎙️ 녹음 중...", status_speak: "🔊 말하는 중..." },
    "ru": { title: "🗣️ ИИ-Переводчик", detecting: "Язык среды: Распознавание", btn_play: "▶️ Играть", btn_export: "💾 Экспорт", btn_clear: "🗑️ Очистить", btn_start: "Начать", status_sleep: "Система спит", status_listen: "👂 Слушаю...", status_capture: "🎙️ Запись...", status_speak: "🔊 Говорю..." },
    "th": { title: "🗣️ นักแปล AI", detecting: "ภาษา: กำลังตรวจจับ", btn_play: "▶️ เล่น", btn_export: "💾 ส่งออก", btn_clear: "🗑️ ล้าง", btn_start: "เริ่ม", status_sleep: "ระบบสลีป", status_listen: "👂 กำลังฟัง...", status_capture: "🎙️ กำลังบันทึก...", status_speak: "🔊 กำลังพูด..." },
    "vi": { title: "🗣️ Trình dịch AI", detecting: "Ngôn ngữ: Đang phát hiện", btn_play: "▶️ Phát", btn_export: "💾 Xuất", btn_clear: "🗑️ Xóa", btn_start: "Bắt đầu", status_sleep: "Hệ thống Đang ngủ", status_listen: "👂 Đang nghe...", status_capture: "🎙️ Đang thu...", status_speak: "🔊 Đang nói..." },
    "ja": { title: "🗣️ AI翻訳機", detecting: "環境言語: 検出中", btn_play: "▶️ 再生", btn_export: "💾 出力", btn_clear: "🗑️ 消去", btn_start: "開始", status_sleep: "待機中", status_listen: "👂 リスニング...", status_capture: "🎙️ 録音中...", status_speak: "🔊 再生中..." },
    "tr": { title: "🗣️ AI Çevirmen", detecting: "Ortam Dili: Algılanıyor", btn_play: "▶️ Oynat", btn_export: "💾 Dışa Aktar", btn_clear: "🗑️ Temizle", btn_start: "Başla", status_sleep: "Sistem Uyku Modunda", status_listen: "👂 Dinleniyor...", status_capture: "🎙️ Kaydediliyor...", status_speak: "🔊 Konuşuluyor..." },
    "hi": { title: "🗣️ AI अनुवादक", detecting: "परिवेश भाषा: पता लगा रहा है", btn_play: "▶️ चलाएं", btn_export: "💾 निर्यात करें", btn_clear: "🗑️ साफ़ करें", btn_start: "शुरू करें", status_sleep: "सिस्टम स्लीप मोड में", status_listen: "👂 सुन रहा है...", status_capture: "🎙️ कैप्चर कर रहा है...", status_speak: "🔊 बोल रहा है..." },
    "ms": { title: "🗣️ Penterjemah AI", detecting: "Bahasa Sekitar: Mengesan", btn_play: "▶️ Main", btn_export: "💾 Eksport", btn_clear: "🗑️ Padam", btn_start: "Mula", status_sleep: "Sistem Tidur", status_listen: "👂 Mendengar...", status_capture: "🎙️ Menangkap...", status_speak: "🔊 Bercakap..." },
    "nl": { title: "🗣️ AI-Vertaler", detecting: "Omgevingstaal: Detecteren", btn_play: "▶️ Afspelen", btn_export: "💾 Exporteren", btn_clear: "🗑️ Wissen", btn_start: "Starten", status_sleep: "Systeem in Slaapstand", status_listen: "👂 Luisteren...", status_capture: "🎙️ Opnemen...", status_speak: "🔊 Spreken..." },
    "sv": { title: "🗣️ AI-Översättare", detecting: "Miljö Språk: Detekterar", btn_play: "▶️ Spela", btn_export: "💾 Exportera", btn_clear: "🗑️ Rensa", btn_start: "Starta", status_sleep: "System i Viloläge", status_listen: "👂 Lyssnar...", status_capture: "🎙️ Spelar in...", status_speak: "🔊 Talar..." },
    "da": { title: "🗣️ AI-Oversætter", detecting: "Miljøsprog: Detekterer", btn_play: "▶️ Afspil", btn_export: "💾 Eksporter", btn_clear: "🗑️ Ryd", btn_start: "Start", status_sleep: "System i Dvale", status_listen: "👂 Lytter...", status_capture: "🎙️ Optager...", status_speak: "🔊 Taler..." },
    "fi": { title: "🗣️ AI-Kääntäjä", detecting: "Ympäristön kieli: Tunnistetaan", btn_play: "▶️ Toista", btn_export: "💾 Vie", btn_clear: "🗑️ Tyhjennä", btn_start: "Aloita", status_sleep: "Järjestelmä Lepotilassa", status_listen: "👂 Kuunnellaan...", status_capture: "🎙️ Nauhoitetaan...", status_speak: "🔊 Puhutaan..." },
    "pl": { title: "🗣️ Tłumacz AI", detecting: "Język otocz: Wykrywanie", btn_play: "▶️ Odtwórz", btn_export: "💾 Eksportuj", btn_clear: "🗑️ Wyczyść", btn_start: "Rozpocznij", status_sleep: "System w Uśpieniu", status_listen: "👂 Słuchanie...", status_capture: "🎙️ Nagrywanie...", status_speak: "🔊 Mówienie..." },
    "cs": { title: "🗣️ AI Překladatel", detecting: "Jazyk prostř: Detekce", btn_play: "▶️ Přehrát", btn_export: "💾 Exportovat", btn_clear: "🗑️ Vymazat", btn_start: "Začít", status_sleep: "Systém v Režimu Spánku", status_listen: "👂 Poslouchám...", status_capture: "🎙️ Nahrávání...", status_speak: "🔊 Mluvím..." },
    "fil": { title: "🗣️ Tagasalin ng AI", detecting: "Wika ng Paligid: Tinutukoy", btn_play: "▶️ I-play", btn_export: "💾 I-export", btn_clear: "🗑️ I-clear", btn_start: "Simulan", status_sleep: "Natutulog ang Sistema", status_listen: "👂 Nakikinig...", status_capture: "🎙️ Nagre-record...", status_speak: "🔊 Nagsasalita..." },
    "fa": { title: "🗣️ مترجم هوش مصنوعی", detecting: "زبان محیط: تشخیص", btn_play: "▶️ پخش", btn_export: "💾 خروجی", btn_clear: "🗑️ پاک کردن", btn_start: "شروع", status_sleep: "سیستم در حالت خواب", status_listen: "👂 در حال گوش دادن...", status_capture: "🎙️ در حال ضبط...", status_speak: "🔊 در حال صحبت..." },
    "el": { title: "🗣️ Μεταφραστής AI", detecting: "Γλώσσα: Ανίχνευση", btn_play: "▶️ Αναπαραγωγή", btn_export: "💾 Εξαγωγή", btn_clear: "🗑️ Εκκαθάριση", btn_start: "Εκκίνηση", status_sleep: "Σύστημα σε Αναστολή", status_listen: "👂 Ακούει...", status_capture: "🎙️ Καταγράφει...", status_speak: "🔊 Μιλάει..." },
    "hu": { title: "🗣️ AI Fordító", detecting: "Környezeti nyelv: Észlelés", btn_play: "▶️ Lejátszás", btn_export: "💾 Exportálás", btn_clear: "🗑️ Törlés", btn_start: "Indítás", status_sleep: "Rendszer Alvó Módban", status_listen: "👂 Figyelés...", status_capture: "🎙️ Rögzítés...", status_speak: "🔊 Beszéd..." },
    "mk": { title: "🗣️ AI Преведувач", detecting: "Јазик на окол: Детектирање", btn_play: "▶️ Пушти", btn_export: "💾 Извези", btn_clear: "🗑️ Исчисти", btn_start: "Започни", status_sleep: "Системот е во мирување", status_listen: "👂 Слушам...", status_capture: "🎙️ Снимам...", status_speak: "🔊 Зборувам..." },
    "ro": { title: "🗣️ Traducător AI", detecting: "Limba mediu: Detectare", btn_play: "▶️ Redare", btn_export: "💾 Export", btn_clear: "🗑️ Șterge", btn_start: "Începe", status_sleep: "Sistem în Așteptare", status_listen: "👂 Ascultă...", status_capture: "🎙️ Capturează...", status_speak: "🔊 Vorbește..." }
};

// --- 2. 核心状态机与常量 ---
let translationQueue = []; 
let currentForeignLang = "fr"; 
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

let audioContext, analyser, microphone, mediaRecorder;
let currentStream = null;
let isVadActive = false, isRecordingChunk = false;
let audioChunks = [], silenceStartTime = 0, recordStartTime = 0, animationFrameId;

const VAD_THRESHOLD = 0.02;     
const SILENCE_NORMAL = 1200;    
const SILENCE_EAGER = 600;      
const EAGER_TRIGGER_TIME = 3000;
const MAX_RECORD_LIMIT = 10000; 

// --- 3. DOM 节点引用 ---
const nativeLangSelect = document.getElementById('nativeLang');
const historyList = document.getElementById('historyList');
const streamingBox = document.getElementById('streamingBox');
const streamOriginal = document.getElementById('streamOriginal');
const streamTranslated = document.getElementById('streamTranslated');
const vadToggleBtn = document.getElementById('vadToggleBtn');
const statusText = document.getElementById('statusText');
const vadLevelBar = document.getElementById('vadLevelBar');
const vadLevelFill = document.getElementById('vadLevelFill');
const langDisplay = document.getElementById('lang-display');
const adminLink = document.getElementById('adminLink');

// --- 4. 国际化渲染引擎 ---
function renderLangOptions() {
    nativeLangSelect.innerHTML = SUPPORTED_LANGS.map(l => `<option value="${l.v}">${l.n}</option>`).join('');
}

function applyUILanguage(langCode) {
    const dict = I18N_DICT[langCode] || I18N_DICT["en"] || I18N_DICT["zh"];
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (dict[key]) el.innerText = dict[key];
    });
    
    if (!isVadActive) {
        statusText.innerText = dict["status_sleep"];
        vadToggleBtn.innerText = dict["btn_start"];
    }
}

// --- 5. 持久化与鉴权 ---
function syncHistoryToStorage() { localStorage.setItem('ttsQueueHistory', JSON.stringify(translationQueue)); }

function initStorageData() {
    renderLangOptions();
    
    const savedLang = localStorage.getItem('nativeLangPref');
    if (savedLang) nativeLangSelect.value = savedLang;
    else {
        const sysLangCode = (navigator.language || navigator.userLanguage || "zh").split('-')[0].toLowerCase();
        const match = SUPPORTED_LANGS.find(opt => opt.v === sysLangCode);
        nativeLangSelect.value = match ? sysLangCode : "zh";
        localStorage.setItem('nativeLangPref', nativeLangSelect.value);
    }

    applyUILanguage(nativeLangSelect.value);

    if (nativeLangSelect.value === currentForeignLang) {
        currentForeignLang = nativeLangSelect.value === "zh" ? "en" : "zh";
    }

    const savedHistory = localStorage.getItem('ttsQueueHistory');
    if (savedHistory) {
        try {
            translationQueue = JSON.parse(savedHistory);
            translationQueue.forEach(item => item.checked = false); 
            renderHistory();
        } catch (e) { translationQueue = []; }
    }
}

async function checkAdminStatus() {
    try {
        const res = await fetch('/api/me');
        if (res.ok && (await res.json()).role === 'admin') adminLink.style.display = 'flex';
    } catch (e) {}
}

nativeLangSelect.addEventListener('change', (e) => {
    localStorage.setItem('nativeLangPref', e.target.value);
    applyUILanguage(e.target.value);
});

// --- 6. UI 列表渲染 ---
function renderHistory() {
    Array.from(historyList.children).forEach(child => { 
        if(child.id !== 'streamingBox') child.remove(); 
    });
    
    translationQueue.forEach((item, index) => {
        const div = document.createElement('div');
        div.className = `history-item ${item.played ? 'played' : ''}`;
        
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox'; 
        checkbox.className = 'history-checkbox'; 
        checkbox.checked = item.checked;
        checkbox.addEventListener('change', (e) => { 
            translationQueue[index].checked = e.target.checked; 
            syncHistoryToStorage(); 
        });

        const contentDiv = document.createElement('div');
        contentDiv.className = 'history-content';
        contentDiv.innerHTML = `<div class="original-text">${item.sourceLang.toUpperCase()}: ${item.original || "..."}</div><div class="translated-text">${item.targetLang.toUpperCase()}: ${item.translated}</div>`;

        div.appendChild(checkbox); 
        div.appendChild(contentDiv);
        historyList.insertBefore(div, streamingBox); 
    });
    historyList.scrollTop = historyList.scrollHeight;
}

// --- 7. 屏幕常亮控制 ---
let wakeLock = null;

async function requestWakeLock() {
    if ('wakeLock' in navigator) {
        try {
            wakeLock = await navigator.wakeLock.request('screen');
        } catch (err) { console.error("Wake Lock Failed:", err); }
    }
}

function releaseWakeLock() {
    if (wakeLock !== null) { wakeLock.release().then(() => wakeLock = null); }
}

document.addEventListener('visibilitychange', async () => {
    if (isVadActive && wakeLock === null && document.visibilityState === 'visible') {
        await requestWakeLock();
    }
});

// --- 8. 播报引擎 ---
function updateStatusUI(statusKey) {
    const dict = I18N_DICT[nativeLangSelect.value] || I18N_DICT["zh"];
    statusText.innerText = dict[statusKey];
}

async function playCheckedItems() {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel(); 
    const itemsToPlay = translationQueue.filter(item => item.checked);
    if (itemsToPlay.length === 0) return;

    updateStatusUI("status_speak");
    vadLevelBar.style.display = 'none'; 

    const voices = window.speechSynthesis.getVoices();

    for (let i = 0; i < itemsToPlay.length; i++) {
        const item = itemsToPlay[i];
        const langMap = { "zh": "zh-CN", "fr": "fr-FR", "en": "en-US", "es": "es-ES", "ja": "ja-JP" };
        const targetSystemLang = langMap[item.targetLang] || item.targetLang;
        
        const utterance = new SpeechSynthesisUtterance(item.translated);
        utterance.lang = targetSystemLang;

        if (voices.length > 0) {
            let matchedVoice = voices.find(v => v.lang.replace('_', '-') === targetSystemLang);
            if (!matchedVoice) {
                const baseLang = targetSystemLang.split('-')[0];
                matchedVoice = voices.find(v => v.lang.startsWith(baseLang));
            }
            if (matchedVoice) utterance.voice = matchedVoice;
        }

        await new Promise(resolve => {
            utterance.onend = () => {
                item.checked = false; item.played = true;   
                renderHistory(); syncHistoryToStorage();
                resolve();
            };
            utterance.onerror = resolve;
            window.speechSynthesis.speak(utterance);
        });
    }
    
    if (isVadActive) {
        updateStatusUI("status_listen");
        vadLevelBar.style.display = 'block';
    } else {
        updateStatusUI("status_sleep");
    }
}

document.getElementById('playSelectedBtn').addEventListener('click', playCheckedItems);

// --- 9. 工具按钮绑定 ---
document.getElementById('clearBtn').addEventListener('click', () => {
    if (translationQueue.length === 0) return;
    
    if (confirm("确认清空记录？")) { 
        // 🎯 核心物理防御：瞬间斩断底层 TTS 播报队列与当前发声
        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
        }
        
        translationQueue = []; 
        syncHistoryToStorage(); 
        renderHistory(); 
        
        // 🎯 状态机急停重置：防止 UI 卡死在 "正在播报..." 状态
        if (isVadActive) {
            updateStatusUI("status_listen");
            vadLevelBar.style.display = 'block';
        } else {
            updateStatusUI("status_sleep");
            vadLevelBar.style.display = 'none';
        }
    }
});

document.getElementById('exportBtn').addEventListener('click', () => {
    if (translationQueue.length === 0) return alert("无记录可导出");
    let txtContent = "=== 随身翻译官 历史记录 ===\n\n";
    translationQueue.forEach((item, index) => {
        txtContent += `[${index + 1}] 原文 (${item.sourceLang}): ${item.original}\n    翻译 (${item.targetLang}): ${item.translated}\n\n`;
    });
    const blob = new Blob([txtContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `翻译记录_${new Date().toISOString().slice(0,10)}.txt`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
});

// --- 10. 核心: VAD 采集与状态机 ---
async function toggleVAD() {
    // [状态机：关闭同传]
    if (isVadActive) {
        isVadActive = false; 
        vadToggleBtn.classList.remove('active'); 
        updateStatusUI("status_sleep");
        applyUILanguage(nativeLangSelect.value); 
        vadLevelBar.style.display = 'none';
        cancelAnimationFrame(animationFrameId);
        
        if (isRecordingChunk) { mediaRecorder.stop(); isRecordingChunk = false; }
        if (audioContext) audioContext.suspend();
        
        // 🎯 核心修复：物理销毁麦克风硬件轨道，熄灭手机红点
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
        
        releaseWakeLock();
        return;
    }

    // [状态机：开启同传]
    try {
        // 🎯 将获取到的物理流挂载到全局变量
        currentStream = await navigator.mediaDevices.getUserMedia({ 
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } 
        });
        
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        analyser = audioContext.createAnalyser(); analyser.fftSize = 512;
        
        // 使用挂载的 currentStream
        microphone = audioContext.createMediaStreamSource(currentStream);
        microphone.connect(analyser);

        let options = { mimeType: 'audio/webm' };
        if (!MediaRecorder.isTypeSupported('audio/webm')) options = { mimeType: 'audio/mp4' }; 
        
        // 使用挂载的 currentStream
        mediaRecorder = new MediaRecorder(currentStream, options);
        
        mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
        mediaRecorder.onstop = () => {
            const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType });
            audioChunks = []; sendAudioChunkStream(blob);
        };

        isVadActive = true; 
        vadToggleBtn.classList.add('active'); 
        vadToggleBtn.innerText = (I18N_DICT[nativeLangSelect.value] || I18N_DICT["zh"])["btn_start"]; // 使用多语言
        updateStatusUI("status_listen");
        vadLevelBar.style.display = 'block';
        
        await requestWakeLock();
        detectAudioLoop();
    } catch (err) { alert("麦克风权限被拒或设备异常"); }
}

vadToggleBtn.addEventListener('click', toggleVAD);

function detectAudioLoop() {
    if (!isVadActive) return;
    
    const pcmData = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(pcmData);
    let sumSquares = 0.0;
    for (const amp of pcmData) sumSquares += amp * amp;
    const rms = Math.sqrt(sumSquares / pcmData.length);
    
    vadLevelFill.style.width = Math.min(100, rms * 1000) + '%';
    const now = Date.now();
    
    let currentSilenceLimit = SILENCE_NORMAL;
    if (isRecordingChunk && (now - recordStartTime > EAGER_TRIGGER_TIME)) {
        currentSilenceLimit = SILENCE_EAGER; 
    }

    if (rms > VAD_THRESHOLD) {
        silenceStartTime = 0; 
        if (!isRecordingChunk) {
            isRecordingChunk = true; recordStartTime = now;
            mediaRecorder.start(); updateStatusUI("status_capture");
        }
    } else {
        if (isRecordingChunk) {
            if (silenceStartTime === 0) silenceStartTime = now;
            if (now - silenceStartTime > currentSilenceLimit) {
                isRecordingChunk = false; mediaRecorder.stop(); updateStatusUI("status_listen");
            }
        }
    }
    
    if (isRecordingChunk && (now - recordStartTime > MAX_RECORD_LIMIT)) {
        isRecordingChunk = false; mediaRecorder.stop(); silenceStartTime = 0;
    }
    
    animationFrameId = requestAnimationFrame(detectAudioLoop);
}

// --- 11. SSE 流式传输 ---
async function sendAudioChunkStream(audioBlob) {
    const formData = new FormData();
    formData.append("audio_file", audioBlob, "chunk.webm");
    formData.append("native_lang", nativeLangSelect.value); 
    formData.append("last_foreign_lang", currentForeignLang);

    const recentHistory = translationQueue.slice(-3).map(item => ({
        original: item.original, translated: item.translated
    }));
    formData.append("chat_history", JSON.stringify(recentHistory));

    try {
        const response = await fetch("/api/stream_voice", { method: "POST", body: formData });
        if (!response.ok) return;

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let streamItemData = { original: "", translated: "", sourceLang: "", targetLang: "" };

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            const chunkStr = decoder.decode(value, { stream: true });
            const events = chunkStr.split("\n\n");
            
            for (const ev of events) {
                if (ev.startsWith("data: ")) {
                    try {
                        const payload = JSON.parse(ev.slice(6));
                        
                        if (payload.event === "start") {
                            streamItemData.original = payload.original_text;
                            streamItemData.sourceLang = payload.source_lang;
                            streamItemData.targetLang = payload.target_lang;
                            
                            if (payload.detected_foreign_lang && payload.detected_foreign_lang !== nativeLangSelect.value) {
                                currentForeignLang = payload.detected_foreign_lang;
                                // 使用多语言环境提示语
                                const prefix = (I18N_DICT[nativeLangSelect.value] || I18N_DICT["zh"])["detecting"].split(":")[0];
                                langDisplay.innerText = `${prefix}: ${currentForeignLang.toUpperCase()}`;
                            }
                            
                            streamOriginal.innerText = payload.original_text;
                            streamTranslated.innerText = "";
                            streamingBox.style.display = "flex";
                            historyList.scrollTop = historyList.scrollHeight;
                        } 
                        else if (payload.event === "token") {
                            streamTranslated.innerText += payload.text;
                            streamItemData.translated += payload.text;
                            historyList.scrollTop = historyList.scrollHeight;
                        }
                        else if (payload.event === "end") {
                            streamingBox.style.display = "none";
                            if (payload.reason === "empty_audio") return; 
                            
                            const newItem = {
                                original: streamItemData.original, translated: streamItemData.translated,
                                sourceLang: streamItemData.sourceLang, targetLang: payload.target_lang,
                                checked: isIOS ? true : false, played: false
                            };
                            translationQueue.push(newItem);
                            syncHistoryToStorage();
                            renderHistory();

                            if (!isIOS && 'speechSynthesis' in window) {
                                const utterance = new SpeechSynthesisUtterance(streamItemData.translated);
                                utterance.lang = payload.target_lang === 'zh' ? 'zh-CN' : payload.target_lang;
                                
                                utterance.onstart = () => {
                                    updateStatusUI("status_speak");
                                    vadLevelBar.style.display = 'none';
                                };

                                utterance.onend = () => { 
                                    newItem.played = true; renderHistory(); syncHistoryToStorage(); 
                                    if (isVadActive) {
                                        updateStatusUI("status_listen");
                                        vadLevelBar.style.display = 'block';
                                    } else { updateStatusUI("status_sleep"); }
                                };
                                window.speechSynthesis.speak(utterance);
                            }
                        }
                    } catch (err) {}
                }
            }
        }
    } catch (error) { console.error("Stream exception:", error); }
}

// 页面加载引擎点火
window.onload = () => { 
    if ('speechSynthesis' in window) window.speechSynthesis.getVoices();
    initStorageData(); 
    checkAdminStatus(); 
};