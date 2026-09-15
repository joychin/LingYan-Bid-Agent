"""模型连通性探活（2026-09-15 路径可靠性批从 api/settings.py 抽出）。

一次最小 chat 调用判断「模型服务当前可用吗」，错误归一成人话文案。两个消费方：
- 设置页「测试连接」（POST /settings/test-model）；
- 断点续跑预检（POST /api/runs/{rid}/continue 在抢占前先探活——2026-09-15
  r_eedd621716b5 两次续跑撞 402 各 1 秒即死、报错看不出是欠费，用户空点两轮）。

纯函数无 FastAPI 依赖；上游失败不抛异常，归一成 (False, 人话, 耗时ms) 交给
调用方决定展示方式。
"""

from __future__ import annotations

_MODEL_ERROR_MARKERS = (
    # 各厂商「模型名不存在」400 的措辞（实测 DeepSeek："The supported API model
    # names are deepseek-flash, deepseek-v4-pro, but you passed ..."）
    "model not found",
    "does not exist",
    "invalid model",
    "unknown model",
    "supported api model names",
    "not a valid model",
    "no such model",
)


def _looks_like_model_error(raw: str) -> bool:
    low = (raw or "").lower()
    return any(m in low for m in _MODEL_ERROR_MARKERS)


def _status_message(code: int, raw: str) -> str:
    """上游 HTTP 状态 → 人话（首行给结论，帮助用户当场自救）。"""
    if code in (401, 403):
        return "API Key 无效或已失效——请检查 Key 是否正确、是否具备该模型的权限"
    if code == 402:
        return "账户额度不足（欠费）——请充值，或切换到其他模型"
    if code == 404:
        return "接口返回 404——多为模型名拼写错误，或接口地址缺少 /v1（也可点「获取列表」选择）"
    if code == 429:
        return "请求过于频繁（限流）——稍后重试"
    if code >= 500:
        return f"服务方错误（HTTP {code}）——稍后重试"
    # 实测：DeepSeek 对未知模型名回 400、自建网关回 422（"model not found: x"），
    # 原文里多带有效模型清单或名字回显
    if code in (400, 422) and _looks_like_model_error(raw):
        return f"模型名不被该服务商支持——检查拼写，或点「获取列表」从真实清单选择。\n服务方返回：{raw[:200]}"
    return f"连接失败（HTTP {code}）：{raw[:200]}"


def ping(base_url: str, model: str, api_key: str) -> tuple[bool, str, int]:
    """同步最小连通性测试，返回 (ok, 人话文案, 耗时 ms)。

    上游失败不抛异常，归一成 ok=False + 人话，交给调用方就地展示。
    """
    import time

    from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=15.0, max_retries=0)
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        # 不带 token 上限：OpenAI/Azure 的 GPT-5/o 系拒绝 max_tokens（只认
        # max_completion_tokens），带了就是假失败；ping 回复成本可忽略
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
        )
    except APITimeoutError:
        return False, "连接超时（15 秒无响应）——检查接口地址与网络", elapsed()
    except APIConnectionError as e:
        return False, f"无法连接到接口地址：{str(e)[:200]}", elapsed()
    except APIStatusError as e:
        return False, _status_message(e.status_code, str(e)), elapsed()
    except Exception as e:  # noqa: BLE001 - 兜底要把原始错误透给用户
        return False, f"连接失败：{str(e)[:200]}", elapsed()
    if not resp.choices:
        return False, "服务方返回了空响应", elapsed()
    return True, "连接正常", elapsed()
