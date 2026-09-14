"""Settings 端点：多模型 profile 列表读写 + 连通性测试。

配置与凭证的真值在 app.db 的 app_settings KV 表（用户明令 2026-08-29 弃钥匙串）：
模型列表/默认模型经 PUT /settings/models，Key 经 PUT /settings/keys（只写不读——
GET 永不回回 Key，只回 key_configured 布尔），百度 AK/SK 经 PUT /settings/ocr-keys。
env 只作兜底读取（.env 开发习惯不变）。变更即时生效（agent 缓存清空惰性重建），
无需重启服务。
"""

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import config as cfg
from .. import model_registry
from ..agent import rebuild_agent

router = APIRouter()


def _kick_registry_refresh() -> None:
    """用户主动联网动作（保存模型/测试连接/获取模型列表）后台刷新社区模型库缓存。

    fire-and-forget：不阻塞端点、失败静默（model_registry 内部有 TTL 守卫与
    旧缓存保留）；run 路径零联网的铁律不受影响——只有设置动作会走到这里。
    """
    try:
        asyncio.create_task(asyncio.to_thread(model_registry.maybe_refresh))
    except RuntimeError:
        pass  # 无事件循环的边缘调用环境：放弃刷新，缓存下次再补


class ModelBody(BaseModel):
    id: str
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    image_support: bool = False
    # 上下文窗口（token；None=未知/自动）。仅 deepagents 压缩触发档位用，可选。
    context_window: int | None = Field(default=None, gt=0)


class BackgroundRolesBody(BaseModel):
    """后台任务角色 → profile id（空串=跟随缺省：extract 回 default，vision 走自动解析）。"""

    extract: str = ""
    vision: str = ""


class ModelsBody(BaseModel):
    models: list[ModelBody]
    default_model: str
    background_roles: BackgroundRolesBody | None = None


def _validate_base_url(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise HTTPException(status_code=422, detail="base_url 不能为空")
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="base_url 必须是合法 http/https URL")
    host = (parsed.hostname or "").lower()
    loopback = host in ("127.0.0.1", "localhost", "::1")
    if parsed.scheme != "https" and not loopback:
        raise HTTPException(status_code=422, detail="非本机 base_url 必须使用 https")
    return v


def _profile_to_api(p: cfg.ModelProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "model": p.model,
        "image_support": p.image_support,
        "context_window": p.context_window,
        "key_configured": bool(cfg.model_key(p.id)),
    }


@router.get("/settings")
async def get_settings():
    return {
        "models": [_profile_to_api(p) for p in cfg.model_profiles()],
        "default_model": cfg.default_model_id(),
        "background_roles": cfg.background_roles(),
        "ocr": {
            "configured": bool(cfg.baidu_ocr_api_key() and cfg.baidu_ocr_secret_key()),
        },
        "paths": {
            "data_dir": str(cfg.data_dir()),
            "log_file": str(cfg.data_dir() / "logs" / "sidecar.log"),
        },
    }


@router.put("/settings/models")
async def put_settings_models(body: ModelsBody):
    ids = [m.id.strip() for m in body.models]
    if not ids or any(not i for i in ids):
        raise HTTPException(status_code=422, detail="models 不能为空且每条必须有 id")
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="模型 id 重复")
    if body.default_model not in ids:
        raise HTTPException(status_code=422, detail="default_model 必须是 models 之一")
    if body.background_roles is not None:
        for role, pid in (
            ("extract", body.background_roles.extract.strip()),
            ("vision", body.background_roles.vision.strip()),
        ):
            if pid and pid not in ids:
                raise HTTPException(status_code=422, detail=f"后台任务角色 {role} 引用了未知模型：{pid}")

    normalized: list[cfg.ModelProfile] = []
    for m, mid in zip(body.models, ids):
        base_url = _validate_base_url(m.base_url or "")
        if not (m.model or "").strip():
            raise HTTPException(status_code=422, detail=f"模型 {mid} 缺少 model 名")
        normalized.append(
            cfg.ModelProfile(
                id=mid,
                name=(m.name or "").strip() or mid,
                base_url=base_url,
                model=m.model.strip(),
                image_support=m.image_support,
                context_window=m.context_window,
            )
        )

    roles = (
        {"extract": body.background_roles.extract, "vision": body.background_roles.vision}
        if body.background_roles is not None
        else None
    )
    cfg.save_models_and_roles(normalized, body.default_model, roles)
    _kick_registry_refresh()
    # 模型列表变了：清 agent 缓存（按 profile 惰性重建，毫秒级；无 key 的 profile 在
    # 实际被选用时才报错，不影响其他 profile）
    await rebuild_agent()
    return {"ok": True}


