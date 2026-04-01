# ==========================================
# 文件名: routers/translation.py
# 架构定位: 同声传译业务线 (极限低延迟流式输出 + 物理防爆显存并发控制)
# 修复内容: 移除了导致 TTFT 翻倍的 XML 标签缓冲逻辑，实现了真正的 Token 级透传；将理论并发数下调至符合 16G 显存物理极限的安全水位。
# ==========================================
import json
import logging
import time
import asyncio
import base64
import re
import os
from fastapi import APIRouter, UploadFile, File, Form, Header
from fastapi.responses import StreamingResponse
import httpx

from routers.user import record_usage, get_user_priority
from languages import LANGUAGES_ZH, TO_LANGUAGE_CODE

logger = logging.getLogger("gateway.translation")
router = APIRouter()

BRAIN_URL = os.getenv("BRAIN_ENGINE_URL", "http://vllm_qwen:8000/v1/chat/completions")
# Transcription API (指定语言)
ASR_TRANSCRIBE_URL = os.getenv("ASR_TRANSCRIBE_URL", "http://qwen3_asr:8000/v1/audio/transcriptions")
# Chat Completions API (自动检测语言)
ASR_CHAT_URL = os.getenv("ASR_ENGINE_URL", "http://qwen3_asr:8000/v1/chat/completions")
ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "qwen3-asr")

MAX_CONCURRENT_TASKS = 32
task_queue = asyncio.PriorityQueue()

# ASR 超时配置
ASR_TIMEOUT = 10.0 # 同传场景缩短超时时间，尽早斩断慢请求


