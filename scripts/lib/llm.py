# -*- coding: utf-8 -*-
"""可选 LLM 客户端(仅供 --llm 独立模式)。

只用标准库 urllib 发 HTTP 请求,零第三方依赖。
配置:
  LLM_PROVIDER   anthropic(默认)| openai
  ANTHROPIC_API_KEY / OPENAI_API_KEY
  LLM_MODEL      可选,默认 anthropic: claude-sonnet-5 ; openai: gpt-4o-mini
"""
import json
import os
import urllib.error
import urllib.request


def available():
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return False


def default_model():
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    return os.environ.get("LLM_MODEL") or (
        "claude-sonnet-5" if provider == "anthropic" else "gpt-4o-mini"
    )


def chat(system, user, model=None, max_tokens=4000, temperature=0.2):
    """一次对话,返回文本。失败抛 RuntimeError(带 HTTP 状态与原因)。"""
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return _chat_anthropic(system, user, model, max_tokens, temperature)
    if provider == "openai":
        return _chat_openai(system, user, model, max_tokens, temperature)
    raise RuntimeError("未知 LLM_PROVIDER=%s" % provider)


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
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("缺少 ANTHROPIC_API_KEY")
    payload = {
        "model": model or default_model(),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    data = _post(
        "https://api.anthropic.com/v1/messages",
        {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        payload,
    )
    return data["content"][0]["text"]


def _chat_openai(system, user, model, max_tokens, temperature):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("缺少 OPENAI_API_KEY")
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
        "https://api.openai.com/v1/chat/completions",
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