class KeyBody(BaseModel):
    model_id: str
    api_key: str


@router.put("/settings/keys")
async def put_settings_key(body: KeyBody):
    """保存模型 Key 到本地库（用户明令 2026-08-29：凭证存 SQLite，弃钥匙串）。

    安全性质保留：GET 永不回读 Key（只回 key_configured 布尔）；本端点只写不读。
    即时生效（agent 缓存清空惰性重建），无需重启服务。
    """
    pid = body.model_id.strip()
    key = body.api_key.strip()
    if not pid:
        raise HTTPException(status_code=422, detail="model_id 不能为空")
    if not key:
        raise HTTPException(status_code=422, detail="api_key 不能为空")
    # 孤儿 key 防护：只给存在的 profile 存 Key（对齐 put_settings_models 的 roles
    # 校验先例）——否则写错 id 会静默存一个 GET 永不可见的凭证
    if cfg.get_profile(pid) is None:
        raise HTTPException(status_code=404, detail=f"模型 {pid} 不存在，请先保存模型配置")
    cfg.set_model_key(pid, key)
    await rebuild_agent()
    return {"ok": True}


class OcrKeysBody(BaseModel):
    api_key: str
    secret_key: str


@router.put("/settings/ocr-keys")
async def put_settings_ocr_keys(body: OcrKeysBody):
    ak, sk = body.api_key.strip(), body.secret_key.strip()
    if not ak or not sk:
        raise HTTPException(status_code=422, detail="API Key 与 Secret Key 均不能为空")
    cfg.set_baidu_ocr_keys(ak, sk)
    # AK/SK 换取的 access_token 缓存作废，下次解析用新凭证重取
    from ..baidu_ocr import _reset_token_cache

    _reset_token_cache()
    return {"ok": True}


class DraftTestBody(BaseModel):
    """草稿态连通性测试：Key 来自表单正在填的值（api_key）或借用已保存 profile（key_ref）。

    with_image=True 时文本 ping 通过后附带一次图片 ping（1×1 PNG data URI），
    探测服务方是否接受图片输入——验证「图片输入」开关的声明是否属实。
    """

    base_url: str
    model: str
    api_key: str | None = None
    key_ref: str | None = None
    with_image: bool = False


class AvailableModelsBody(BaseModel):
    """拉取服务商模型清单：同样只收草稿 Key，不落库。"""

    base_url: str
    api_key: str | None = None
    key_ref: str | None = None


class CopyKeyBody(BaseModel):
    """同厂商 Key 复用：服务端读源写目标，Key 不出库。"""

    from_model: str = Field(alias="from")
    to_model: str = Field(alias="to")


def _norm_base_url(u: str) -> str:
    """同厂商地址比较用：去首尾空白与尾斜杠（与前端 modelSettings.sameBaseUrl 同语义）。"""
    return (u or "").strip().rstrip("/")