async def convert_webm_to_wav(audio_bytes: bytes) -> bytes:
    """使用 FFmpeg 进行极速内存转码"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout_data, _ = await proc.communicate(input=audio_bytes)
        if proc.returncode != 0: raise Exception(f"FFmpeg 异常, 退出码: {proc.returncode}")
        return stdout_data
    except Exception as e:
        logger.error(f"FFmpeg 处理异常: {e}")
        raise


async def asr_transcribe_with_language(client: httpx.AsyncClient, wav_bytes: bytes, language: str, temperature: float, worker_id: int) -> dict:
    """使用 vLLM /v1/audio/transcriptions API 指定语言转录"""
    try:
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model": ASR_MODEL_NAME, "language": language, "temperature": temperature}

        asr_resp = await client.post(ASR_TRANSCRIBE_URL, files=files, data=data, timeout=ASR_TIMEOUT)

        if asr_resp.status_code != 200:
            return {"worker_id": worker_id, "mode": language, "text": "", "detected_lang": language, "error": f"HTTP {asr_resp.status_code}"}

        result = asr_resp.json()
        text = result.get("text", "").strip()

        return {"worker_id": worker_id, "mode": language, "text": text, "detected_lang": language, "error": None}
    except Exception as e:
        return {"worker_id": worker_id, "mode": language, "text": "", "detected_lang": language, "error": str(e)}


async def asr_detect_language(client: httpx.AsyncClient, base64_audio: str, temperature: float, worker_id: int) -> dict:
    """使用 Chat Completions API 自动检测语言"""
    try:
        asr_payload = {
            "model": ASR_MODEL_NAME,
            "messages": [{"role": "user", "content": [{"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{base64_audio}"}}]}],
            "max_tokens": 128, 
            "temperature": temperature
        }

        asr_resp = await client.post(ASR_CHAT_URL, json=asr_payload, timeout=ASR_TIMEOUT)
        if asr_resp.status_code != 200:
            return {"worker_id": worker_id, "mode": "detect", "text": "", "detected_lang": "unknown", "error": f"HTTP {asr_resp.status_code}"}

        raw_asr_text = asr_resp.json()["choices"][0]["message"]["content"].strip()
        asr_text = raw_asr_text
        detected_lang = "unknown"

        match = re.match(r"^\s*language\s+([A-Za-z]+)\s*<asr_text>\s*(.*)", raw_asr_text, re.IGNORECASE | re.DOTALL)
        if match:
            detected_lang = TO_LANGUAGE_CODE.get(match.group(1).lower(), "unknown")
            asr_text = match.group(2).strip()

        return {"worker_id": worker_id, "mode": "detect", "text": asr_text, "detected_lang": detected_lang, "error": None}
    except Exception as e:
        return {"worker_id": worker_id, "mode": "detect", "text": "", "detected_lang": "unknown", "error": str(e)}


async def parallel_asr_recognition(client: httpx.AsyncClient, wav_bytes: bytes, native_lang: str, target_lang: str, debug: bool, req_id: str) -> list:
    """并行 ASR 转录：引入阶梯式 Temperature"""
    t_asr_start = time.time()
    base64_audio = base64.b64encode(wav_bytes).decode("utf-8")

    tasks = [
        asr_transcribe_with_language(client, wav_bytes, native_lang, 0.2, 0),
        asr_transcribe_with_language(client, wav_bytes, target_lang, 0.5, 1),
        asr_detect_language(client, base64_audio, 0.8, 2),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    asr_results = []
    successful_count = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            if debug: logger.warning(f"[{req_id}] ASR Worker-{i} 异常: {result}")
        else:
            asr_results.append(result)
            if result["error"] is None and result["text"]:
                successful_count += 1
                if debug: logger.info(f"[{req_id}] 👂 ASR v{result['worker_id']+1} [{result['mode']}] lang={result['detected_lang']} | '{result['text']}'")
            else:
                if debug: logger.warning(f"[{req_id}] ASR Worker-{result['worker_id']} 失败: {result['error']}")

    if debug: logger.info(f"[{req_id}] ⏱️ 并行 ASR 完成: {successful_count}/3 成功, 耗时: {int((time.time() - t_asr_start)*1000)}ms")
    return [r for r in asr_results if r["error"] is None and r["text"]]


async def execute_stream_pipeline(client: httpx.AsyncClient, payload: dict, chunk_queue: asyncio.Queue, debug: bool = False):
    """执行流式翻译核心管线"""
    req_id = payload["req_id"]
    audio_bytes = payload["audio_bytes"]
    native_lang_base = payload["native_lang_base"]
    target_lang = payload["target_lang"]
    chat_history_str = payload.get("chat_history", "[]")

    try:
        wav_bytes = await convert_webm_to_wav(audio_bytes)

        asr_results = await parallel_asr_recognition(client, wav_bytes, native_lang_base, target_lang, debug, req_id)

        if not asr_results:
            await chunk_queue.put({"event": "end", "reason": "empty_audio"})
            return

        # 2. 语种裁决逻辑 (修复为 Owner-Centric: 异语种全部转母语)
        detect_result = next((r for r in asr_results if r["mode"] == "detect"), None)
        detected_lang = detect_result["detected_lang"] if detect_result else native_lang_base
        
        # 核心修正：只要开口说的不是母语，一律翻译为母语。只有当说的是母语时，才翻译为目标外语。
        is_native = (detected_lang == native_lang_base)
        target_tts_lang = target_lang if is_native else native_lang_base
        
        # 诚实传递：ASR 真实检测出什么语言，就直接告诉前端什么语言
        actual_source_lang = detected_lang
        
        # 触发前端气泡：如果是不在设定范围内的“第三语种”，通知前端（前端UI会提示用户是否要将此语种设为新的目标语）
        detected_foreign_lang = detected_lang if detected_lang not in [native_lang_base, target_lang, "unknown"] else None

        target_lang_full_name = LANGUAGES_ZH.get(target_tts_lang, target_tts_lang).title()

        target_lang_full_name = LANGUAGES_ZH.get(target_tts_lang, target_tts_lang).title()

        asr_options_text = "\n".join([f"[{r['mode']}] (lang: {r.get('detected_lang', 'unknown')}) {r['text']}" for r in asr_results])
        first_text = asr_results[0]["text"]
        
        await chunk_queue.put({
            "event": "start", "original_text": first_text,
            "source_lang": actual_source_lang, "target_lang": target_tts_lang,
            "detected_foreign_lang": detected_foreign_lang
        })

        system_prompt = f"""你是一个超低延迟的智能同传引擎。

