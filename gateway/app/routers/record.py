# ==========================================
# 文件名: routers/record.py
# 架构定位: 会议记录业务线 (MoE 并行 ASR + 滑动窗口流式解析器)
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

logger = logging.getLogger("gateway.record")
router = APIRouter()

BRAIN_URL = os.getenv("BRAIN_ENGINE_URL", "http://vllm_qwen:8000/v1/chat/completions")
ASR_URL = os.getenv("ASR_ENGINE_URL", "http://qwen3_asr:8000/v1/chat/completions")
ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "qwen3-asr")

RECORD_MAX_CONCURRENT = 16
record_task_queue = asyncio.PriorityQueue()

ASR_TEMPERATURES = [0.1, 0.4, 0.7]
ASR_TIMEOUT = 15.0
LLM_TIMEOUT = 60.0


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


async def single_asr_recognition(client: httpx.AsyncClient, base64_audio: str, temperature: float, worker_id: int) -> dict:
    try:
        asr_payload = {
            "model": ASR_MODEL_NAME,
            "messages": [{"role": "user", "content": [{"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{base64_audio}"}}]}],
            "max_tokens": 256,
            "temperature": temperature
        }
        
        asr_resp = await client.post(ASR_URL, json=asr_payload, timeout=ASR_TIMEOUT)
        if asr_resp.status_code != 200:
            return {"worker_id": worker_id, "temperature": temperature, "text": "", "detected_lang": "unknown", "raw_text": "", "error": f"HTTP {asr_resp.status_code}"}
            
        raw_asr_text = asr_resp.json()["choices"][0]["message"]["content"].strip()
        
        asr_text = raw_asr_text
        detected_lang = "unknown"
        match = re.match(r"^\s*language\s+([A-Za-z]+)\s*<asr_text>\s*(.*)", raw_asr_text, re.IGNORECASE | re.DOTALL)
        if match:
            detected_lang = match.group(1).lower()
            asr_text = match.group(2).strip()
        
        return {"worker_id": worker_id, "temperature": temperature, "text": asr_text, "detected_lang": detected_lang, "raw_text": raw_asr_text, "error": None}
    except Exception as e:
        return {"worker_id": worker_id, "temperature": temperature, "text": "", "error": str(e)}


async def parallel_asr_recognition(client: httpx.AsyncClient, base64_audio: str, chunk_queue: asyncio.Queue, debug: bool = False, req_id: str = "") -> list:
    t_asr_start = time.time()
    
    tasks = [single_asr_recognition(client, base64_audio, temp, i) for i, temp in enumerate(ASR_TEMPERATURES)]
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
                if debug:
                    logger.info(f"[{req_id}] 👂 ASR Worker-{result['worker_id']} (temp={result['temperature']}, lang={result['detected_lang']}) -> '{result['text']}'")
            else:
                if debug: logger.warning(f"[{req_id}] ASR Worker-{result['worker_id']} 失败: {result['error']}")
    
    if debug:
        logger.info(f"[{req_id}] ⏱️ 并行 ASR 完成: {successful_count}/3 成功, 耗时: {int((time.time() - t_asr_start)*1000)}ms")
    
    await chunk_queue.put({"event": "asr_complete", "successful_count": successful_count})
    
    valid_results = [r for r in asr_results if r["error"] is None and r["text"]]
    return valid_results if valid_results else [{"worker_id": -1, "temperature": 0.0, "text": "", "error": "All ASR failed"}]


