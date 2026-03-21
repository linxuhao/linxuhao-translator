# ==========================================
# 文件名: gateway/app/languages.py
# 架构定位: [Phase 4] 静态语种双向映射引擎
# ==========================================

# 1. 用于解析 ASR 输出的正则探针 (English -> Code)
TO_LANGUAGE_CODE = {
    "chinese": "zh", "english": "en", "cantonese": "yue", "arabic": "ar",
    "german": "de", "french": "fr", "spanish": "es", "portuguese": "pt",
    "indonesian": "id", "italian": "it", "korean": "ko", "russian": "ru",
    "thai": "th", "vietnamese": "vi", "japanese": "ja", "turkish": "tr",
    "hindi": "hi", "malay": "ms", "dutch": "nl", "swedish": "sv",
    "danish": "da", "finnish": "fi", "polish": "pl", "czech": "cs",
    "filipino": "fil", "persian": "fa", "greek": "el", "hungarian": "hu",
    "macedonian": "mk", "romanian": "ro"
}

# 2. 用于构造 LLM 翻译 Prompt 的目标语种 (Code -> 中文全称)
LANGUAGES_ZH = {
    "zh": "中文-普通话", "en": "英语", "yue": "粤语", "ar": "阿拉伯语",
    "de": "德语", "fr": "法语", "es": "西班牙语", "pt": "葡萄牙语",
    "id": "印尼语", "it": "意大利语", "ko": "韩语", "ru": "俄语",
    "th": "泰语", "vi": "越南语", "ja": "日语", "tr": "土耳其语",
    "hi": "印地语", "ms": "马来语", "nl": "荷兰语", "sv": "瑞典语",
    "da": "丹麦语", "fi": "芬兰语", "pl": "波兰语", "cs": "捷克语",
    "fil": "菲律宾语", "fa": "波斯语", "el": "希腊语", "hu": "匈牙利语",
    "mk": "马其顿语", "ro": "罗马尼亚语"
}