任务：
1. 迅速判断用户实际说的是哪种语言。
2. 🚨 【跨语种空耳修复】：如果发现输入的文本毫无逻辑（例如中文里出现“美容骨头公平呀”），请敏锐地意识到这是 ASR 听错了发音。请尝试根据其拼音/发音，逆向推导还原成合理的外语（如法语的 "maison coûte combien"）。
3. 将还原并锁定后的文本翻译为: {target_lang_full_name}。
4. 【最高戒律】：直接输出最终的翻译文本！绝对不要输出任何前言、解释、XML标签，也不要重复原文。如果判断用户说的本身就是{target_lang_full_name}，则直接修复错别字后输出原文。

<<DISABLE_THINKING>>"""

        messages = [{"role": "system", "content": system_prompt}]

        try:
            history_data = json.loads(chat_history_str)
            valid_history = []
            is_couple_matched = detected_lang in [native_lang_base, target_lang, "unknown"]

            if is_couple_matched and len(history_data) > 0:
                valid_history = [history_data[-1]]
            elif not is_couple_matched:
                if debug: logger.warning(f"[{req_id}] ⚠️ 语种越界 ({detected_lang} ∉ {native_lang_base}/{target_lang}) -> 物理斩断记忆")

            for h in valid_history:
                if h.get("original") and h.get("translated"):
                    messages.append({"role": "user", "content": h["original"]})
                    messages.append({"role": "assistant", "content": h["translated"]})
        except Exception: pass

        current_task_prompt = f"""【当前语音的 ASR 候选版本】(格式: [API调用模式] (lang: ASR底层检测语种) 识别文本)：
{asr_options_text}

请直接输出翻译结果。"""
        messages.append({"role": "user", "content": current_task_prompt})

        brain_payload = {
            "model": "qwen3",
            "messages": messages,
            "stream": True,
            "max_tokens": 128, 
            "temperature": 0.2, 
            "top_p": 0.85,
            "presence_penalty": 1.2,
            "repetition_penalty": 1.05
        }

        t_llm_start = time.time()
        full_trans_text = ""

        async with client.stream("POST", BRAIN_URL, json=brain_payload) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                        if delta:
                            full_trans_text += delta
                            await chunk_queue.put({"event": "token", "text": delta})
                    except Exception: pass

        await chunk_queue.put({"event": "end", "target_lang": target_tts_lang})
        if debug:
            logger.info(f"[{req_id}] 🧠 LLM 完毕 耗时: {int((time.time() - t_llm_start)*1000)}ms | 结果: '{full_trans_text}'")

    except Exception as e:
        logger.error(f"[{req_id}] 💥 Stream 崩溃: {e}")
        await chunk_queue.put({"event": "error", "message": str(e)})
    finally:
        await chunk_queue.put(None)


async def voice_worker(worker_id: int):
    """保持单一 client 会话复用，减少 TCP 建联开销"""
    async with httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_keepalive_connections=20)) as client:
        while True:
            priority, ts, chunk_queue, payload, debug = await task_queue.get()
            try:
                if debug: logger.info(f"[Worker-{worker_id}] 🌊 翻译请求: {payload['req_id']} | P{priority}")
                await execute_stream_pipeline(client, payload, chunk_queue, debug)
            except Exception as e:
                logger.error(f"[Worker-{worker_id}] 💥 崩溃: {e}")
            finally:
                task_queue.task_done()


def start_translation_workers():
    for i in range(MAX_CONCURRENT_TASKS):
        asyncio.create_task(voice_worker(i))
    logger.info(f"✅ 同传专线: 物理锁定拉起 {MAX_CONCURRENT_TASKS} 个流式 Worker")


@router.post("/api/stream_voice")
async def stream_voice(
    audio_file: UploadFile = File(...),
    native_lang: str = Form("zh"),
    target_lang: str = Form("fr"),
    chat_history: str = Form("[]"),
    debug: bool = Form("false"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"TRANS-{int(time.time()*1000)}"
    record_usage(cf_user)

    payload = {
        "req_id": req_id, "audio_bytes": await audio_file.read(),
        "native_lang_base": native_lang.split('-')[0].lower(),
        "target_lang": target_lang.split('-')[0].lower(), "chat_history": chat_history
    }

    chunk_queue = asyncio.Queue()
    await task_queue.put((get_user_priority(cf_user), time.time(), chunk_queue, payload, debug))

    async def event_generator():
        while True:
            chunk = await chunk_queue.get()
            if chunk is None: break
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")