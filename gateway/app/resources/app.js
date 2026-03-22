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
        if (dict[key]) {
            el.innerText = dict[key];
        }
    });
    
    // 动态状态同步
    if (!isVadActive) {
        // 由于新的麦克风按钮变成了纯 Icon "🎙️"，我们不需要再去覆盖它的文字
        // 确保你已经把 I18N_DICT 里的 btn_start 改为了 "🎙️"
        vadToggleBtn.innerText = dict["btn_start"];
        statusText.innerText = dict["status_sleep"];
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
        if (res.ok && (await res.json()).role === 'admin') {
            const adminTab = document.getElementById('adminTab');
            // 🎯 如果是超级管理员，解除 display: none 的封印，按 Flex 布局将其挤入导航栏
            if (adminTab) adminTab.style.display = 'flex';
        }
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
    
    // 🎯 核心重构：倒序遍历 Queue，让最新的翻译卡片排在紧贴着 streamingBox 的下方
    for (let i = translationQueue.length - 1; i >= 0; i--) {
        const item = translationQueue[i];
        const div = document.createElement('div');
        div.className = `history-item ${item.played ? 'played' : ''}`;
        
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox'; 
        checkbox.className = 'history-checkbox'; 
        checkbox.checked = item.checked;
        checkbox.addEventListener('change', (e) => { 
            translationQueue[i].checked = e.target.checked; 
            syncHistoryToStorage(); 
        });

        const contentDiv = document.createElement('div');
        contentDiv.className = 'history-content';
        contentDiv.innerHTML = `<div class="original-text">${item.sourceLang.toUpperCase()}: ${item.original || "..."}</div><div class="translated-text">${item.targetLang.toUpperCase()}: ${item.translated}</div>`;

        div.appendChild(checkbox); 
        div.appendChild(contentDiv);
        
        // 🎯 改为 appendChild，顺着往下排
        historyList.appendChild(div); 
    }
    // 🎯 渲染完毕后，强制锁定视角在最顶部
    historyList.scrollTop = 0; 
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

const exportBtn = document.getElementById('exportBtn');
if (exportBtn) {
    exportBtn.addEventListener('click', () => {
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
}

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
                            historyList.scrollTop = 0; // 🎯 视线锁定顶部
                        } 
                        else if (payload.event === "token") {
                            streamTranslated.innerText += payload.text;
                            streamItemData.translated += payload.text;
                            historyList.scrollTop = 0; // 🎯 视线锁定顶部
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