async def execute_record_pipeline(client: httpx.AsyncClient, payload: dict, chunk_queue: asyncio.Queue, debug: bool = False):
    req_id = payload["req_id"]
    audio_bytes = payload["audio_bytes"]
    target_lang = payload["target_lang"]
    chat_history_str = payload.get("chat_history", "[]")
    
    try:
        wav_bytes = await convert_webm_to_wav(audio_bytes)
        base64_audio = base64.b64encode(wav_bytes).decode("utf-8")
        
        await chunk_queue.put({"event": "asr_start"})
        
        asr_results = await parallel_asr_recognition(client, base64_audio, chunk_queue, debug, req_id)
        
        if not asr_results or asr_results[0].get("error"):
            await chunk_queue.put({"event": "error", "message": "ASR 识别失败，请重试"})
            return
        
        detected_languages = list(set([r["detected_lang"] for r in asr_results if r["detected_lang"] and r["detected_lang"] != "unknown"]))
        target_lang_full_name = LANGUAGES_ZH.get(target_lang, target_lang).title()
        
        asr_descriptions = []
        for i, result in enumerate(asr_results):
            if result["text"]:
                lang_info = f"检测语言={result['detected_lang']}" if result["detected_lang"] != "unknown" else "检测语言=未知"
                asr_descriptions.append(f"版本{i+1} [{lang_info}]: {result['text']}")
        
        asr_results_str = "\n".join(asr_descriptions)
        
        system_prompt = f"""你是一个顶级会议记录员。你的任务是根据多个 ASR 识别结果，融合并提炼出最准确的会议记录。

工作流程：
1. 交叉对比 ASR 结果，修复错别字和遗漏。
2. 准确判断实际的源语言。
3. 重构出完美的源文本：必须去除语气词、无意义的停顿词，平滑语意，使之更符合书面阅读习惯。
4. 将重构后的文本高质量翻译为：{target_lang_full_name}。

ASR 识别结果：
{asr_results_str}

🚨 强制输出格式（请自由进行深度思考，但在思考结束后必须严格按照以下 XML 结构输出结果）：
<language>
[判断出的源语言名称]
</language>
<original>
[去除停顿词、平滑语意后的源语言文本]
</original>
<translation>
[针对 {target_lang_full_name} 的高质量翻译]
</translation>"""

        messages = [{"role": "system", "content": system_prompt}]
        
        try:
            history_data = json.loads(chat_history_str)
            valid_history = [h for h in history_data if h.get("original") and h.get("translated")]
            for h in valid_history[-10:]:
                messages.append({"role": "user", "content": h["original"]})
                messages.append({"role": "assistant", "content": h["translated"]})
        except Exception:
            pass
        
        await chunk_queue.put({"event": "thinking_start"})
        
        brain_payload = {
            "model": "qwen3",
            "messages": messages,
            "stream": True,
            "max_tokens": 1024, 
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "thinking_token_budget": 512
        }
        
        t_llm_start = time.time()
        
        # 🚨 坚如磐石的流式滑动窗口状态机
        current_tag = "none"
        buffer = ""
        
        thinking_content = ""
        detected_final_lang = ""
        reconstructed_original = ""
        final_translation = ""
        
        async with client.stream("POST", BRAIN_URL, json=brain_payload, timeout=LLM_TIMEOUT) as r:
            if r.status_code != 200: raise Exception(f"LLM Error: {r.status_code}")
            
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                        if not delta: continue
                        
                        buffer += delta
                        
                        while True:
                            if current_tag == "none":
                                if "<think>" in buffer:
                                    _, buffer = buffer.split("<think>", 1)
                                    current_tag = "think"
                                    continue
                                elif "<language>" in buffer:
                                    _, buffer = buffer.split("<language>", 1)
                                    current_tag = "language"
                                    continue
                                elif "<original>" in buffer:
                                    _, buffer = buffer.split("<original>", 1)
                                    current_tag = "original"
                                    continue
                                elif "<translation>" in buffer:
                                    _, buffer = buffer.split("<translation>", 1)
                                    current_tag = "translation"
                                    # 原文组装完毕，立刻推给前端触发 UI 渲染
                                    await chunk_queue.put({
                                        "event": "start", 
                                        "original_text": reconstructed_original.strip(),
                                        "detected_langs": [detected_final_lang.strip()] if detected_final_lang else detected_languages
                                    })
                                    continue
                                else:
                                    # 保持 buffer 不过长，防止内存溢出，但保留足够的长度检测被切碎的 XML 标签
                                    if len(buffer) > 50: buffer = buffer[-50:]
                                    break
                                    
                            else: # 正在处理某个特定的标签内容
                                end_tag = f"</{current_tag}>"
                                if end_tag in buffer:
                                    content, buffer = buffer.split(end_tag, 1)
                                    if current_tag == "think":
                                        thinking_content += content
                                        await chunk_queue.put({"event": "thinking_end"})
                                    elif current_tag == "language":
                                        detected_final_lang += content
                                    elif current_tag == "original":
                                        reconstructed_original += content
                                    elif current_tag == "translation":
                                        final_translation += content
                                        if content: await chunk_queue.put({"event": "token", "text": content})
                                    
                                    current_tag = "none" # 重置状态，寻找下一个标签
                                    continue
                                else:
                                    # 寻找可能的结束标签开头 '<'
                                    safe_idx = buffer.rfind("<")
                                    if safe_idx != -1:
                                        content = buffer[:safe_idx]
                                        buffer = buffer[safe_idx:]
                                    else:
                                        content = buffer
                                        buffer = ""
                                    
                                    if content:
                                        if current_tag == "think":
                                            thinking_content += content
                                        elif current_tag == "language":
                                            detected_final_lang += content
                                        elif current_tag == "original":
                                            reconstructed_original += content
                                        elif current_tag == "translation":
                                            final_translation += content
                                            await chunk_queue.put({"event": "token", "text": content})
                                    break
                                    
                    except Exception: pass
        
        if debug:
            # 日志不再打印全量 Raw，而是清晰地打印解析出的各部分成果
            logger.info(f"[{req_id}] 🧠 思考摘要: {thinking_content.strip()[-200:]}...") # 仅打印最后 200 字思考，防止刷屏
            logger.info(f"[{req_id}] 🌐 研判语种: {detected_final_lang.strip()}")
            logger.info(f"[{req_id}] 🎯 清洗原文: {reconstructed_original.strip()}")
            logger.info(f"[{req_id}] 📝 最终翻译: {final_translation.strip()} | 耗时: {int((time.time() - t_llm_start)*1000)}ms")
            
        await chunk_queue.put({"event": "end", "target_lang": target_lang})

    except Exception as e:
        logger.error(f"[{req_id}] 💥 管线崩溃: {e}")
        await chunk_queue.put({"event": "error", "message": str(e)})
    finally:
        await chunk_queue.put(None)


