"""ComfyUI Provider：走 frp 隧道调用 GPU 节点的 ComfyUI（saiOS video 槽）。

协议：ComfyUI 原生 API
  POST {base}/prompt            body = workflow JSON（含 prompt 文本的节点会由模板替换）
  GET  {base}/history/{id}      轮询直到 completed → outputs 里取首个媒体文件
  GET  {base}/view?filename=..&subfolder=..&type=output   下载产物

Provider 返回内部 URL（http://host.docker.internal:7001/...），task_runner 的
_download_media 会去拉取；隧道服务口只绑云服务器内网，公网不可达。

workflow 模板：默认用内置的 Wan2.1-T2V 通用模板；也可经 hub 的 default_model
或 env COMFYUI_WORKFLOW_PATH 指向挂载的自定义 JSON。模板里的用户提示词节点
按 role 约定替换：class_type=CLIPTextEncode 且 title 以 "prompt" 开头。
"""

from __future__ import annotations

import json
import os

import httpx

from app.providers.base import ImageProvider, VideoProvider

_WAN_T2V_TEMPLATE = {
  "1": {
    "class_type": "UNETLoader",
    "inputs": {"unet_name": "wan2.1_t2v_1.3B_fp16.safetensors", "weight_dtype": "default"},
  },
  "2": {
    "class_type": "CLIPLoader",
    "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"},
  },
  "3": {
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "prompt"},
    "inputs": {"text": "", "clip": ["2", 0]},
  },
  "4": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留",
      "clip": ["2", 0],
    },
  },
  "5": {
    "class_type": "EmptyHunyuanLatentVideo",
    "inputs": {"width": 832, "height": 480, "length": 33, "batch_size": 1},
  },
  "6": {
    "class_type": "ModelSamplingSD3",
    "inputs": {"model": ["1", 0], "shift": 8.0},
  },
  "7": {
    "class_type": "KSampler",
    "inputs": {
      "model": ["6", 0],
      "positive": ["3", 0],
      "negative": ["4", 0],
      "latent_image": ["5", 0],
      "seed": 82628696717253,
      "steps": 30,
      "cfg": 6.0,
      "sampler_name": "uni_pc",
      "scheduler": "simple",
      "denoise": 1.0,
    },
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["7", 0], "vae": ["9", 0]},
  },
  "9": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "wan_2.1_vae.safetensors"},
  },
  "10": {
    "class_type": "CreateVideo",
    "inputs": {"images": ["8", 0], "fps": 16},
  },
  "11": {
    "class_type": "SaveVideo",
    "inputs": {"video": ["10", 0], "filename_prefix": "saios_wan", "format": "auto"},
  },
}

# 批16改：H3 改走容器 7860（fp8 模型 + turbo 8步 LoRA + video vae）。
# 容器 7860 ComfyUI 上有 minimax_h3_fl2v_turbo_8step LoRA，用它 8 步出片速度翻倍。
_H3_T2V_TEMPLATE = {
  "1": {
    "class_type": "UNETLoader",
    "inputs": {"unet_name": "minimax_h3_fl2va_pruned_fp8_scaled.safetensors", "weight_dtype": "default"},
  },
  "2": {
    "class_type": "LoraLoader",
    "inputs": {"model": ["1", 0], "clip": ["3", 0], "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", "strength_model": 1.0, "strength_clip": 1.0},
  },
  "3": {
    "class_type": "CLIPLoader",
    "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"},
  },
  "4": {
    "class_type": "MiniMaxH3ImageToVideo",
    "_meta": {"title": "prompt-h3"},
    "inputs": {"clip": ["2", 1], "vae": ["8", 0], "prompt": "", "width": 864, "height": 480, "length": 96},
  },
  "5": {
    "class_type": "ConditioningZeroOut",
    "inputs": {"conditioning": ["4", 0]},
  },
  "6": {
    "class_type": "KSampler",
    "inputs": {
      "model": ["2", 0],
      "positive": ["4", 0],
      "negative": ["5", 0],
      "latent_image": ["4", 1],
      "seed": 98712340123,
      "steps": 8,
      "cfg": 1.0,
      "sampler_name": "euler",
      "scheduler": "simple",
      "denoise": 1.0,
    },
  },
  "8": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"},
  },
  "7": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["6", 0], "vae": ["8", 0]},
  },
  "9": {
    "class_type": "CreateVideo",
    "inputs": {"images": ["7", 0], "fps": 24},
  },
  "10": {
    "class_type": "SaveVideo",
    "inputs": {"video": ["9", 0], "filename_prefix": "saios_h3", "format": "auto", "codec": "auto"},
  },
}


