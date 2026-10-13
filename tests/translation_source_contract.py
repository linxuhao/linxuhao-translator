"""Exercise complete translation streams without contacting GPU services."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from routers import translation


class TranslationSourceContract(unittest.IsolatedAsyncioTestCase):
    async def run_stream(self, asr, expected, history=None):
        requests = []

        async def transcribe(client, wav, language=None):
            value = asr.get(language)
            if isinstance(value, Exception):
                raise value
            return value or {"text": "", "language": "unknown"}

        def handler(request):
            self.assertEqual(request.url.path, "/engines/translator/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer fixture")
            body = json.loads(request.content)
            self.assertTrue(body["stream"])
            self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
            requests.append(body)
            chunks = ["你", "好吗？"]
            content = "".join("data: " + json.dumps({"choices": [{"delta": {"content": part}}]}) + "\n\n" for part in chunks)
            return httpx.Response(200, text=content + "data: [DONE]\n\n")

        queue = asyncio.Queue()
        payload = {"req_id": self.id(), "audio_bytes": b"audio", "native_lang_base": "zh", "target_lang": "fr", "chat_history": json.dumps(history or [])}
        with patch.object(translation, "convert_webm_to_wav", AsyncMock(return_value=b"wav")), patch.object(translation, "transcribe", transcribe), patch.object(translation, "gpu_headers", return_value={"Authorization": "Bearer fixture"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await translation.execute_stream_pipeline(client, payload, queue)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        print(json.dumps({"test": self.id(), "events": events}, ensure_ascii=False), flush=True)
        if expected is None:
            self.assertEqual(events, [{"event": "end", "reason": "empty_audio"}, None])
            self.assertEqual(requests, [])
            return
        text, source, target, foreign = expected
        self.assertEqual(events, [
            {"event": "start", "original_text": text, "source_lang": source, "target_lang": target, "detected_foreign_lang": foreign},
            {"event": "token", "text": "你"},
            {"event": "token", "text": "好吗？"},
            {"event": "end", "target_lang": target}, None,
        ])
        self.assertEqual(len(requests), 1)
        return requests[0]["messages"]

    async def test_french_source_uses_auto_text_instead_of_chinese_hallucination(self):
        await self.run_stream({"zh": {"text": "我，我，我。"}, "fr": {"text": "comment ça va"}, None: {"text": "comment ça va", "language": "French"}}, ("comment ça va", "fr", "zh", None))

    async def test_native_source_still_translates_to_selected_foreign_language(self):
        await self.run_stream({"zh": {"text": "你好"}, "fr": {"text": "bonjour"}, None: {"text": "你好", "language": "Chinese"}}, ("你好", "zh", "fr", None))

    async def test_third_language_uses_auto_text_and_preserves_owner_centric_routing(self):
        messages = await self.run_stream({"zh": {"text": "海楼"}, "fr": {"text": "allô"}, None: {"text": "hello", "language": "English"}}, ("hello", "en", "zh", "en"), [{"original": "old original", "translated": "old translation"}])
        self.assertNotIn("old original", messages[-1]["content"])

    async def test_detection_failure_falls_back_to_native_candidate_as_pair(self):
        await self.run_stream({"zh": {"text": "你好"}, "fr": {"text": "bonjour"}, None: RuntimeError("detect unavailable")}, ("你好", "zh", "fr", None))

    async def test_only_foreign_candidate_fallback_keeps_its_language(self):
        await self.run_stream({"zh": RuntimeError("native unavailable"), "fr": {"text": "bonjour"}, None: RuntimeError("detect unavailable")}, ("bonjour", "fr", "zh", None))

    async def test_only_detect_candidate_is_valid(self):
        await self.run_stream({"zh": RuntimeError("native unavailable"), "fr": RuntimeError("foreign unavailable"), None: {"text": "comment ça va", "language": "French"}}, ("comment ça va", "fr", "zh", None))

    async def test_empty_audio_ends_without_translation(self):
        await self.run_stream({}, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
