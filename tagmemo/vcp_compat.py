from __future__ import annotations

import ast
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
import secrets
from typing import Any

import httpx


_SYSTEM_NOTIFICATION_RE = re.compile(r"\[系统通知\][\s\S]*?\[系统通知结束\]", re.S)
_DYNAMIC_FOLD_RE = re.compile(r"<<<FOLD>>>([\s\S]*?)<<<UNFOLD>>>")
_META_THINKING_RE = re.compile(r"\[\[VCP元思考(.*?)\]\]")


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


def detect_tag_line(content: str) -> tuple[bool, str, str]:
    lines = content.split("\n")
    if not lines:
        return False, "", content
    last_line = lines[-1].strip()
    has_tag = bool(re.match(r"^Tag:\s*.+", last_line, re.I))
    return has_tag, last_line, "\n".join(lines[:-1]) if has_tag else content


def fix_tag_format(tag_line: str) -> str:
    fixed = tag_line.strip()
    fixed = re.sub(r"^tag:\s*", "Tag: ", fixed, flags=re.I)
    if not fixed.startswith("Tag: "):
        fixed = "Tag: " + fixed

    content = fixed[5:].strip()
    content = content.replace("：", "").replace("，", ", ").replace("、", ", ")
    content = re.sub(r",\s*", ", ", content)
    content = re.sub(r",\s{2,}", ", ", content)
    content = re.sub(r"\s+,", ",", content)
    content = re.sub(r"\s{2,}", " ", content).strip()
    return "Tag: " + content


def extract_tag_from_ai_response(text: str) -> str | None:
    match = re.search(r"\[\[Tag:\s*(.+?)\]\]", text, flags=re.I | re.S)
    if not match:
        return None
    return "Tag: " + match.group(1).strip()


async def generate_tags_with_ai(
    content: str,
    *,
    api_url: str,
    api_key: str,
    model: str,
    prompt_file: Path,
    max_tokens: int,
) -> str | None:
    if not api_url or not api_key:
        return None

    try:
        system_prompt = prompt_file.read_text(encoding="utf-8")
    except Exception:
        return None

    endpoint = api_url if "/chat/completions" in api_url else f"{api_url.rstrip('/')}/v1/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(1, 4):
            try:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                if response.status_code == 429 and attempt < 3:
                    await asyncio.sleep(5 * attempt)
                    continue
                if response.status_code in {500, 503} and attempt < 3:
                    await asyncio.sleep(attempt)
                    continue
                response.raise_for_status()
                payload = response.json()
                content_text = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
                return extract_tag_from_ai_response(content_text)
            except Exception:
                if attempt >= 3:
                    return None
                await asyncio.sleep(attempt)
    return None


async def process_tags_in_content(
    content: str,
    *,
    generator: Any | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    prompt_file: Path | None = None,
    max_tokens: int | None = None,
) -> str:
    has_tag, last_line, body_wo_tag = detect_tag_line(content)
    if has_tag:
        fixed = fix_tag_format(last_line)
        return body_wo_tag.rstrip("\n") + "\n" + fixed

    generator_fn = generator
    if generator_fn is None:
        resolved_prompt_file = prompt_file or (Path(__file__).resolve().parent.parent / os.environ.get("TagModelPrompt", "TagMaster.txt"))
        async def _default_generator(text: str) -> str | None:
            return await generate_tags_with_ai(
                text,
                api_url=api_url or os.environ.get("API_URL", ""),
                api_key=api_key or os.environ.get("API_Key", ""),
                model=model or os.environ.get("TagModel", "gpt-4o-mini"),
                prompt_file=resolved_prompt_file,
                max_tokens=max_tokens or int(os.environ.get("TagModelMaxTokens", "40000")),
            )
        generator_fn = _default_generator

    generated = await generator_fn(body_wo_tag)
    if not generated:
        return content

    extracted = extract_tag_from_ai_response(generated)
    if extracted:
        generated = extracted

    fixed = fix_tag_format(generated)
    return content.rstrip("\n") + "\n" + fixed


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


def update_daily_note(root_path: str, maid_name: str, date_string: str, content_text: str) -> Path:
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

    existing = target_file.read_text(encoding="utf-8") if target_file.exists() else f"[{date_string}] - {alias}\n\n"
    merged = existing.rstrip("\n") + "\n\n" + _rewrite_local_file_urls(content_text).strip() + "\n"
    target_file.write_text(merged, encoding="utf-8")
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