class ComfyUIProvider(VideoProvider):
    def __init__(self, base_url: str = "", api_key: str = "", default_model: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or "none"
        self.default_model = default_model or ""

    def _load_workflow(self) -> dict[str, object]:
        """读 workflow：default_model 含 h3/minimax 用 H3 模板；env/路径指定次之；否则 Wan 模板。"""
        m = (self.default_model or "").lower()
        if "h3" in m or "minimax" in m:
            return json.loads(json.dumps(_H3_T2V_TEMPLATE))
        path = os.environ.get("COMFYUI_WORKFLOW_PATH", "")
        if not path and self.default_model:
            # 允许以 default_model 存 JSON 路径（不便时忽略）
            if self.default_model.endswith(".json") and os.path.exists(self.default_model):
                path = self.default_model
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return json.loads(json.dumps(_WAN_T2V_TEMPLATE))

    def _inject_prompt(self, workflow: dict[str, object], prompt: str) -> dict[str, object]:
        """按 title 约定注入提示词：Wan=CLIPTextEncode.text；H3=MiniMaxH3ImageToVideo.prompt。"""
        injected = False
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            title = str((node.get("_meta") or {}).get("title") or "")
            field = "text" if "text" in inputs else ("prompt" if "prompt" in inputs else "")
            if not field:
                continue
            hit = title.lower().startswith("prompt") or (
                node.get("class_type") == "CLIPTextEncode" and not title
            )
            if hit:
                inputs[field] = prompt
                injected = True
        if not injected:
            # 兜底：第一个带 text/prompt 输入的节点
            for node in workflow.values():
                if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
                    for f in ("text", "prompt"):
                        if f in node["inputs"]:
                            node["inputs"][f] = prompt
                            injected = True
                            break
                if injected:
                    break
        return workflow

    async def submit(
        self, text: str, model: str = "", **kwargs: object
    ) -> dict[str, object]:
        if not self.base_url:
            return {"task_id": "", "status": "failed", "error": "未配置 ComfyUI 服务地址"}
        try:
            workflow = self._load_workflow()
            workflow = self._inject_prompt(workflow, text)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": workflow},
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key not in ("", "none") else None,
                )
                resp.raise_for_status()
                body = resp.json()
            prompt_id = str(body.get("prompt_id") or "")
            if not prompt_id:
                return {"task_id": "", "status": "failed", "error": "ComfyUI 未返回 prompt_id"}
            return {"task_id": prompt_id, "status": "running"}
        except Exception as exc:
            return {"task_id": "", "status": "failed", "error": str(exc)[:200]}

    async def poll(self, task_id: str, timeout: float = 720.0) -> dict[str, object]:
        """阻塞轮询到生成完成（task_runner 的视频分支只 poll 一次）。

        ComfyUI 是异步任务：提交后需持续查 /history 直到 completed。
        轮询间隔 8s；超时/失败如实返回。
        """
        import asyncio
        import time as _time

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(f"{self.base_url}/history/{task_id}")
                    resp.raise_for_status()
                    hist = resp.json()
                rec = (hist or {}).get(task_id)
                if not rec:
                    continue  # 记录尚未出现，等下一轮
                if rec.get("status", {}).get("completed") or rec.get("outputs"):
                    # 找首个媒体输出（videos > gifs > images 兼容 ComfyUI 版本差异）
                    outs = rec.get("outputs") or {}
                    for node_out in outs.values():
                        for key in ("videos", "gifs", "images"):
                            items = node_out.get(key) or []
                            if items:
                                f = items[0]
                                return {
                                    "status": "succeeded",
                                    "video_url": (
                                        f"{self.base_url}/view?filename={f['filename']}"
                                        f"&subfolder={f.get('subfolder','')}&type={f.get('type','output')}"
                                    ),
                                }
                    return {"status": "failed", "error": "ComfyUI 无媒体输出"}
                if (rec.get("status") or {}).get("status_str") == "running":
                    continue  # 生成中，继续等
                # 失败诊断（execution_error / 其他终态）
                msgs = (rec.get("status") or {}).get("messages") or []
                for m in msgs:
                    if isinstance(m, list) and m and m[0] == "execution_error":
                        return {"status": "failed", "error": str(m[1].get("exception_message") or m[1])[:200]}
                return {"status": "failed", "error": "ComfyUI 执行未成功"}
            except Exception:
                pass
            await asyncio.sleep(8)
        return {"status": "failed", "error": f"ComfyUI 生成超时({timeout}s)"}