def _resolve_draft_key(api_key: str | None, key_ref: str | None, base_url: str) -> str:
    """草稿 Key 优先；为空时借用 key_ref 已保存的 Key（编辑未改 Key / 同厂商复用两条路径）。

    借用必须绑定地址（2026-09-12）：已存 Key 只允许发往其所属 profile 的 base_url——
    否则「编辑改地址 + Key 留空点测试」会把 A 厂商的 Key 发到 B 地址。归一化后
    不一致 → 400 人话，引导为新地址填写 Key。
    """
    k = (api_key or "").strip()
    if k:
        return k
    ref = (key_ref or "").strip()
    if ref:
        p = cfg.get_profile(ref)
        if p is None:
            raise HTTPException(status_code=400, detail=f"引用的模型 {ref} 不存在，请重新选择")
        if _norm_base_url(p.base_url) != _norm_base_url(base_url):
            raise HTTPException(
                status_code=400,
                detail=f"所借 Key 属于接口地址 {p.base_url} 的模型，与当前填写地址不一致——请为新地址填写 API Key",
            )
        return cfg.model_key(ref) or ""
    return ""


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


def _ping_model_sync(base_url: str, model: str, api_key: str) -> tuple[bool, str, int]:
    """同步最小连通性测试，返回 (ok, 人话文案, 耗时 ms)。

    上游失败不抛异常，归一成 ok=False + 人话，交给前端在弹窗里就地展示。
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


def _list_models_sync(base_url: str, api_key: str) -> tuple[bool, list[str], str]:
    """调 OpenAI 兼容 /models 拉清单。失败返回 (False, [], 错误)，前端静默回落静态预设。"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=15.0, max_retries=0)
    try:
        resp = client.models.list()
    except Exception as e:  # noqa: BLE001 - 拉不到清单不是致命错误，交给前端兜底
        return False, [], str(e)[:200]
    ids = sorted({m.id for m in resp.data if getattr(m, "id", None)})
    return True, ids, ""


# 1×1 红色 PNG 的 data URI——图片探测用最小载荷（费用可忽略，无需外网图片 URL）
_TINY_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _ping_image_sync(base_url: str, model: str, api_key: str) -> tuple[bool, str]:
    """图片输入探测：发一条带 1×1 PNG 的最小 chat 请求。

    支持=服务方接受（200）；多数文本模型回 4xx 拒绝。已知边界：个别兼容网关会
    静默忽略图片照常 200（假阳性接受）——探测语义是「服务方是否接受」，不是
    「模型是否真理解图片内容」，提示文案按此措辞。
    """
    from openai import APIStatusError, OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=15.0, max_retries=0)
    try:
        # 同文本 ping：不带上限参数（GPT-5/o 系拒绝 max_tokens，见 _ping_model_sync）
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "ping"},
                        {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URI}},
                    ],
                }
            ],
        )
    except APIStatusError as e:
        if e.status_code in (400, 404, 422):
            return False, "未通过——服务方拒绝图片请求，该模型可能不支持图片输入（建议关闭开关）"
        return False, f"未通过（HTTP {e.status_code}）：{str(e)[:200]}"
    except Exception as e:  # noqa: BLE001 - 探测失败照常透给用户
        return False, f"未通过：{str(e)[:200]}"
    if not resp.choices:
        return False, "未通过——服务方返回了空响应"
    return True, "通过——服务方接受图片请求"


def _test_ocr_sync() -> str:
    from ..baidu_ocr import BaiduOcrUnavailable, exchange_access_token

    if not (cfg.baidu_ocr_api_key() and cfg.baidu_ocr_secret_key()):
        raise HTTPException(status_code=400, detail="文档解析未配置（API Key / Secret Key 缺失）")
    try:
        exchange_access_token(force_refresh=True)
    except BaiduOcrUnavailable as e:
        raise HTTPException(status_code=502, detail=f"连通失败：{e}") from e
    except Exception as e:  # noqa: BLE001 - 测试端点要把原始错误透给用户
        raise HTTPException(status_code=502, detail=f"连通失败：{e}") from e
    return "ok"


