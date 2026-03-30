# 修复了 vLLM 因 token 限制强行注入 `</think>` 导致的脏数据残留问题，以及输出截断时闭合标签缺失导致的解析失败问题，并适当放宽了 token 上限。
# ==========================================
# 文件名: routers/record.py
# 架构定位: 会议记录业务线 (极简高可靠版：非流式 JSON + 隔离解析防幻觉)
# ==========================================
import json
import logging
import time
import asyncio
import base64
import re
import os
from fastapi import APIRouter, UploadFile, File, Form, Header
from fastapi.responses import JSONResponse
import httpx

from routers.user import record_usage
from languages import LANGUAGES_ZH

logger = logging.getLogger("gateway.record")
router = APIRouter()

BRAIN_URL = os.getenv("BRAIN_ENGINE_URL", "http://vllm_qwen:8000/v1/chat/completions")
ASR_URL = os.getenv("ASR_ENGINE_URL", "http://qwen3_asr:8000/v1/chat/completions")
ASR_MODEL_NAME = os.getenv("ASR_MODEL_NAME", "qwen3-asr")

# 🚦 使用信号量代替复杂的队列机制，锁定最大并发
RECORD_MAX_CONCURRENT = 16
concurrency_limiter = asyncio.Semaphore(RECORD_MAX_CONCURRENT)

ASR_TEMPERATURES = [0.1, 0.4, 0.7]
ASR_TIMEOUT = 15.0
LLM_TIMEOUT = 60.0