async def record_worker(worker_id: int):
    async with httpx.AsyncClient(timeout=120.0) as client:
        while True:
            priority, ts, chunk_queue, payload, debug = await record_task_queue.get()
            try:
                if debug: logger.info(f"[Record-Worker-{worker_id}] 📝 启动记录请求: {payload['req_id']} | P{priority}")
                await execute_record_pipeline(client, payload, chunk_queue, debug)
            except Exception as e:
                logger.error(f"[Record-Worker-{worker_id}] 💥 崩溃: {e}")
            finally:
                record_task_queue.task_done()


def start_record_workers():
    for i in range(RECORD_MAX_CONCURRENT):
        asyncio.create_task(record_worker(i))
    logger.info(f"✅ 会议记录专线: 物理锁定拉起 {RECORD_MAX_CONCURRENT} 个并发 Worker")


@router.post("/api/record_stream")
async def record_stream(
    audio_file: UploadFile = File(...),
    target_lang: str = Form("zh"),
    chat_history: str = Form("[]"),
    debug: str = Form("false"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"RECORD-{int(time.time()*1000)}"
    record_usage(cf_user)
    
    is_debug = debug.lower() == "true"
    
    payload = {
        "req_id": req_id,
        "audio_bytes": await audio_file.read(),
        "target_lang": target_lang,
        "chat_history": chat_history
    }
    
    chunk_queue = asyncio.Queue()
    await record_task_queue.put((get_user_priority(cf_user), time.time(), chunk_queue, payload, is_debug))
    
    async def event_generator():
        while True:
            chunk = await chunk_queue.get()
            if chunk is None:
                break
            yield f"data: {json.dumps(chunk)}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")