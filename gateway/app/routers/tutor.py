# ==========================================
# 文件名: routers/tutor.py
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

logger = logging.getLogger("gateway.tutor")
router = APIRouter()

BRAIN_URL = os.getenv("BRAIN_ENGINE_URL", "http://vllm_qwen:8000/v1/chat/completions")
ASR_URL = os.getenv("ASR_ENGINE_URL", "http://qwen3_asr:8000/v1/chat/completions")
ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "qwen3-asr") 

# 🎯 外教业务专属算力锁：严格物理隔离，最大并发 16，保护 7900 XTX 显存
TUTOR_MAX_CONCURRENT = 16
tutor_task_queue = asyncio.PriorityQueue()

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

async def execute_tutor_stream(client: httpx.AsyncClient, payload: dict, chunk_queue: asyncio.Queue):
    req_id = payload["req_id"]
    audio_bytes = payload["audio_bytes"]
    target_lang = payload["target_lang"]
    native_lang = payload["native_lang"]
    chat_history_str = payload.get("chat_history", "[]")

    try:
        wav_bytes = await convert_webm_to_wav(audio_bytes)
        base64_audio = base64.b64encode(wav_bytes).decode("utf-8")

        # ----------------------------------------
        # Step 1: ASR 听写 (外教模式不强制要求 LID，但直接复用多模态接口)
        # ----------------------------------------
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
        
        # 剥离语种前缀
        asr_text = raw_asr_text
        match = re.match(r"^\s*language\s+([A-Za-z]+)\s*<asr_text>\s*(.*)", raw_asr_text, re.IGNORECASE | re.DOTALL)
        if match: asr_text = match.group(2).strip()
            
        logger.info(f"[{req_id}] 👨‍🏫 ASR 耗时: {int((time.time() - t_asr_start)*1000)}ms | 文本: '{asr_text}'")

        if not asr_text or len(asr_text) < 1:
            await chunk_queue.put({"event": "end", "reason": "empty_audio"})
            return

        target_lang_full_name = LANGUAGES_ZH.get(target_lang, target_lang).title()
        native_lang_full_name = LANGUAGES_ZH.get(native_lang, native_lang).title()
        await chunk_queue.put({
            "event": "start", 
            "original_text": asr_text, 
            "target_lang": target_lang
        })

        # ----------------------------------------
        # Step 2: 组装外教 Stateful History
        # ----------------------------------------
        system_prompt = f"""你是一位专业、耐心、幽默的{target_lang_full_name}外教。
规则：
1. 你的任务是与用户进行自然的口语对话练习，必须且只能使用{target_lang_full_name}回复。
2. 每次回复要简短、口语化，像真人在聊天（控制在1-3句话内）。
3. 输入文本来自语音识别(ASR)，可能包含同音错别字、标点错误或语义断层。请务必根据上下文逻辑进行合理的自动纠错与润色后，再进行回复
4. 如果用户的表达有明显语法错误，可以在回复中自然地给出简短建议，然后继续话题
5. 用户的母语是{native_lang_full_name}, 如果用户的母语和你的外教语言一样，那你们就是在练习口语
6. 绝对不要输出任何 Markdown 格式、发音标记或翻译解析，只输出对话文本本身。"""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        try:
            # 严格解析前端传来的最多 10 轮对话记忆
            history_data = json.loads(chat_history_str)
            for h in history_data:
                # 外教模式的历史结构：{"role": "user"/"assistant", "content": "..."}
                if h.get("role") and h.get("content"):
                    messages.append({"role": h["role"], "content": h["content"]})
        except Exception as e:
            logger.warning(f"[{req_id}] ⚠️ 外教历史记录解析失败: {e}")

        # 追加当前用户的最新语音转写文本
        messages.append({"role": "user", "content": asr_text})

        # ----------------------------------------
        # Step 3: 请求大模型进行流式对话
        # ----------------------------------------
        brain_payload = {"model": "qwen3", "messages": messages, "stream": True, "temperature": 0.5, "max_tokens": 256}

        t_llm_start = time.time()
        full_reply_text = ""
        async with client.stream("POST", BRAIN_URL, json=brain_payload) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                        if delta: 
                            full_reply_text += delta
                            await chunk_queue.put({"event": "token", "text": delta})
                    except Exception: pass
                        
        await chunk_queue.put({"event": "end", "target_lang": target_lang})
        logger.info(f"[{req_id}] 🧠 LLM 回复耗时: {int((time.time() - t_llm_start)*1000)}ms | native_lang_full_name: {native_lang_full_name} | target_lang_full_name: {target_lang_full_name} | 结果: '{full_reply_text}'")
        
    except Exception as e:
        logger.error(f"[{req_id}] 💥 Stream 崩溃: {e}")
        await chunk_queue.put({"event": "error", "message": str(e)})
    finally:
        await chunk_queue.put(None)

async def tutor_worker(worker_id: int):
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            priority, ts, chunk_queue, payload = await tutor_task_queue.get()
            try:
                logger.info(f"[TutorWorker-{worker_id}] 👨‍🏫 外教请求: {payload['req_id']} | P{priority}")
                await execute_tutor_stream(client, payload, chunk_queue)
            except Exception as e:
                logger.error(f"[TutorWorker-{worker_id}] 💥 崩溃: {e}")
            finally:
                tutor_task_queue.task_done()

# 🎯 由主网关统一调用的拉起函数
def start_tutor_workers():
    for i in range(TUTOR_MAX_CONCURRENT):
        asyncio.create_task(tutor_worker(i))
    logger.info(f"✅ 外教专线: 物理锁定拉起 {TUTOR_MAX_CONCURRENT} 个并发 Worker")

@router.post("/api/tutor/stream")
async def stream_tutor(
    audio_file: UploadFile = File(...), 
    target_lang: str = Form("zh"),
    native_lang: str = Form("fr"), 
    chat_history: str = Form("[]"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"TUTOR-{int(time.time()*1000)}"
    record_usage(cf_user)
    
    payload = {
        "req_id": req_id, 
        "audio_bytes": await audio_file.read(),
        "target_lang": target_lang, 
        "native_lang": native_lang,
        "chat_history": chat_history 
    }
    
    chunk_queue = asyncio.Queue()
    await tutor_task_queue.put((get_user_priority(cf_user), time.time(), chunk_queue, payload))
    
    async def event_generator():
        while True:
            chunk = await chunk_queue.get()
            if chunk is None: break
            yield f"data: {json.dumps(chunk)}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")