def _strip_nested_placeholders(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\[\[.*?日记本.*?\]\]", "[循环占位符已移除]", text)
    text = re.sub(r"<<.*?日记本>>", "[循环占位符已移除]", text)
    text = re.sub(r"《《.*?日记本.*?》》", "[循环占位符已移除]", text)
    text = re.sub(r"\{\{.*?日记本\}\}", "[循环占位符已移除]", text)
    return text


def _strip_system_notification(text: str) -> str:
    if not text:
        return text
    cleaned = _SYSTEM_NOTIFICATION_RE.sub("", text)
    cleaned = re.sub(r"\n---\n\*系统通知:[\s\S]*$", "", cleaned)
    return cleaned.strip()


def _is_likely_base64(text: str) -> bool:
    if not text or len(text) < 100:
        return False
    sample = text[:200]
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", sample):
        return False
    if len(text) % 4 not in {0, 2, 3}:
        return False
    unique_chars = len(set(sample))
    if unique_chars > 50:
        return True
    if len(text) > 200:
        return True
    return len(text) > 500


def _json_to_markdown(obj: Any, depth: int = 0) -> str:
    if obj is None:
        return ""
    if isinstance(obj, (str, int, float, bool)):
        return str(obj)

    indent = "  " * depth
    if isinstance(obj, list):
        parts: list[str] = []
        for item in obj:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
                continue
            rendered = _json_to_markdown(item, depth + 1).strip()
            if rendered:
                parts.append(f"{indent}- {rendered}")
        return "\n".join(parts)

    if isinstance(obj, dict):
        parts = []
        for key, value in obj.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                rendered = _json_to_markdown(value, depth + 1).strip()
                if rendered:
                    parts.append(f"{indent}# {key}:\n{rendered}")
                continue

            value_str = str(value)
            if len(value_str) > 200 and ("base64" in value_str.lower() or _is_likely_base64(value_str)):
                value_str = "[Data Omitted]"
            parts.append(f"{indent}* **{key}**: {value_str}")
        return "\n".join(parts)

    return str(obj)


def _parse_aggregate_syntax(raw_name: str, modifiers_text: str) -> dict[str, Any]:
    diary_names = [name.strip() for name in raw_name.split("|") if name.strip()]
    return {
        "diary_names": diary_names or ([raw_name.strip()] if raw_name.strip() else []),
        "k_multiplier": _extract_k_multiplier(modifiers_text),
        "is_aggregate": len(diary_names) > 1,
        "cleaned_modifiers": modifiers_text,
    }


def _get_average_threshold(
    diary_names: list[str],
    diary_configs: dict[str, dict[str, Any]],
    *,
    default_threshold: float,
) -> float:
    if not diary_names:
        return default_threshold
    total = 0.0
    count = 0
    for diary_name in diary_names:
        config = diary_configs.get(diary_name) or {}
        total += float(config.get("threshold", default_threshold))
        count += 1
    return total / count if count else default_threshold


def _read_full_diary(root_path: str, diary_name: str) -> str:
    root = Path(root_path)
    folder = root / diary_name
    if not folder.exists() or not folder.is_dir():
        return ""

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
    return _strip_nested_placeholders("\n\n".join(chunks))


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
            replacement = _strip_nested_placeholders("\n\n".join(chunks))
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

        clean_user_content = _strip_system_notification(user_content)
        clean_ai_content = ai_content or ""

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
            content = await self._replace_dynamic_fold_blocks(
                content,
                user_content=clean_user_content,
                ai_content=clean_ai_content,
            )
            content = await self._replace_meta_thinking_placeholders(
                content,
                user_content=clean_user_content,
                ai_content=clean_ai_content,
            )
            content = await self._replace_rag_placeholders(
                content,
                user_content=clean_user_content,
                ai_content=clean_ai_content,
                aimemo_licensed=aimemo_licensed,
            )
            updated[idx]["content"] = content
        return updated

    async def _replace_meta_thinking_placeholders(
        self,
        content: str,
        *,
        user_content: str,
        ai_content: str,
    ) -> str:
        if "[[VCP元思考" not in content:
            return content

        manager = getattr(self.engine, "meta_thinking_manager", None)
        if manager is None:
            return content

        combined_query = f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content
        query_vector = await self.engine.embedding_service.embed(combined_query)
        if not query_vector:
            return content

        output = content
        for match in list(_META_THINKING_RE.finditer(content)):
            raw = (match.group(1) or "").strip()
            chain_name = "default"
            use_group = False
            is_auto_mode = False
            auto_threshold = 0.65

            parts = [part.strip() for part in raw.lstrip(":").split("::") if part.strip()]
            for part in parts:
                lower_part = part.lower()
                if lower_part.startswith("auto"):
                    is_auto_mode = True
                    threshold_match = re.search(r":(\d+\.?\d*)", part)
                    if threshold_match:
                        auto_threshold = float(threshold_match.group(1))
                    continue
                if lower_part == "group":
                    use_group = True
                    continue
                chain_name = part

            replacement = await manager.process_meta_thinking_chain(
                chain_name,
                query_vector,
                user_content,
                ai_content,
                combined_query,
                None,
                use_group,
                is_auto_mode,
                auto_threshold,
            )
            output = output.replace(match.group(0), replacement, 1)
        return output

    async def _replace_dynamic_fold_blocks(
        self,
        content: str,
        *,
        user_content: str,
        ai_content: str,
    ) -> str:
        if "<<<FOLD>>>" not in content:
            return content

        output = content
        for match in list(_DYNAMIC_FOLD_RE.finditer(content)):
            replacement = await self._resolve_dynamic_fold_protocol(
                match.group(1),
                user_content=user_content,
                ai_content=ai_content,
            )
            output = output.replace(match.group(0), replacement)
        return output

    async def _resolve_dynamic_fold_protocol(
        self,
        fold_payload: str,
        *,
        user_content: str,
        ai_content: str,
    ) -> str:
        try:
            fold_obj = json.loads(fold_payload)
        except Exception:
            try:
                parsed = ast.literal_eval(fold_payload)
            except Exception:
                return fold_payload
            if not isinstance(parsed, dict):
                return fold_payload
            fold_obj = parsed

        if not fold_obj.get("vcp_dynamic_fold"):
            return fold_payload

        blocks = list(fold_obj.get("fold_blocks") or [])
        if not blocks:
            return ""
        blocks.sort(key=lambda item: float(item.get("threshold", 0.0)), reverse=True)
        fallback_block = blocks[-1]

        query_text = f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content
        if not query_text:
            return str(fallback_block.get("content") or "")

        query_vector = await self.engine.embedding_service.embed(query_text)
        desc_text = str(fold_obj.get("plugin_description") or "dynamic-fold")
        desc_vector = None
        knowledge_base = getattr(self.engine, "knowledge_base", None)
        get_plugin_vector = getattr(knowledge_base, "get_plugin_description_vector", None)
        if callable(get_plugin_vector):
            desc_vector = await get_plugin_vector(
                desc_text,
                self.engine.embedding_service.embed,
            )
        if not desc_vector:
            desc_vector = await self.engine.embedding_service.embed(desc_text)
        if not query_vector or not desc_vector:
            return str(fallback_block.get("content") or "")

        similarity = _cosine_similarity(query_vector, desc_vector)
        for block in blocks:
            if similarity >= float(block.get("threshold", 0.0)):
                return str(block.get("content") or "")

        return str(fallback_block.get("content") or "")

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
        combined_query = f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content
        aimemo_handler = getattr(self.engine, "ai_memo_handler", None)
        aimemo_requests: list[dict[str, Any]] = []

        rag_declarations = list(re.finditer(r"\[\[(.*?)日记本(.*?)\]\]", output))
        fulltext_declarations = list(re.finditer(r"<<(.*?)日记本>>", output))
        hybrid_declarations = list(re.finditer(r"《《(.*?)日记本(.*?)》》", output))

        for declaration in rag_declarations:
            placeholder = declaration.group(0)
            raw_name = declaration.group(1).strip()
            modifiers_text = declaration.group(2) or ""
            aggregate_info = _parse_aggregate_syntax(raw_name, modifiers_text)
            modifiers = _extract_modifiers(modifiers_text)
            if aimemo_handler is not None and aimemo_licensed and "AIMEMO" in modifiers:
                token = f"__AIMEMO_PLACEHOLDER_{len(aimemo_requests)}__"
                output = output.replace(placeholder, token, 1)
                aimemo_requests.append({"token": token, "db_names": aggregate_info["diary_names"]})
                continue
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

        for declaration in fulltext_declarations:
            placeholder = declaration.group(0)
            diary_name = declaration.group(1).strip()
            resolved = await self._resolve_fulltext_placeholder(
                diary_name=diary_name,
                user_content=user_content,
                ai_content=ai_content,
            )
            output = output.replace(placeholder, resolved)

        for declaration in hybrid_declarations:
            placeholder = declaration.group(0)
            raw_name = declaration.group(1).strip()
            modifiers_text = declaration.group(2) or ""
            aggregate_info = _parse_aggregate_syntax(raw_name, modifiers_text)
            modifiers = _extract_modifiers(modifiers_text)
            if aimemo_handler is not None and aimemo_licensed and "AIMEMO" in modifiers:
                if await self._passes_threshold_gate(
                    aggregate_info["diary_names"],
                    user_content=user_content,
                    ai_content=ai_content,
                ):
                    token = f"__AIMEMO_PLACEHOLDER_{len(aimemo_requests)}__"
                    output = output.replace(placeholder, token, 1)
                    aimemo_requests.append({"token": token, "db_names": aggregate_info["diary_names"]})
                else:
                    output = output.replace(placeholder, "", 1)
                continue
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

        if aimemo_requests:
            for index, request in enumerate(aimemo_requests):
                aggregated_result = await aimemo_handler.process_aimemo_aggregated(
                    request["db_names"],
                    user_content,
                    ai_content,
                    combined_query,
                )
                if index == 0:
                    replacement = aggregated_result
                else:
                    replacement = f"[AIMemo语义推理检索模式] 检索结果已在\"{'+'.join(request['db_names'])}\"日记本中合并展示，本次为跨库联合检索。"
                output = output.replace(request["token"], replacement, 1)

        return output

    async def _passes_threshold_gate(
        self,
        diary_names: list[str],
        *,
        user_content: str,
        ai_content: str,
    ) -> bool:
        if not diary_names:
            return False
        query_text = f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content
        query_vector = await self.engine.embedding_service.embed(query_text)
        if not query_vector:
            return False

        diary_configs = ((getattr(self.engine, "rag_params", {}) or {}).get("RAGDiaryPlugin") or {}).get("diary_tags") or {}
        if len(diary_names) > 1:
            threshold = _get_average_threshold(
                diary_names,
                diary_configs if isinstance(diary_configs, dict) else {},
                default_threshold=self.threshold,
            )
        else:
            config = (diary_configs if isinstance(diary_configs, dict) else {}).get(diary_names[0]) or {}
            threshold = float(config.get("threshold", self.threshold))

        max_similarity = 0.0
        for diary_name in diary_names:
            diary_vec = self.engine.get_enhanced_diary_vector(diary_name)
            if not diary_vec:
                diary_vec = self.engine.knowledge_base.get_diary_name_vector(diary_name)
            if not diary_vec:
                continue
            similarity = _cosine_similarity(query_vector, diary_vec)
            if similarity > max_similarity:
                max_similarity = similarity
        return max_similarity >= threshold

    async def _resolve_fulltext_placeholder(
        self,
        *,
        diary_name: str,
        user_content: str,
        ai_content: str,
    ) -> str:
        root_path = ((getattr(self.engine, "knowledge_base", None) or {}).config["root_path"]
                     if getattr(getattr(self.engine, "knowledge_base", None), "config", None)
                     else "")
        if not root_path or not diary_name:
            return ""

        query_text = f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content
        query_vector = await self.engine.embedding_service.embed(query_text)
        if not query_vector:
            return ""

        get_enhanced = getattr(self.engine, "get_enhanced_diary_vector", None)
        diary_vec = get_enhanced(diary_name) if callable(get_enhanced) else None
        if not diary_vec:
            diary_vec = self.engine.knowledge_base.get_diary_name_vector(diary_name)
        if not diary_vec:
            return ""

        similarity = _cosine_similarity(query_vector, diary_vec)
        if similarity < self.threshold:
            return ""

        return _read_full_diary(root_path, diary_name)

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
        aggregate_info = _parse_aggregate_syntax(raw_name, modifiers_text)
        diary_names = aggregate_info["diary_names"]
        if not diary_names:
            return ""

        k_multiplier = aggregate_info["k_multiplier"]
        modifiers = _extract_modifiers(modifiers_text)
        use_rerank = "RERANK" in modifiers
        use_time = "TIME" in modifiers
        use_aimemo = aimemo_licensed and "AIMEMO" in modifiers

        if aggregate_info["is_aggregate"] and not use_aimemo:
            return await self._process_aggregate_retrieval(
                mode=mode,
                diary_names=diary_names,
                user_content=user_content,
                ai_content=ai_content,
                use_rerank=use_rerank,
                use_time=use_time,
                k_multiplier=k_multiplier,
                threshold_gate=threshold_gate,
            )

        if threshold_gate:
            if not await self._passes_threshold_gate(
                diary_names,
                user_content=user_content,
                ai_content=ai_content,
            ):
                return ""

        if use_aimemo:
            handler = getattr(self.engine, "ai_memo_handler", None)
            if handler is not None:
                content = await handler.process_aimemo_aggregated(
                    diary_names,
                    user_content,
                    ai_content,
                    f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content,
                )
            else:
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

    async def _process_aggregate_retrieval(
        self,
        *,
        mode: str,
        diary_names: list[str],
        user_content: str,
        ai_content: str,
        use_rerank: bool,
        use_time: bool,
        k_multiplier: float,
        threshold_gate: bool,
    ) -> str:
        query_text = f"[AI]: {ai_content}\n[User]: {user_content}" if ai_content else user_content
        query_vector = await self.engine.embedding_service.embed(query_text)
        if not query_vector:
            return ""

        diary_configs = ((getattr(self.engine, "rag_params", {}) or {}).get("RAGDiaryPlugin") or {}).get("diary_tags") or {}
        avg_threshold = _get_average_threshold(
            diary_names,
            diary_configs if isinstance(diary_configs, dict) else {},
            default_threshold=self.threshold,
        )

        scores: list[tuple[str, float]] = []
        max_similarity = 0.0
        for diary_name in diary_names:
            diary_vec = self.engine.get_enhanced_diary_vector(diary_name)
            if not diary_vec:
                diary_vec = self.engine.knowledge_base.get_diary_name_vector(diary_name)
            if not diary_vec:
                continue
            similarity = _cosine_similarity(query_vector, diary_vec)
            scores.append((diary_name, similarity))
            max_similarity = max(max_similarity, similarity)

        if not scores:
            return ""
        if threshold_gate and max_similarity < avg_threshold:
            return ""

        rag_config = (getattr(self.engine, "rag_params", {}) or {}).get("RAGDiaryPlugin") or {}
        temperature = float(rag_config.get("aggregateTemperature", 3.0))
        exp_scores = [math.exp(score * temperature) for _, score in scores]
        total_exp = sum(exp_scores) or 1.0

        chunks: list[str] = []
        for (diary_name, _score), exp_score in zip(scores, exp_scores):
            local_multiplier = max(0.1, round(k_multiplier * len(scores) * (exp_score / total_exp), 3))
            result = await self.engine.query(
                user_content,
                [{"role": "assistant", "content": ai_content}] if ai_content else [],
                {
                    "diary_name": diary_name,
                    "use_rerank": use_rerank,
                    "use_time_aware": use_time,
                    "k_multiplier": local_multiplier,
                },
            )
            memory_context = result.get("memory_context") or ""
            if memory_context and "没有找到相关的记忆片段" not in memory_context:
                chunks.append(memory_context)

        merged = "\n\n".join(chunks)
        meta = RAGBlockMeta(
            mode=mode,
            diary_names=[name for name, _ in scores],
            modifiers=[],
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
    if not tool_results:
        return ""

    rendered: list[str] = []
    for result in tool_results:
        if isinstance(result, str):
            rendered.append(result)
            continue
        rendered.append(_json_to_markdown(result))
    return "\n\n".join(part for part in rendered if part).strip()


def current_date_string() -> str:
    return datetime.now().strftime("%Y-%m-%d")