# ── FLUX.1-schnell 文生图（图片走本地 GPU）───────────────────────────
# 依赖文件（ModelScope AI-ModelScope 镜像）：
#   diffusion_models/flux1-schnell.safetensors (23.8G)
#   text_encoders/t5xxl_fp8_e4m3fn.safetensors + clip_l.safetensors
#   vae/ae.safetensors
# schnell 是蒸馏模型：4 步、cfg 1.0、euler/simple，负向用空文本。
_FLUX_T2I_TEMPLATE = {
  "1": {
    "class_type": "UNETLoader",
    "inputs": {"unet_name": "flux1-schnell.safetensors", "weight_dtype": "default"},
  },
  "2": {
    "class_type": "DualCLIPLoader",
    "inputs": {
      "clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
      "clip_name2": "clip_l.safetensors",
      "type": "flux",
      "device": "default",
    },
  },
  "3": {
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "prompt"},
    "inputs": {"text": "", "clip": ["2", 0]},
  },
  "4": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "", "clip": ["2", 0]},
  },
  "5": {
    "class_type": "EmptySD3LatentImage",
    "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
  },
  "6": {
    "class_type": "KSampler",
    "inputs": {
      "model": ["1", 0],
      "positive": ["3", 0],
      "negative": ["4", 0],
      "latent_image": ["5", 0],
      "seed": 98712340123,
      "steps": 4,
      "cfg": 1.0,
      "sampler_name": "euler",
      "scheduler": "simple",
      "denoise": 1.0,
    },
  },
  "7": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "ae.safetensors"},
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["6", 0], "vae": ["7", 0]},
  },
  "9": {
    "class_type": "SaveImage",
    "inputs": {"images": ["8", 0], "filename_prefix": "saios_flux"},
  },
}


class ComfyUIImageProvider(ImageProvider):
    """ComfyUI 文生图 Provider：image 槽走本地 GPU（FLUX）。

    submit → /prompt 拿 prompt_id；poll → /history 等 completed，返回 image_url。
    """

    def __init__(self, base_url: str = "", api_key: str = "", default_model: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or "none"
        self.default_model = default_model or ""

    def _load_workflow(self) -> dict[str, object]:
        m = (self.default_model or "").lower()
        if "flux" in m or "schnell" in m:
            return json.loads(json.dumps(_FLUX_T2I_TEMPLATE))
        # 兜底 FLUX（本 provider 只服务 FLUX）
        return json.loads(json.dumps(_FLUX_T2I_TEMPLATE))

    def _inject_prompt(self, workflow: dict[str, object], prompt: str) -> dict[str, object]:
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict) or "text" not in inputs:
                continue
            title = str((node.get("_meta") or {}).get("title") or "")
            if title.lower().startswith("prompt") or (node.get("class_type") == "CLIPTextEncode" and not title):
                inputs["text"] = prompt
                return workflow
        # 兜底第一个 text 节点
        for node in workflow.values():
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict) and "text" in node["inputs"]:
                node["inputs"]["text"] = prompt
                break
        return workflow

    async def submit(self, prompt: str, model: str = "default", **kwargs: object) -> dict[str, object]:
        if not self.base_url:
            return {"task_id": "", "status": "failed", "error": "未配置 ComfyUI 服务地址"}
        try:
            workflow = self._load_workflow()
            workflow = self._inject_prompt(workflow, prompt)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/prompt",
                    json={"prompt": workflow},
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key not in ("", "none") else None,
                )
                resp.raise_for_status()
                body = resp.json()
            prompt_id = str(body.get("prompt_id") or "")
            if not prompt_id:
                return {"task_id": "", "status": "failed", "error": "ComfyUI 未返回 prompt_id"}
            return {"task_id": prompt_id, "status": "running"}
        except Exception as exc:
            return {"task_id": "", "status": "failed", "error": str(exc)[:200]}

    async def poll(self, task_id: str) -> dict[str, object]:
        import asyncio
        import time as _time

        deadline = _time.monotonic() + 300.0
        while _time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(f"{self.base_url}/history/{task_id}")
                    resp.raise_for_status()
                    hist = resp.json()
                rec = (hist or {}).get(task_id)
                if not rec:
                    continue
                if rec.get("outputs"):
                    for node_out in (rec.get("outputs") or {}).values():
                        items = node_out.get("images") or []
                        if items:
                            f = items[0]
                            return {
                                "status": "succeeded",
                                "image_url": (
                                    f"{self.base_url}/view?filename={f['filename']}"
                                    f"&subfolder={f.get('subfolder','')}&type={f.get('type','output')}"
                                ),
                            }
                    return {"status": "failed", "error": "ComfyUI 无图片输出"}
                if (rec.get("status") or {}).get("status_str") == "running":
                    continue
                msgs = (rec.get("status") or {}).get("messages") or []
                for m in msgs:
                    if isinstance(m, list) and m and m[0] == "execution_error":
                        return {"status": "failed", "error": str(m[1].get("exception_message") or m[1])[:200]}
                return {"status": "failed", "error": "ComfyUI 执行未成功"}
            except Exception:
                pass
            await asyncio.sleep(5)
        return {"status": "failed", "error": f"ComfyUI 图片生成超时({300}s)"}
