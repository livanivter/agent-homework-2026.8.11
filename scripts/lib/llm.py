# -*- coding: utf-8 -*-
"""可选 LLM 客户端(仅供 --llm 独立模式)。

只用标准库 urllib 发 HTTP 请求,零第三方依赖。
配置优先级:环境变量 > 项目根目录 .env 文件。

支持的供应商(LLM_PROVIDER):
  anthropic  默认模型 claude-sonnet-5   key: ANTHROPIC_API_KEY
  openai     默认模型 gpt-4o-mini        key: OPENAI_API_KEY
  deepseek   OpenAI 兼容协议            key: DEEPSEEK_API_KEY
可选的 LLM_MODEL 覆盖默认模型。
"""
import json
import os
import urllib.error
import urllib.request

PROVIDERS = {
    "anthropic": {
        "api_type": "anthropic",
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-5",
        "key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "api_type": "openai",
        "base_url": "https://api.openai.com",
        "default_model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "api_type": "openai",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
}


def _load_dotenv():
    """从 skill 根目录的 .env 读取配置(环境变量已设则不动)。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _provider():
    name = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    if name not in PROVIDERS:
        raise RuntimeError("未知 LLM_PROVIDER=%s,可选:%s" % (name, ",".join(PROVIDERS)))
    return PROVIDERS[name]


def available():
    try:
        return bool(os.environ.get(_provider()["key_env"]))
    except RuntimeError:
        return False


def default_model():
    return os.environ.get("LLM_MODEL") or _provider()["default_model"]


def chat(system, user, model=None, max_tokens=4000, temperature=0.2):
    """一次对话,返回文本。失败抛 RuntimeError(带 HTTP 状态与原因)。"""
    provider = _provider()
    if provider["api_type"] == "anthropic":
        return _chat_anthropic(system, user, model, max_tokens, temperature)
    return _chat_openai(provider, system, user, model, max_tokens, temperature)


def _post(url, headers, payload, timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError("LLM HTTP %s: %s" % (e.code, body))


def _chat_anthropic(system, user, model, max_tokens, temperature):
    p = PROVIDERS["anthropic"]
    key = os.environ.get(p["key_env"])
    if not key:
        raise RuntimeError("缺少 %s" % p["key_env"])
    payload = {
        "model": model or default_model(),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    data = _post(
        p["base_url"] + "/v1/messages",
        {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        payload,
    )
    return data["content"][0]["text"]


def _chat_openai(provider, system, user, model, max_tokens, temperature):
    key = os.environ.get(provider["key_env"])
    if not key:
        raise RuntimeError("缺少 %s" % provider["key_env"])
    payload = {
        "model": model or default_model(),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    data = _post(
        provider["base_url"] + "/v1/chat/completions",
        {"content-type": "application/json", "authorization": "Bearer %s" % key},
        payload,
    )
    return data["choices"][0]["message"]["content"]


def parse_json(text):
    """把 LLM 输出解析成 dict,容忍 markdown 代码块包裹。失败抛 ValueError。"""
    t = (text or "").strip()
    t = re_sub(r"^```(?:json)?\s*", "", t)
    t = re_sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        t = t[start:end + 1]
    return json.loads(t)


def re_sub(pattern, repl, string):
    import re
    return re.sub(pattern, repl, string)
