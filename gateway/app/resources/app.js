// ==========================================
// 文件名: resources/app.js
// 架构定位: [Phase 5] 随身翻译官 - 核心引擎与前端状态机
// 包含: VAD 音频采集、流式 SSE 处理、UI 国际化(i18n)、本地存储与播放
// ==========================================

let debug = false;
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
            debug = true;
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
    formData.append("debug", debug ? "true" : "false");
    
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