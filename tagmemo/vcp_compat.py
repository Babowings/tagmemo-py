from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
import secrets
from typing import Any


def extract_ai_text_from_response_payload(response_text: str) -> str:
    if not response_text:
        return ""

    lines = response_text.strip().splitlines()
    looks_like_sse = any(line.startswith("data: ") for line in lines)
    if looks_like_sse:
        parts: list[str] = []
        for line in lines:
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]" or not payload:
                continue
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            chunk = (
                (((obj.get("choices") or [{}])[0].get("delta") or {}).get("content"))
                or (((obj.get("choices") or [{}])[0].get("message") or {}).get("content"))
                or ""
            )
            if chunk:
                parts.append(chunk)
        if parts:
            return "".join(parts)

    try:
        obj = json.loads(response_text)
        content = (((obj.get("choices") or [{}])[0].get("message") or {}).get("content"))
        if isinstance(content, str):
            return content
    except Exception:
        pass

    return response_text


_DAILY_BLOCK_RE = re.compile(r"<<<DailyNoteStart>>>(.*?)<<<DailyNoteEnd>>>", re.S)


def extract_daily_note_payload(ai_text: str) -> dict[str, str] | None:
    if not ai_text:
        return None
    m = _DAILY_BLOCK_RE.search(ai_text)
    if not m:
        return None

    block = m.group(1).strip()
    maid_m = re.search(r"^\s*Maid:\s*(.+?)$", block, re.M)
    date_m = re.search(r"^\s*Date:\s*(.+?)$", block, re.M)
    content_m = re.search(r"^\s*Content:\s*([\s\S]*)$", block, re.M)

    maid_name = maid_m.group(1).strip() if maid_m else ""
    date_str = date_m.group(1).strip() if date_m else ""
    content = content_m.group(1).strip() if content_m else ""
    if not maid_name or not date_str or not content:
        return None
    return {"maid_name": maid_name, "date_string": date_str, "content_text": content}


def write_daily_note(root_path: str, maid_name: str, date_string: str, content_text: str) -> Path:
    root = Path(root_path).resolve()
    root.mkdir(parents=True, exist_ok=True)

    folder = maid_name
    alias = maid_name
    bracket = re.match(r"^\s*\[(.+?)\]\s*(.+?)\s*$", maid_name)
    if bracket:
        folder = bracket.group(1).strip()
        alias = bracket.group(2).strip()

    safe_folder = _safe_name(folder or "Root")
    safe_alias = _safe_name(alias or "AI")
    safe_date = _safe_name(date_string.replace("/", "-").replace(".", "-"))

    target_dir = root / safe_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    target_file = target_dir / f"{safe_date}-{safe_alias}.md"
    processed_content = _rewrite_local_file_urls(content_text)
    body = f"[{date_string}] - {alias}\n\n{processed_content}\n"
    target_file.write_text(body, encoding="utf-8")
    return target_file


def _safe_name(value: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "_", value).strip() or "untitled"


