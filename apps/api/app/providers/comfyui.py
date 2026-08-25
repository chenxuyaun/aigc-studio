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
import uuid

import httpx

from app.providers.base import VideoProvider

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
    "class_type": "EmptyLatentVideo",
    "inputs": {"length": 81, "batch_size": 1, "width": 832, "height": 480},
  },
  "5": {
    "class_type": "KSamplerAdvanced",
    "inputs": {
      "model": ["1", 0],
      "positive": ["3", 0],
      "negative": ["3", 0],
      "latent_image": ["4", 0],
      "add_noise": "enable",
      "noise_seed": 0,
      "steps": 30,
      "cfg": 6.0,
      "sampler_name": "uni_pc",
      "scheduler": "simple",
      "start_at_step": 0,
      "end_at_step": 30,
      "return_with_leftover_noise": "disable",
    },
  },
  "6": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["5", 0], "vae": ["7", 0]},
  },
  "7": {
    "class_type": "VAELoader",
    "inputs": {"vae_name": "wan_2.1_vae.safetensors"},
  },
  "8": {
    "class_type": "SaveVideo",
    "inputs": {"images": ["6", 0], "filename_prefix": "saios_wan"},
  },
}


class ComfyUIProvider(VideoProvider):
    def __init__(self, base_url: str = "", api_key: str = "", default_model: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or "none"
        self.default_model = default_model or ""

    def _load_workflow(self) -> dict[str, object]:
        """读 workflow：优先环境变量/默认模型指定路径，否则内置 Wan 模板。"""
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
        injected = False
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            meta = node.get("_meta") or {}
            title = str(meta.get("title") or "")
            if node.get("class_type") == "CLIPTextEncode" and title.lower().startswith("prompt"):
                node["inputs"]["text"] = prompt
                injected = True
        if not injected:
            # 兜底：第一个 CLIPTextEncode
            for node in workflow.values():
                if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
                    node["inputs"]["text"] = prompt
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
        except Exception as exc:  # noqa: BLE001
            return {"task_id": "", "status": "failed", "error": str(exc)[:200]}

    async def poll(self, task_id: str) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(f"{self.base_url}/history/{task_id}")
                resp.raise_for_status()
                hist = resp.json()
            rec = (hist or {}).get(task_id)
            if not rec:
                return {"status": "running", "progress": 10}
            if rec.get("status", {}).get("completed") or rec.get("outputs"):
                # 找首个媒体输出（videos > gifs > images 图标兼容 ComfyUI 版本差异）
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
            err = (rec.get("status") or {}).get("messages") or rec.get("status", {}).get("status_str")
            return {"status": "failed", "error": str(err)[:200] or "ComfyUI 输出未知"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "error": str(exc)[:200]}