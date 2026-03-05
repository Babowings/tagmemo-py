from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
    body = f"[{date_string}] - {alias}\n\n{content_text}\n"
    target_file.write_text(body, encoding="utf-8")
    return target_file


def _safe_name(value: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "_", value).strip() or "untitled"


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
