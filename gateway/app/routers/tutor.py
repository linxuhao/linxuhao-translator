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

TUTOR_MAX_CONCURRENT = 32
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

async def execute_tutor_stream(client: httpx.AsyncClient, payload: dict, chunk_queue: asyncio.Queue, debug: bool = False):
    req_id = payload["req_id"]
    audio_bytes = payload["audio_bytes"]
    target_lang = payload["target_lang"]
    native_lang = payload["native_lang"]
    allow_native = payload["allow_native"]
    chat_history_str = payload.get("chat_history", "[]")

    try:
        wav_bytes = await convert_webm_to_wav(audio_bytes)
        base64_audio = base64.b64encode(wav_bytes).decode("utf-8")
        target_lang_full_name = LANGUAGES_ZH.get(target_lang, target_lang).title()
        native_lang_full_name = LANGUAGES_ZH.get(native_lang, native_lang).title()

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
        
        if debug:
            logger.info(f"[{req_id}] 👨‍🏫 ASR 耗时: {int((time.time() - t_asr_start)*1000)}ms | 文本: '{asr_text}'")
        
        

        if not asr_text or len(asr_text) < 1:
            await chunk_queue.put({"event": "end", "reason": "empty_audio"})
            return

        await chunk_queue.put({
            "event": "start", 
            "original_text": asr_text, 
            "target_lang": target_lang
        })

        # ----------------------------------------
        # Step 2: 组装外教 Stateful History
        # ----------------------------------------

# prompt_generator.py
# 修复了原有 Prompt 中条件互斥与 TTS 标签混用的问题，引入状态机逻辑解耦，确保格式可直接用于代码库。

        if allow_native:
            native_rule = f"""【语种与标签映射声明】(最高优)：
        你的认知母语是 {native_lang_full_name}，但在文本输出时，必须且只能将其包裹在 <母语> 标签后。
        你的目标教学语言是 {target_lang_full_name}，但在文本输出时，必须且只能将其包裹在 <外语> 标签后。

        【双语标记与TTS发音强制规范】：
        每次使用{target_lang_full_name}前，必须且只能输出 <外语> 标记；每次使用{native_lang_full_name}前，必须且只能输出 <母语> 标记。严禁在同一个标签内混杂两种语言！

        【对话与教学状态机】：
        请根据用户的输入状态，严格执行以下逻辑之一：
        1. 状态A：用户完全用{native_lang_full_name}回答/提问
        -> 先用 <母语> 简短回应，然后用 <母语> 告诉他这句话的{target_lang_full_name}怎么说，并引导他尝试用{target_lang_full_name}重复。
        2. 状态B：用户用{target_lang_full_name}表达，且完全正确
        -> 先用 <外语> 给予简短的肯定，然后用 <外语> 提出下一个简单的话题，继续聊天。
        3. 状态C：用户发音不准或用{target_lang_full_name}表达有误
        -> 用 <母语> 简短鼓励并给出正确示范。⚠️【重要防卡死机制】：如果用户连续多次发音错误或遇到困难，直接用 <母语> 轻松带过（例如：“没关系，这个词确实有点难”），并**必须主动转移到一个全新的、极其简单的话题**，绝对不要死磕同一个词！
        4. 状态D：用户沉默、困惑或明确表示听不懂
        -> 直接用 <母语> 安慰他并解释刚才的意思，然后用 <母语> 给出下一步的回答提示。"""
            
        else:
            native_rule = f"【纯净外语环境】：你必须且只能使用{target_lang_full_name}回复，绝对严禁使用{native_lang_full_name}。每次输出前必须带有 <外语> 标记。"

        # 🎯 降维人设：彻底抹除“外教”高高在上的强制感
        system_prompt = f"""你的名字是Marine,你是一位精通{native_lang_full_name}和{target_lang_full_name}的双语语言向导,你的目标是轻松愉快地和用户聊天，顺便教几句{target_lang_full_name}。
        规则：
        1. {native_rule}
        2. 每次回复要简短，保持礼貌，口语化，像真人在微信聊天（控制在2-4句话内）。严禁长篇大论。
        3. ⚠️跨语种声学纠错：用户的输入来自AI。初学者的口音常导致AI把外语听成离谱的中文（如把"J'ai faim"听成"直接放"）或其他语言的乱码（如把"J'ai soif"听成"Eu sou"或"This of"）。你必须在脑内判定这是用户在努力模仿， 表现得就像一个善解人意的朋友，直接给出正确的{target_lang_full_name}即可。
        4. 你是聊天伙伴，如果用户不想学或读不准，就直接用{native_lang_full_name}随性聊天，不要有强迫用户重复的执念。
        5. 【纯文本发音禁令】：只输出人类能直接读出来的纯文本对话。**绝对严禁用{native_lang_full_name}汉字或拼音/伪音标来标注{target_lang_full_name}的发音（例如：严禁输出类似“bon-zhoor”、“zhé sof”这种谐音）！** 只需要输出正确的法语单词即可。"""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        try:
            history_data = json.loads(chat_history_str)
            
            # 1. 先过滤出所有合法的历史消息
            valid_history = []
            for h in history_data:
                # 外教模式的历史结构：{"role": "user"/"assistant", "content": "..."}
                if h.get("role") and h.get("content"):
                    valid_history.append({"role": h["role"], "content": h["content"]})
            
            # 2. 再截取最新的最多 20 条，追加到主 messages 列表中
            messages.extend(valid_history[-20:])
        except Exception as e:
            logger.warning(f"[{req_id}] ⚠️ 外教历史记录解析失败: {e}")

        # 追加当前用户的最新语音转写文本
        messages.append({"role": "user", "content": asr_text})

        # ----------------------------------------
        # Step 3: 请求大模型进行流式对话
        # ----------------------------------------
        brain_payload = {"model": "qwen3", "messages": messages, "stream": True, "temperature": 0.5, "max_tokens": 1024}

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
        if debug:
            logger.info(f"[{req_id}] 🧠 LLM 回复耗时: {int((time.time() - t_llm_start)*1000)}ms | native_lang_full_name: {native_lang_full_name} | target_lang_full_name: {target_lang_full_name} | 结果: '{full_reply_text}'")
        
    except Exception as e:
        logger.error(f"[{req_id}] 💥 Stream 崩溃: {e}")
        await chunk_queue.put({"event": "error", "message": str(e)})
    finally:
        await chunk_queue.put(None)

async def tutor_worker(worker_id: int):
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            priority, chunk_queue, payload, debug = await tutor_task_queue.get()
            try:
                logger.info(f"[TutorWorker-{worker_id}] 👨‍🏫 外教请求: {payload['req_id']} | P{priority}")
                await execute_tutor_stream(client, payload, chunk_queue, debug)
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
    target_lang: str = Form("fr"),
    native_lang: str = Form("zh"), 
    allow_native: str = Form("false"),
    chat_history: str = Form("[]"),
    debug: bool = Form("false"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"TUTOR-{int(time.time()*1000)}"
    record_usage(cf_user)
    
    payload = {
        "req_id": req_id, 
        "audio_bytes": await audio_file.read(),
        "target_lang": target_lang, 
        "native_lang": native_lang,
        "allow_native": allow_native == "true",
        "chat_history": chat_history 
    }
    
    chunk_queue = asyncio.Queue()
    await tutor_task_queue.put((get_user_priority(cf_user), chunk_queue, payload, debug))
    
    async def event_generator():
        while True:
            chunk = await chunk_queue.get()
            if chunk is None: break
            yield f"data: {json.dumps(chunk)}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")