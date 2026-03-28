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

        # ==========================================
        # 局部修改: routers/tutor.py
        # 架构定位: 高智商模型专属的“放权式”极简 Prompt
        # ==========================================

        if allow_native:
            native_rule = f"""【双语输出规范】(物理级最高优)：
        - 说{native_lang_full_name}前，必须且只能输出 <母语> 标记。
        - 说{target_lang_full_name}前，必须且只能输出 <外语> 标记。
        - 绝对不要输出 </外语> 或 </母语> 这样的闭合标签！
        绝对严禁在同一个标签的句子中混杂两种语言！如果需要用外语举例，必须物理打断句子，换用新标签！
        【教学互动指南】：
        请根据用户的表现自然地切换策略，表现得像个善解人意的朋友，不要死板：
        1. 教任何内容之后都用{native_lang_full_name}解释
        2. ⚠️【不死磕原则 (核心)】：如果用户连续读错、觉得困难、沉默或明确表示不想学，绝对不要逼迫他重复！你应该立刻用<母语>安慰他（例如：“没关系，我们聊点别的”），**但是在你转移话题时，你自己依然要极其自然地说一两句简单的<外语>，保持外教的身份和语境浸润感。**
        3. 当用户困惑或听不懂时：用<母语>解释你刚才的意思，并给出他可以怎么回答的提示。"""
            
            # 🧠 动态生成尾部强化指令（双语模式）
            tail_instruction = f"\n\n[System_Override_复核]: 请用极简短的2-4句话回复。严格遵循标签规范且严禁闭合标签！绝对严禁用拼音/汉字标注发音！"
            
        else:
            native_rule = f"""【沉浸外语环境】：
        你必须且只能使用{target_lang_full_name}回复。每次输出前必须带有 <外语> 标记。
        ⚠️ 绝对禁令：严禁输出 </外语> 闭合标签！绝对严禁使用{native_lang_full_name}。"""
            
            # 🧠 动态生成尾部强化指令（沉浸模式）
            tail_instruction = f"\n\n[System_Override_复核]: 请用极简短的2-4句话回复。必须且只能使用 <外语> 前缀并输出纯{target_lang_full_name}！严禁输出闭合标签！严禁出现任何注音！"

        # 🎯 降维人设：双语向导
        system_prompt = f"""你的名字是Marine，一位精通{native_lang_full_name}和{target_lang_full_name}的双语向导。你的目标是像朋友一样在微信上与用户轻松语音聊天，顺便教几句外语。
        规则：
        1. {native_rule}
        2. 【极致简短】：每次回复控制在 2-4 句话以内，极度口语化。严禁长篇大论的语法解释。
        3. ⚠️【跨语种声学倒推引擎】：用户的语音由ASR转写。当收到极其突兀的{native_lang_full_name}输入时，必须优先在脑内进行“空耳解码”：这是否是用户在努力模仿{target_lang_full_name}，但因为口音极重被识别成了离谱的同音字？（例如：本意是"J'ai faim"，却被识别为"直接放"）。
        -> 应对策略：若判定为口音误听，请发挥同理心，温柔且自然地给出正确的{target_lang_full_name}示范。绝对严禁拆穿这是机器识别错误，也严禁向用户解释你的纠错推导过程，然后自然的继续下一段聊天/教学。
        4. 【严禁注音】：只输出纯文本单词。绝对严禁用汉字或拼音标注发音（例如严禁写"bon-zhoor"）。"""
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

        # 🧠 将单次输入与尾部强约束拼接，不打破状态机的逻辑推理链
        enhanced_user_input = f"{asr_text}\n{tail_instruction}"
        messages.append({"role": "user", "content": enhanced_user_input})

        # ----------------------------------------
        # Step 3: 请求大模型进行流式对话 (带思考状态透传与绝对首行修剪)
        # ----------------------------------------
        brain_payload = {"model": "qwen3", "messages": messages, "stream": True, "temperature": 0.5, "max_tokens": 1024}

        t_llm_start = time.time()
        full_reply_text = ""
        
        # 🎯 物理静音滤网状态机
        is_thinking = True 
        thinking_buffer = ""
        has_started_speaking = False  # 🔒 首字修剪锁

        async with client.stream("POST", BRAIN_URL, json=brain_payload) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                        if delta: 
                            full_reply_text += delta
                            
                            if is_thinking:
                                thinking_buffer += delta
                                
                                # 💡 UX 优化：把思考的 token 发给前端，事件名设为 think_token
                                # 前端收到这个事件，不要送给 TTS 发音，只在界面上渲染为浅灰色的斜体字，缓解用户的等待焦虑
                                await chunk_queue.put({"event": "think_token", "text": delta})
                                
                                if "</think>" in thinking_buffer:
                                    is_thinking = False
                                    
                                    # 截取 </think> 之后的内容
                                    valid_chunk = thinking_buffer.split("</think>")[-1]
                                    
                                    # 🔒 极其冷酷的首字修剪：砍掉所有紧跟在 think 后面的换行和空格
                                    if not has_started_speaking:
                                        valid_chunk = valid_chunk.lstrip('\n\r ')
                                        if valid_chunk:
                                            has_started_speaking = True
                                            await chunk_queue.put({"event": "token", "text": valid_chunk})
                                            
                            else:
                                # 广播模式
                                if not has_started_speaking:
                                    # 🔒 持续修剪，直到遇到第一个有意义的字符
                                    delta_clean = delta.lstrip('\n\r ')
                                    if delta_clean:
                                        has_started_speaking = True
                                        await chunk_queue.put({"event": "token", "text": delta_clean})
                                else:
                                    await chunk_queue.put({"event": "token", "text": delta})
                    except Exception: 
                        pass
                        
        await chunk_queue.put({"event": "end", "target_lang": target_lang})
        if debug:
            logger.info(f"[{req_id}] 🧠 LLM 回复耗时: {int((time.time() - t_llm_start)*1000)}ms | 结果: '{full_reply_text}'")
        
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