def parse_llm_response(full_content: str) -> dict:
    """安全解析 LLM 响应，物理隔离思考区与输出区，彻底杜绝正则误捕获与截断问题"""
    # 1. 提取 thinking 内容（支持未闭合的标签截断）
    think_match = re.search(r"<think>(.*?)(?:</think>|$)", full_content, re.DOTALL | re.IGNORECASE)
    thinking = think_match.group(1).strip() if think_match else ""
    
    # 2. 物理切除思考块！保证干净的业务文本
    clean_content = re.sub(r"<think>.*?(?:</think>|$)", "", full_content, flags=re.DOTALL | re.IGNORECASE)
    # 核心修复：清理达到 thinking budget 限制时系统强行注入的异常 </think> 尾巴，防止脏数据残留
    clean_content = re.sub(r"^.*?</think>", "", clean_content, flags=re.DOTALL | re.IGNORECASE).strip()
    
    # 3. 在干净文本中提取业务标签 (容忍截断和未闭合标签)
    def extract_tag(text, tag):
        # 优先严格匹配闭合标签
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
        if m: 
            return m.group(1).strip()
        
        # 兜底截断匹配：匹配到下一个已知标签或结尾，完美兼容末尾截断无闭合标签的场景
        m = re.search(rf"<{tag}>(.*?)(?:<(?:/?language|/?original|/?translation)>|$)", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""
        
    detected_lang = extract_tag(clean_content, "language")
    original = extract_tag(clean_content, "original")
    translation = extract_tag(clean_content, "translation")
    
    # 4. 兜底策略：如果模型抽风完全没输出任何可识别标签
    if not original and not translation:
        clean_text = clean_content.strip()
        clean_text = re.sub(r"<(?:/?language|/?original|/?translation)>", "", clean_text, flags=re.IGNORECASE).strip()
        original = clean_text
        translation = "[格式解析失败或输出严重截断，原文本见上方]"
        
    # 5. 如果原文本存在但因到达 max_tokens 导致翻译没生成，兜底返回原文本
    if original and not translation:
        translation = original

    return {
        "thinking": thinking,
        "detected_lang": detected_lang,
        "original": original,
        "translation": translation
    }

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
            return {"worker_id": worker_id, "temperature": temperature, "text": "", "detected_lang": "unknown", "error": f"HTTP {asr_resp.status_code}"}
            
        raw_asr_text = asr_resp.json()["choices"][0]["message"]["content"].strip()
        
        asr_text = raw_asr_text
        detected_lang = "unknown"
        match = re.match(r"^\s*language\s+([A-Za-z]+)\s*<asr_text>\s*(.*)", raw_asr_text, re.IGNORECASE | re.DOTALL)
        if match:
            detected_lang = match.group(1).lower()
            asr_text = match.group(2).strip()
        
        return {"worker_id": worker_id, "temperature": temperature, "text": asr_text, "detected_lang": detected_lang, "error": None}
    except Exception as e:
        return {"worker_id": worker_id, "temperature": temperature, "text": "", "error": str(e)}

async def parallel_asr_recognition(client: httpx.AsyncClient, base64_audio: str, debug: bool, req_id: str) -> list:
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
                if debug: logger.info(f"[{req_id}] 👂 ASR Worker-{result['worker_id']} -> '{result['text']}'")
            else:
                if debug: logger.warning(f"[{req_id}] ASR Worker-{result['worker_id']} 失败: {result['error']}")
    
    if debug: logger.info(f"[{req_id}] ⏱️ ASR 完成: {successful_count}/3 成功, 耗时: {int((time.time() - t_asr_start)*1000)}ms")
    
    valid_results = [r for r in asr_results if r["error"] is None and r["text"]]
    return valid_results

@router.post("/api/record")
async def record_endpoint(
    audio_file: UploadFile = File(...),
    target_lang: str = Form("zh"),
    chat_history: str = Form("[]"),
    debug: str = Form("false"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    """会议记录非流式 API：稳如老狗的阻塞等待 + 正则提取"""
    req_id = f"RECORD-{int(time.time()*1000)}"
    record_usage(cf_user)
    is_debug = debug.lower() == "true"
    
    async with concurrency_limiter:
        if is_debug: logger.info(f"[{req_id}] 📝 开始处理记录...")
        
        try:
            audio_bytes = await audio_file.read()
            wav_bytes = await convert_webm_to_wav(audio_bytes)
            base64_audio = base64.b64encode(wav_bytes).decode("utf-8")
            
            async with httpx.AsyncClient(timeout=120.0) as client:
                # 1. 异构 ASR
                asr_results = await parallel_asr_recognition(client, base64_audio, is_debug, req_id)
                
                if not asr_results:
                    return JSONResponse({"error": "语音识别失败，请清晰发音"}, status_code=400)
                
                detected_languages = list(set([r["detected_lang"] for r in asr_results if r["detected_lang"] and r["detected_lang"] != "unknown"]))
                target_lang_full_name = LANGUAGES_ZH.get(target_lang, target_lang).title()
                
                asr_descriptions_list = []
                for i, r in enumerate(asr_results):
                    lang_info = f"检测语言={r['detected_lang']}" if r.get('detected_lang') and r['detected_lang'] != 'unknown' else "检测语言=未知"
                    asr_descriptions_list.append(f"版本{i+1} [{lang_info}]: {r['text']}")
                asr_descriptions = "\n".join(asr_descriptions_list)
                
                # 2. Prompt 职责解耦
                system_prompt = f"""你是一个顶级会议记录员。你的任务是根据多个 ASR 识别结果，融合并提炼出最准确的会议记录。

工作流程：
1. 交叉对比 ASR 结果，修复错别字。
2. 判断源语言。 
3. 去除语气词、无意义的停顿词（如“啊”、“那个”），平滑语意，符合书面习惯。
4. 将重构后的文本翻译为：{target_lang_full_name}。
5. 如果判断出的源语言就是 {target_lang_full_name}，则直接将重构后的原文无损复制到 translation 标签中，严禁进行任何画蛇添足的同义词替换或解释。
6. 联系上下文，ASR切片的时候可能会切掉一两个字

🚨 强制输出格式（严格照抄下方样例格式，绝不能有任何多余空行或重复文本）：
<language>
[判断出的源语言名称]
</language>
<original>
[去除停顿词、平滑语意后的源语言文本]
</original>
<translation>
[针对 {target_lang_full_name} 的高质量翻译，或是免翻译的原文本复制]
</translation>"""
                user_prompt = f"""
ASR 识别结果：
{asr_descriptions}

请按要求的 XML 格式输出融合与翻译结果。"""

                messages = [{"role": "system", "content": system_prompt}]
                
                try:
                    history_data = json.loads(chat_history)
                    valid_history = [h for h in history_data if h.get("original") and h.get("translated")]
                    for h in valid_history[-10:]:
                        messages.append({"role": "user", "content": h["original"]})
                        messages.append({"role": "assistant", "content": h["translated"]})
                except Exception: pass
                
                messages.append({"role": "user", "content": user_prompt})
                
                brain_payload = {
                    "model": "qwen3",
                    "messages": messages,
                    "max_tokens": 1280,   # 扩容防截断
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 40,
                    "thinking_token_budget": 512  # 增大 budget 防异常注入
                }
                
                t_llm_start = time.time()
                
                brain_resp = await client.post(BRAIN_URL, json=brain_payload, timeout=LLM_TIMEOUT)
                if brain_resp.status_code != 200:
                    raise Exception(f"LLM 报错 HTTP {brain_resp.status_code}")
                    
                full_content = brain_resp.json()["choices"][0]["message"]["content"]
                
                # 3. 隔离提取 (核心修复区)
                parsed_data = parse_llm_response(full_content)
                
                if is_debug:
                    logger.info(f"[{req_id}] LLM 全文: {full_content}")
                    logger.info(f"[{req_id}] 📝 解析完成 -> 原文: {parsed_data['original']} | 翻译: {parsed_data['translation']} | 耗时: {int((time.time() - t_llm_start)*1000)}ms")
                
                return JSONResponse({
                    "original": parsed_data["original"],
                    "translation": parsed_data["translation"],
                    "detected_lang": [parsed_data["detected_lang"]] if parsed_data["detected_lang"] else detected_languages,
                    "thinking": parsed_data["thinking"]
                })
                
        except Exception as e:
            logger.error(f"[{req_id}] 💥 管线崩溃: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)
        
def start_record_workers():
    logger.info(f"✅ 会议记录专线: 拉起 {RECORD_MAX_CONCURRENT} 个物理锁")