@router.post("/settings/test-model")
async def test_model_draft(body: DraftTestBody):
    """测「表单当前值」（base_url/model/key 尚未保存）：填好即可测，测试不再偷偷保存。

    入参非法（地址/模型名缺失）→ 422；上游连接问题一律 200 + ok=false + 人话文案。
    with_image=True 且文本 ping 通过时，附带图片输入探测（image_ok/image_message）。
    """
    base_url = _validate_base_url(body.base_url)
    model = (body.model or "").strip()
    if not model:
        raise HTTPException(status_code=422, detail="请填写模型名称")
    api_key = _resolve_draft_key(body.api_key, body.key_ref, base_url)
    if not api_key:
        raise HTTPException(status_code=400, detail="未提供 API Key——请填写 Key，或复用同厂商已配置的 Key")
    ok, message, latency_ms = await asyncio.to_thread(_ping_model_sync, base_url, model, api_key)
    _kick_registry_refresh()
    image_ok: bool | None = None
    image_message: str | None = None
    if ok and body.with_image:
        image_ok, image_message = await asyncio.to_thread(_ping_image_sync, base_url, model, api_key)
    return {
        "ok": ok,
        "message": message,
        "latency_ms": latency_ms,
        "image_ok": image_ok,
        "image_message": image_message,
    }


@router.post("/settings/available-models")
async def available_models(body: AvailableModelsBody):
    """用草稿 Key 调服务商 /models 拉真实清单（OpenAI 兼容协议）。

    失败返回 ok=false + 错误（不是 4xx/5xx）——前端静默回落到内置常用清单。
    """
    base_url = _validate_base_url(body.base_url)
    api_key = _resolve_draft_key(body.api_key, body.key_ref, base_url)
    if not api_key:
        raise HTTPException(status_code=400, detail="未提供 API Key——请先填写 Key")
    ok, models, err = await asyncio.to_thread(_list_models_sync, base_url, api_key)
    _kick_registry_refresh()
    return {"ok": ok, "models": models, "error": None if ok else err}


@router.put("/settings/keys/copy")
async def copy_settings_key(body: CopyKeyBody):
    """同厂商 Key 复用：服务端读源写目标。Key 只写不读铁律不破——不出库、不返回。"""
    src = (body.from_model or "").strip()
    dst = (body.to_model or "").strip()
    if not src or not dst:
        raise HTTPException(status_code=422, detail="from / to 不能为空")
    if src == dst:
        raise HTTPException(status_code=422, detail="源与目标不能是同一个模型")
    if cfg.get_profile(src) is None:
        raise HTTPException(status_code=404, detail=f"源模型 {src} 不存在")
    if cfg.get_profile(dst) is None:
        raise HTTPException(status_code=404, detail=f"目标模型 {dst} 不存在，请先保存模型配置")
    key = cfg.model_key(src)
    if not key:
        raise HTTPException(status_code=400, detail=f"源模型 {src} 未配置 API Key，无法复用")
    cfg.set_model_key(dst, key)
    await rebuild_agent()
    return {"ok": True}


@router.get("/settings/test")
async def test_settings(
    request: Request,
    role: str | None = Query(default=None, pattern="^(ocr)$"),
):
    """轻量连通性测试（仅剩文档解析 role=ocr）。

    模型连通性改走 POST /settings/test-model（测表单草稿值、不落库）。要求自定义头
    X-Sidecar-Ping：GET 是免预检的简单请求，无此防护时任意网站可静默触发「用存储的
    Key 向已配置 base_url 发出站请求」（本机开发模式无 token，主要是调用费消耗）；
    自定义头使跨站触发必须过 CORS 预检、被 origin 白名单挡住。
    """
    if (request.headers.get("x-sidecar-ping") or "") != "1":
        raise HTTPException(status_code=403, detail="缺少 X-Sidecar-Ping 头")
    if role == "ocr":
        result = await asyncio.to_thread(_test_ocr_sync)
        return {"ok": result == "ok", "role": role}
    raise HTTPException(status_code=422, detail="必须提供 role=ocr")
