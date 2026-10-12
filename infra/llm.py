# infra/llm.py
# 通用 LLM 调用，模型/endpoint 由 config 传入

import json
import re
import threading
import time
from openai import OpenAI
from pipeline.config_loader import PromptConfig

# 单次 LLM 请求超时（秒）与 SDK 内部重试次数。openai SDK 默认 600s × 3 次，
# 上游不响应时单条 item 最多卡 30 分钟。
LLM_REQUEST_TIMEOUT_S = 60
LLM_SDK_MAX_RETRIES = 1


def make_llm_client(base_url: str, api_key: str, timeout: float = LLM_REQUEST_TIMEOUT_S) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=LLM_SDK_MAX_RETRIES)


_MODEL_TEMP_OVERRIDE: dict[str, float] = {}
_MODEL_TEMP_LOCK = threading.Lock()

# Kimi k2.6 错误消息形如 "invalid temperature: only 0.6 is allowed for this model"
_TEMP_ALLOWED_RE = re.compile(r"only\s+([\d.]+)\s+is\s+allowed", re.IGNORECASE)


def _resolve_temperature(model: str, temperature: float) -> float:
    override = _MODEL_TEMP_OVERRIDE.get(model)
    if override is not None:
        return override
    return temperature


def _handle_invalid_temperature(model: str, temperature: float, err_str: str) -> float | None:
    """
    返回 None = 非温度问题；返回 float = 下次请求应使用的温度（同时写入全局 override）。
    优先从错误消息里解析 API 明确要求的温度值（如 kimi-k2.6 要求 0.6），
    找不到再兜底到 1.0（旧行为）。
    """
    if "invalid temperature" not in err_str.lower():
        return None

    with _MODEL_TEMP_LOCK:
        existing = _MODEL_TEMP_OVERRIDE.get(model)
        if existing is not None and existing != temperature:
            # 已经有其他线程更新过且和当前用的不同，直接采纳
            return existing

        m = _TEMP_ALLOWED_RE.search(err_str)
        if m:
            try:
                allowed = float(m.group(1))
                if allowed != temperature:
                    _MODEL_TEMP_OVERRIDE[model] = allowed
                    print(f"  ⚠️ 模型 {model} 不支持 temperature={temperature}，已按 API 提示全局回退到 {allowed}")
                    return allowed
            except ValueError:
                pass

        if temperature != 1.0:
            _MODEL_TEMP_OVERRIDE[model] = 1.0
            print(f"  ⚠️ 模型 {model} 不支持 temperature={temperature}，已全局回退到 1.0（API 未给出明确允许值）")
            return 1.0

    return None


def _model_extra_body(model: str) -> dict:
    """
    为特定模型注入额外参数。kimi-k2.5 / kimi-k2.6 默认开启 thinking，
    会往输出里掺 reasoning 内容，破坏 response_format=json_object 解析，
    必须显式关闭。
    """
    if model.startswith("kimi-k2.5") or model.startswith("kimi-k2.6"):
        return {"thinking": {"type": "disabled"}}
    return {}


def call_llm(
    prompt: str,
    config: PromptConfig,
    system_prompt: str = "You only output JSON.",
    api_key: str = "",
) -> dict | None:
    if not api_key:
        print("⚠️ LLM API key 未设置")
        return None

    client = make_llm_client(config.model_base_url, api_key)
    temperature = _resolve_temperature(config.model, config.temperature)
    extra_body = _model_extra_body(config.model)

    attempt = 0
    max_attempts = config.max_retries
    # 温度回退不计入 attempt（单独上限防死循环）
    temp_fallback_left = 2

    while attempt < max_attempts:
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                model=config.model,
                temperature=temperature,
                response_format={"type": "json_object"},
                extra_body=extra_body,
            )
            content = response.choices[0].message.content or ""
            if not content.strip():
                raise ValueError("LLM 返回空内容（疑似内容过滤或 thinking 未关闭）")
            result = json.loads(content)
            result["model"] = config.model
            time.sleep(config.request_interval)
            return result

        except Exception as e:
            err_str = str(e)

            fallback_temp = _handle_invalid_temperature(config.model, temperature, err_str)
            if fallback_temp is not None and temp_fallback_left > 0:
                temperature = fallback_temp
                temp_fallback_left -= 1
                continue  # 不 attempt += 1

            is_rate_limit = "429" in err_str or "overloaded" in err_str
            if is_rate_limit and attempt < max_attempts - 1:
                wait = 2 ** (attempt + 2)
                print(f"  ⏳ 限流，{wait}s 后重试 ({attempt + 1}/{max_attempts})")
                time.sleep(wait)
                attempt += 1
                continue

            print(f"⚠️ LLM 调用失败: {e}")
            return None

    return None


def call_llm_raw(
    prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str = "You only output JSON.",
    temperature: float = 0.1,
    timeout: int = 30,
) -> dict | None:
    """不依赖 PromptConfig 的简化调用，用于 archive 等场景。"""
    if not api_key:
        return None

    client = make_llm_client(base_url, api_key, timeout=timeout)
    temperature = _resolve_temperature(model, temperature)
    extra_body = _model_extra_body(model)

    attempt = 0
    max_attempts = 2
    temp_fallback_left = 2

    while attempt < max_attempts:
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
                extra_body=extra_body,
            )
            content = response.choices[0].message.content or ""
            if not content.strip():
                raise ValueError("LLM 返回空内容（疑似内容过滤或 thinking 未关闭）")
            return json.loads(content)
        except Exception as e:
            err_str = str(e)
            fallback_temp = _handle_invalid_temperature(model, temperature, err_str)
            if fallback_temp is not None and temp_fallback_left > 0:
                temperature = fallback_temp
                temp_fallback_left -= 1
                continue
            print(f"⚠️ LLM 调用失败: {e}")
            return None
        attempt += 1
    return None
