# ==========================================
# 文件名: routers/translation.py
# 架构定位: 同声传译业务线 (单次多模态请求 + 逻辑并发锁 + 动态历史斩断)
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
ASR_URL = os.getenv("ASR_ENGINE_URL", "http://qwen3_asr:8000/v1/chat/completions")
ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "qwen3-asr") 

# 同传业务专有算力池
MAX_CONCURRENT_TASKS = 64
task_queue = asyncio.PriorityQueue()

async def convert_webm_to_wav(audio_bytes: bytes) -> bytes:
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

async def execute_stream_pipeline(client: httpx.AsyncClient, payload: dict, chunk_queue: asyncio.Queue, debug: bool = False):
    req_id = payload["req_id"]
    audio_bytes = payload["audio_bytes"]
    native_lang_base = payload["native_lang_base"]
    last_foreign_lang = payload["last_foreign_lang"]
    chat_history_str = payload.get("chat_history", "[]")

    try:
        wav_bytes = await convert_webm_to_wav(audio_bytes)
        base64_audio = base64.b64encode(wav_bytes).decode("utf-8")

        t_asr_start = time.time()
        asr_payload = {
            "model": ASR_MODEL_NAME,
            "messages": [{"role": "user", "content": [{"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{base64_audio}"}}]}],
            "max_tokens": 256,
            "temperature": 0.0
        }
        
        asr_resp = await client.post(ASR_URL, json=asr_payload, timeout=10.0)
        if asr_resp.status_code != 200: raise Exception(f"ASR Error: {asr_resp.text}")
            
        raw_asr_text = asr_resp.json()["choices"][0]["message"]["content"].strip()
        
        input_lang = "unknown"
        asr_text = raw_asr_text
        detected_lang_str = "unknown"
        
        match = re.match(r"^\s*language\s+([A-Za-z]+)\s*<asr_text>\s*(.*)", raw_asr_text, re.IGNORECASE | re.DOTALL)
        if match:
            detected_lang_str = match.group(1).lower()
            asr_text = match.group(2).strip()
            input_lang = TO_LANGUAGE_CODE.get(detected_lang_str, "unknown")
        
        if debug:
            logger.info(f"[{req_id}] 👂 ASR 耗时: {int((time.time() - t_asr_start)*1000)}ms | detected_lang_str: {detected_lang_str} | 探测语种: {input_lang} | 文本: '{asr_text}'")

        if not asr_text or len(asr_text) < 1:
            await chunk_queue.put({"event": "end", "reason": "empty_audio"})
            return

        if input_lang == "unknown" or input_lang == "": input_lang = native_lang_base
        is_native = (input_lang == native_lang_base)

        if is_native:
            target_tts_lang, actual_source_lang, detected_foreign_lang = last_foreign_lang, native_lang_base, last_foreign_lang
        else:
            target_tts_lang, actual_source_lang, detected_foreign_lang = native_lang_base, input_lang, input_lang

        target_lang_full_name = LANGUAGES_ZH.get(target_tts_lang, target_tts_lang).title()

        await chunk_queue.put({
            "event": "start", "original_text": asr_text, 
            "source_lang": actual_source_lang, "target_lang": target_tts_lang,
            "detected_foreign_lang": detected_foreign_lang 
        })

        system_prompt = f"""你是一个执行驱动的自动化翻译引擎。你的唯一最高优先级是语种映射与字符级协议兼容性。
核心操作规则（CORE OPERATING RULES）：

仅输出针对最新一句话的{target_lang_full_name}的翻译结果，禁止输出任何其他字符。

绝对禁止回复用户，或者给用户纠错。

绝对禁止在输出前后添加诸如“好的”、“这是翻译结果”等对话式前言或问候语。

绝对禁止附加任何语法解释、文化备注、总结或翻译策略说明。

绝对禁止使用Markdown代码块（Code Fences）包裹翻译结果，除非源文本本身包含代码块。

必须保持源文本的所有路径、缩进和结构化空白符（Whitespace）的原样映射。
任何偏离上述规则的附加解释都会导致自动化管线崩溃。禁止一切创造性行为，必须保持严格、刻板与字面映射。

<<DISABLE_THINKING>>"""
        messages = [{"role": "system", "content": system_prompt}]
        
        try:
            # 🎯 核心物理防御：动态斩断逻辑
            history_data = json.loads(chat_history_str)
            valid_history = []
            
            # 判断当前 ASR 探测的语种是否在双向对讲的合法集合内
            is_couple_matched = False
            if input_lang in [native_lang_base, last_foreign_lang, "unknown"]:
                is_couple_matched = True
                
            if is_couple_matched:
                if len(history_data) > 0:
                    valid_history = [history_data[-1]]
            else:
                logger.warning(f"[{req_id}] ⚠️ 语种越界 ({input_lang} ∉ {native_lang_base}/{last_foreign_lang}) -> 物理斩断记忆")
                valid_history = []
                
            for h in valid_history:
                if h.get("original") and h.get("translated"):
                    messages.append({"role": "user", "content": h["original"]})
                    messages.append({"role": "assistant", "content": h["translated"]})
        except Exception as e:
            logger.warning(f"[{req_id}] ⚠️ 历史记录解析失败, 自动回退至 Zero-shot: {e}")

        messages.append({"role": "user", "content": asr_text})

        brain_payload = {
            "model": "qwen3",
            "messages": messages,
            "stream": True,
            "max_tokens": 256,
            
            # --- 核心采样参数校准 ---
            # 放弃绝对 0.0，保留 0.6 以维持目标语言的自然语感与句法流畅度
            "temperature": 0.6,
            
            # 物理切断概率分布长尾，杜绝结尾处的“灵光一现”（额外解释）
            "top_p": 0.80,
            
            # 绝对硬截断，仅允许前 20 个最优 Token，建立防御虚假解释的数学屏障
            "top_k": 20,
            
            # 停用此参数，依赖 top_p 和 top_k 联合过滤
            "min_p": 0.0,
            
            # 极高优先级惩罚，强制推进语意，防止翻译长文本时的“复读机”死循环
            "presence_penalty": 1.5,
            
            # 轻微重复惩罚，足以抑制乱码或结巴，同时保护正常语法结构（如冠词重复）
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
            logger.info(f"[{req_id}] 🧠 LLM 完毕 耗时: {int((time.time() - t_llm_start)*1000)}ms | target_lang_full_name: {target_lang_full_name} | 结果: '{full_trans_text}'")
        
    except Exception as e:
        logger.error(f"[{req_id}] 💥 Stream 崩溃: {e}")
        await chunk_queue.put({"event": "error", "message": str(e)})
    finally:
        await chunk_queue.put(None)

async def voice_worker(worker_id: int):
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            priority, ts, chunk_queue, payload, debug = await task_queue.get()
            try:
                logger.info(f"[Worker-{worker_id}] 🌊 翻译请求: {payload['req_id']} | P{priority}")
                await execute_stream_pipeline(client, payload, chunk_queue, debug)
            except Exception as e:
                logger.error(f"[Worker-{worker_id}] 💥 崩溃: {e}")
            finally:
                task_queue.task_done()

def start_translation_workers():
    for i in range(MAX_CONCURRENT_TASKS):
        asyncio.create_task(voice_worker(i))
    logger.info(f"✅ 翻译专线: 物理锁定拉起 {MAX_CONCURRENT_TASKS} 个并发 Worker")

@router.post("/api/stream_voice")
async def stream_voice(
    audio_file: UploadFile = File(...), 
    native_lang: str = Form("zh"), 
    last_foreign_lang: str = Form("fr"), 
    chat_history: str = Form("[]"),
    debug: bool = Form("false"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"TRANS-{int(time.time()*1000)}"
    record_usage(cf_user)
    
    payload = {
        "req_id": req_id, "audio_bytes": await audio_file.read(),
        "native_lang_base": native_lang.split('-')[0].lower(), 
        "last_foreign_lang": last_foreign_lang, "chat_history": chat_history 
    }
    
    chunk_queue = asyncio.Queue()
    await task_queue.put((get_user_priority(cf_user), time.time(), chunk_queue, payload, debug))
    
    async def event_generator():
        while True:
            chunk = await chunk_queue.get()
            if chunk is None: break
            yield f"data: {json.dumps(chunk)}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")