def _safe_asset_name(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", value)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return (cleaned[:80] if cleaned else "file")


def _file_uri_to_path(file_url: str) -> Path | None:
    parsed = urlparse(file_url)
    if parsed.scheme != "file":
        return None
    raw_path = unquote(parsed.path or "")
    resolved_path = url2pathname(raw_path)
    if os.name == "nt" and resolved_path.startswith("/") and len(resolved_path) > 2 and resolved_path[2] == ":":
        resolved_path = resolved_path[1:]
    if not resolved_path:
        return None
    return Path(resolved_path)


def _rewrite_local_file_urls(content_text: str) -> str:
    project_base_path = os.environ.get("PROJECT_BASE_PATH")
    server_port = os.environ.get("SERVER_PORT")
    var_http_url = os.environ.get("VarHttpUrl")
    image_key = os.environ.get("IMAGESERVER_IMAGE_KEY")
    file_key = os.environ.get("IMAGESERVER_FILE_KEY")

    if not project_base_path or not server_port or not var_http_url:
        return content_text

    result = content_text
    project_base = Path(project_base_path)

    def _copy_asset(file_url: str, *, kind: str, key: str | None, default_ext: str) -> str | None:
        if not key:
            return None
        source_path = _file_uri_to_path(file_url)
        if source_path is None or not source_path.exists() or not source_path.is_file():
            return None

        ext = source_path.suffix.lower() or default_ext
        base_name = _safe_asset_name(source_path.stem)
        generated_name = f"{secrets.token_hex(4)}_{base_name}{ext}"
        dest_dir = project_base / kind / "dailynote"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / generated_name
        dest_path.write_bytes(source_path.read_bytes())

        route = "images" if kind == "image" else "files"
        return f"{var_http_url}:{server_port}/pw={key}/{route}/dailynote/{generated_name}"

    if image_key:
        image_matches = list(re.finditer(r"!\[([^\]]*)\]\((file://[^)]+)\)", result))
        for match in image_matches:
            replacement = _copy_asset(match.group(2), kind="image", key=image_key, default_ext=".png")
            if replacement:
                result = result.replace(match.group(0), f"![{match.group(1)}]({replacement})", 1)

    if file_key:
        file_matches = list(re.finditer(r"(?<!!)\[([^\]]*)\]\((file://[^)]+)\)", result))
        for match in file_matches:
            replacement = _copy_asset(match.group(2), kind="file", key=file_key, default_ext=".bin")
            if replacement:
                result = result.replace(match.group(0), f"[{match.group(1)}]({replacement})", 1)

    return result


def replace_variable_placeholders(text: str, root_path: str) -> str:
    if not text:
        return text

    out = text
    root = Path(root_path)

    if "{{AllCharacterDiariesData}}" in out:
        diaries = []
        if root.exists():
            for entry in sorted(root.iterdir(), key=lambda x: x.name.lower()):
                if entry.is_dir():
                    diaries.append(entry.name)
        out = out.replace("{{AllCharacterDiariesData}}", "\n".join(diaries))

    for m in re.finditer(r"\{\{(.+?)日记本\}\}", out):
        raw_name = m.group(1).strip()
        folder = root / raw_name
        replacement = ""
        if folder.exists() and folder.is_dir():
            chunks: list[str] = []
            files = sorted(
                [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"}],
                key=lambda x: x.as_posix(),
            )
            for fp in files:
                try:
                    chunks.append(fp.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    continue
            replacement = "\n\n".join(chunks)
        out = out.replace(m.group(0), replacement)

    return out


@dataclass
class RAGBlockMeta:
    mode: str
    diary_names: list[str]
    modifiers: list[str]
    k_multiplier: float
    threshold_gate: bool
    aimemo: bool


class VCPPlaceholderProcessor:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.threshold = float(os.environ.get("RAG_SIMILARITY_THRESHOLD", "0.3"))

    async def process_system_messages(
        self,
        messages: list[dict],
        *,
        user_content: str,
        ai_content: str,
    ) -> list[dict]:
        updated = json.loads(json.dumps(messages))
        if not updated:
            return updated

        aimemo_licensed = False
        for message in updated:
            if message.get("role") == "system" and isinstance(message.get("content"), str):
                if "[[AIMemo=True]]" in message["content"]:
                    aimemo_licensed = True

        for idx, message in enumerate(updated):
            if message.get("role") != "system" or not isinstance(message.get("content"), str):
                continue
            content = message["content"]
            content = content.replace("[[AIMemo=True]]", "")
            content = await self._replace_rag_placeholders(
                content,
                user_content=user_content,
                ai_content=ai_content,
                aimemo_licensed=aimemo_licensed,
            )
            updated[idx]["content"] = content
        return updated

    async def refresh_rag_blocks_if_needed(
        self,
        messages: list[dict],
        *,
        new_context: dict[str, str],
    ) -> list[dict]:
        updated = json.loads(json.dumps(messages))
        rag_re = re.compile(
            r"<!-- VCP_RAG_BLOCK_START ([\s\S]*?) -->([\s\S]*?)<!-- VCP_RAG_BLOCK_END -->",
            re.M,
        )

        for i, message in enumerate(updated):
            if message.get("role") not in {"system", "assistant", "user"}:
                continue
            content = message.get("content")
            if not isinstance(content, str) or "VCP_RAG_BLOCK_START" not in content:
                continue

            matches = list(rag_re.finditer(content))
            if not matches:
                continue

            original_user = ""
            for j in range(i - 1, -1, -1):
                prev = updated[j]
                prev_content = prev.get("content")
                if prev.get("role") == "user" and isinstance(prev_content, str):
                    if prev_content.startswith("<!-- VCP_TOOL_PAYLOAD -->"):
                        continue
                    if prev_content.startswith("[系统提示:]"):
                        continue
                    if prev_content.startswith("[系统邀请指令:]"):
                        continue
                    original_user = prev_content
                    break

            for match in matches:
                whole = match.group(0)
                metadata_text = match.group(1)
                try:
                    metadata = json.loads(metadata_text)
                except Exception:
                    continue

                replacement = await self._resolve_block_from_metadata(
                    metadata,
                    user_content=original_user,
                    ai_content=new_context.get("lastAiMessage", ""),
                    tool_results_text=new_context.get("toolResultsText", ""),
                )
                content = content.replace(whole, replacement)

            message["content"] = content
        return updated

    async def _replace_rag_placeholders(
        self,
        content: str,
        *,
        user_content: str,
        ai_content: str,
        aimemo_licensed: bool,
    ) -> str:
        output = content

        rag_declarations = list(re.finditer(r"\[\[(.*?)日记本(.*?)\]\]", output))
        hybrid_declarations = list(re.finditer(r"《《(.*?)日记本(.*?)》》", output))

        for declaration in rag_declarations:
            placeholder = declaration.group(0)
            raw_name = declaration.group(1).strip()
            modifiers_text = declaration.group(2) or ""
            resolved = await self._resolve_placeholder(
                mode="rag",
                raw_name=raw_name,
                modifiers_text=modifiers_text,
                user_content=user_content,
                ai_content=ai_content,
                aimemo_licensed=aimemo_licensed,
                threshold_gate=False,
            )
            output = output.replace(placeholder, resolved)

        for declaration in hybrid_declarations:
            placeholder = declaration.group(0)
            raw_name = declaration.group(1).strip()
            modifiers_text = declaration.group(2) or ""
            resolved = await self._resolve_placeholder(
                mode="hybrid",
                raw_name=raw_name,
                modifiers_text=modifiers_text,
                user_content=user_content,
                ai_content=ai_content,
                aimemo_licensed=aimemo_licensed,
                threshold_gate=True,
            )
            output = output.replace(placeholder, resolved)

        return output

    async def _resolve_placeholder(
        self,
        *,
        mode: str,
        raw_name: str,
        modifiers_text: str,
        user_content: str,
        ai_content: str,
        aimemo_licensed: bool,
        threshold_gate: bool,
    ) -> str:
        diary_names = [n.strip() for n in raw_name.split("|") if n.strip()]
        if not diary_names:
            return ""

        k_multiplier = _extract_k_multiplier(modifiers_text)
        modifiers = _extract_modifiers(modifiers_text)
        use_rerank = "RERANK" in modifiers
        use_time = "TIME" in modifiers
        use_aimemo = aimemo_licensed and "AIMEMO" in modifiers

        if threshold_gate:
            query_vector = await self.engine.embedding_service.embed(
                f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content
            )
            if not query_vector:
                return ""
            max_similarity = 0.0
            for diary_name in diary_names:
                diary_vec = self.engine.knowledge_base.get_diary_name_vector(diary_name)
                if not diary_vec:
                    continue
                similarity = _cosine_similarity(query_vector, diary_vec)
                if similarity > max_similarity:
                    max_similarity = similarity
            if max_similarity < self.threshold:
                return ""

        if use_aimemo:
            contexts: list[str] = []
            for diary_name in diary_names:
                result = await self.engine.query(
                    user_content,
                    [{"role": "assistant", "content": ai_content}] if ai_content else [],
                    {
                        "diary_name": diary_name,
                        "use_rerank": use_rerank,
                        "use_time_aware": use_time,
                        "k_multiplier": k_multiplier,
                    },
                )
                memory_context = result.get("memory_context") or ""
                if memory_context and "没有找到相关的记忆片段" not in memory_context:
                    contexts.append(memory_context)
            if not contexts:
                content = "这是我获取的所有相关知识/记忆[[未找到相关记忆]]"
            else:
                content = "这是我获取的所有相关知识/记忆[[" + "\n\n".join(contexts) + "]]"
            meta = RAGBlockMeta(
                mode=mode,
                diary_names=diary_names,
                modifiers=sorted(modifiers),
                k_multiplier=k_multiplier,
                threshold_gate=threshold_gate,
                aimemo=True,
            )
            return _wrap_rag_block(content, meta)

        chunks: list[str] = []
        for diary_name in diary_names:
            result = await self.engine.query(
                user_content,
                [{"role": "assistant", "content": ai_content}] if ai_content else [],
                {
                    "diary_name": diary_name,
                    "use_rerank": use_rerank,
                    "use_time_aware": use_time,
                    "k_multiplier": k_multiplier,
                },
            )
            memory_context = result.get("memory_context") or ""
            if memory_context and "没有找到相关的记忆片段" not in memory_context:
                chunks.append(memory_context)

        merged = "\n\n".join(chunks)
        meta = RAGBlockMeta(
            mode=mode,
            diary_names=diary_names,
            modifiers=sorted(modifiers),
            k_multiplier=k_multiplier,
            threshold_gate=threshold_gate,
            aimemo=False,
        )
        return _wrap_rag_block(merged, meta) if merged else ""

    async def _resolve_block_from_metadata(
        self,
        metadata: dict[str, Any],
        *,
        user_content: str,
        ai_content: str,
        tool_results_text: str,
    ) -> str:
        diary_names = metadata.get("diary_names") or []
        if not isinstance(diary_names, list) or not diary_names:
            return ""

        modifiers = set(str(m).upper() for m in (metadata.get("modifiers") or []))
        k_multiplier = float(metadata.get("k_multiplier") or 1.0)
        threshold_gate = bool(metadata.get("threshold_gate", False))
        use_aimemo = bool(metadata.get("aimemo", False))

        refreshed_user = user_content
        if tool_results_text:
            refreshed_user = f"{user_content}\n\n[工具结果]\n{tool_results_text}"

        return await self._resolve_placeholder(
            mode=str(metadata.get("mode") or "rag"),
            raw_name="|".join(str(n) for n in diary_names),
            modifiers_text="::" + "::".join(modifiers) if modifiers else "",
            user_content=refreshed_user,
            ai_content=ai_content,
            aimemo_licensed=use_aimemo,
            threshold_gate=threshold_gate,
        ) if refreshed_user else ""


def _wrap_rag_block(content: str, metadata: RAGBlockMeta) -> str:
    metadata_json = json.dumps(
        {
            "mode": metadata.mode,
            "diary_names": metadata.diary_names,
            "modifiers": metadata.modifiers,
            "k_multiplier": metadata.k_multiplier,
            "threshold_gate": metadata.threshold_gate,
            "aimemo": metadata.aimemo,
        },
        ensure_ascii=False,
    )
    return f"<!-- VCP_RAG_BLOCK_START {metadata_json} -->{content}<!-- VCP_RAG_BLOCK_END -->"


def _extract_k_multiplier(modifiers_text: str) -> float:
    m = re.search(r":(\d+\.?\d*)", modifiers_text or "")
    if not m:
        return 1.0
    try:
        return max(0.1, min(10.0, float(m.group(1))))
    except Exception:
        return 1.0


def _extract_modifiers(modifiers_text: str) -> set[str]:
    parts = [p.strip() for p in (modifiers_text or "").split("::") if p.strip()]
    clean: set[str] = set()
    for part in parts:
        head = part.split(":", 1)[0].strip().upper()
        if head:
            clean.add(head)
    return clean


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    length = min(len(vec_a), len(vec_b))
    if length == 0:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(length):
        a = float(vec_a[i])
        b = float(vec_b[i])
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


_TOOL_REQUEST_RE = re.compile(
    r"<<<\[TOOL_REQUEST\]>>>([\s\S]*?)<<<\[END_TOOL_REQUEST\]>>>",
    re.I,
)


def parse_tool_requests(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    requests: list[dict[str, Any]] = []
    for block_match in _TOOL_REQUEST_RE.finditer(text):
        block = block_match.group(1)
        params: dict[str, str] = {}
        tool_name = ""
        for match in re.finditer(r"([\w_]+)\s*:\s*「始」([\s\S]*?)「末」\s*(?:,|$)", block):
            key = match.group(1)
            value = match.group(2).strip()
            if key == "tool_name":
                tool_name = value
            else:
                params[key] = value
        if tool_name:
            requests.append({"tool_name": tool_name, "params": params})
    return requests


def build_tool_payload_for_rag(tool_results: list[Any]) -> str:
    return json.dumps(tool_results, ensure_ascii=False)


def current_date_string() -> str:
    return datetime.now().strftime("%Y-%m-%d")
