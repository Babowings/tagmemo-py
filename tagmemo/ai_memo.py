from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)


class AIMemoHandler:
    def __init__(self, engine, cache: dict[str, dict]) -> None:
        self.engine = engine
        self.config: dict[str, str | int] = {}
        self.prompt_template = ""
        self.cache = cache

    async def load_config(self) -> None:
        self.config = {
            "model": os.environ.get("AIMemoModel", ""),
            "batch_size": int(os.environ.get("AIMemoBatch", "5") or 5),
            "url": os.environ.get("AIMemoUrl", ""),
            "api_key": os.environ.get("AIMemoApi", ""),
            "max_tokens_per_batch": int(os.environ.get("AIMemoMaxTokensPerBatch", "60000") or 60000),
            "prompt_file": os.environ.get("AIMemoPrompt", "AIMemoPrompt.txt"),
        }
        prompt_path = Path(__file__).resolve().parent / str(self.config["prompt_file"])
        try:
            self.prompt_template = prompt_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("[AIMemoHandler] Failed to load prompt template: %s", exc)
            self.prompt_template = ""

    def is_configured(self) -> bool:
        return bool(
            self.config.get("url")
            and self.config.get("api_key")
            and self.config.get("model")
            and self.prompt_template
        )

    async def process_aimemo(self, db_name: str, user_content: str, ai_content: str, combined_query_for_display: str) -> str:
        return await self.process_aimemo_aggregated([db_name], user_content, ai_content, combined_query_for_display)

    async def process_aimemo_aggregated(
        self,
        db_names: list[str],
        user_content: str,
        ai_content: str,
        combined_query_for_display: str,
    ) -> str:
        if not self.is_configured():
            return "[AIMemo功能未配置]"

        try:
            unique_db_names = [name for name in dict.fromkeys(db_names) if name]
            cache_key = self._get_cache_key(unique_db_names, user_content, ai_content)
            cached = self._get_cache(cache_key)
            if cached:
                self._publish_vcp_info({**cached.get("vcpInfo", {}), "fromCache": True} if cached.get("vcpInfo") else None)
                return str(cached.get("content") or "")

            all_diary_files: list[dict] = []
            loaded_diaries: list[str] = []
            for db_name in unique_db_names:
                files = await self._get_diary_files(db_name)
                if not files:
                    continue
                all_diary_files.extend([{**file_info, "db_name": db_name} for file_info in files])
                loaded_diaries.append(db_name)

            if not all_diary_files:
                return "[所有日记本均为空或无法访问]"

            total_file_tokens = sum(int(file_info.get("tokens") or 0) for file_info in all_diary_files)
            total_tokens = total_file_tokens + 10000
            if total_tokens > int(self.config["max_tokens_per_batch"]):
                result_object = await self._process_batched_aggregated(
                    loaded_diaries,
                    all_diary_files,
                    user_content,
                    ai_content,
                    combined_query_for_display,
                )
            else:
                result_object = await self._process_single_aggregated(
                    loaded_diaries,
                    all_diary_files,
                    user_content,
                    ai_content,
                    combined_query_for_display,
                )

            self._publish_vcp_info(result_object.get("vcpInfo"))
            self._set_cache(cache_key, result_object)
            return str(result_object.get("content") or "")
        except Exception as exc:
            logger.warning("[AIMemoHandler] Aggregated processing failed: %s", exc)
            return f"[AIMemo聚合处理失败: {exc}]"

    def _get_cache_key(self, db_names: list[str], user_content: str, ai_content: str) -> str:
        payload = f"{','.join(sorted(db_names))}|{user_content}|{ai_content}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_cache(self, key: str) -> dict | None:
        entry = self.cache.get(key)
        if not entry:
            return None
        now_ms = datetime.now().timestamp() * 1000
        if now_ms - float(entry.get("timestamp") or 0) > float(getattr(self.engine, "ai_memo_cache_ttl", 1800000)):
            self.cache.pop(key, None)
            return None
        return entry.get("result")

    def _set_cache(self, key: str, result: dict) -> None:
        max_size = int(getattr(self.engine, "ai_memo_cache_max_size", 50) or 50)
        if len(self.cache) >= max_size:
            oldest_key = next(iter(self.cache))
            self.cache.pop(oldest_key, None)
        self.cache[key] = {"result": result, "timestamp": datetime.now().timestamp() * 1000}

    def _publish_vcp_info(self, payload: dict | None) -> None:
        if not payload:
            return
        push_vcp_info = getattr(self.engine, "push_vcp_info", None)
        if callable(push_vcp_info):
            try:
                push_vcp_info(payload)
            except Exception as exc:
                logger.warning("[AIMemoHandler] push_vcp_info failed: %s", exc)

    async def _process_single_aggregated(
        self,
        db_names: list[str],
        diary_files: list[dict],
        user_content: str,
        ai_content: str,
        combined_query_for_display: str,
    ) -> dict:
        knowledge_base = self._combine_files(diary_files)
        prompt = self._build_prompt(knowledge_base, user_content, ai_content)
        ai_response = await self._call_ai_model(prompt)
        if not ai_response:
            return {"content": "[AI模型调用失败]", "vcpInfo": None}
        extracted_memories = self._extract_memories(ai_response)
        return {
            "content": f"[跨库联合检索: {' + '.join(db_names)}]\n{extracted_memories}",
            "vcpInfo": {
                "type": "AI_MEMO_RETRIEVAL",
                "dbNames": db_names,
                "query": combined_query_for_display,
                "mode": "aggregated_single",
                "diaryCount": len(db_names),
                "fileCount": len(diary_files),
                "rawResponse": ai_response,
                "extractedMemories": extracted_memories,
            },
        }

    async def _process_batched_aggregated(
        self,
        db_names: list[str],
        diary_files: list[dict],
        user_content: str,
        ai_content: str,
        combined_query_for_display: str,
    ) -> dict:
        batches = self._split_files_into_batches(diary_files)
        batch_results: list[str] = []
        batch_size = int(self.config["batch_size"])
        for i in range(0, len(batches), batch_size):
            batch_group = batches[i:i + batch_size]
            group_results = await asyncio.gather(
                *[
                    self._process_batch(batch, user_content, ai_content, i + idx + 1, len(batches))
                    for idx, batch in enumerate(batch_group)
                ]
            )
            batch_results.extend(group_results)
        merged_memories = self._merge_batch_results(batch_results)
        return {
            "content": f"[跨库联合检索: {' + '.join(db_names)}]\n{merged_memories}",
            "vcpInfo": {
                "type": "AI_MEMO_RETRIEVAL",
                "dbNames": db_names,
                "query": combined_query_for_display,
                "mode": "aggregated_batched",
                "diaryCount": len(db_names),
                "fileCount": len(diary_files),
                "batchCount": len(batches),
                "extractedMemories": merged_memories,
            },
        }

    async def _process_batch(
        self,
        batch_files: list[dict],
        user_content: str,
        ai_content: str,
        batch_index: int,
        total_batches: int,
    ) -> str:
        knowledge_base = self._combine_files(batch_files)
        prompt = self._build_prompt(knowledge_base, user_content, ai_content)
        ai_response = await self._call_ai_model(prompt)
        if not ai_response:
            logger.warning("[AIMemoHandler] Batch %d/%d failed", batch_index, total_batches)
            return ""
        return self._extract_memories(ai_response)

    async def _get_diary_files(self, db_name: str) -> list[dict]:
        root_path = Path(str(getattr(self.engine, "config", {}).get("root_path") or ""))
        diary_dir = root_path / db_name
        try:
            file_list = sorted(diary_dir.iterdir(), key=lambda path: path.name.lower())
        except FileNotFoundError:
            return []
        except Exception as exc:
            logger.warning("[AIMemoHandler] Failed to read diary directory %s: %s", diary_dir, exc)
            return []

        result: list[dict] = []
        for file_path in file_list:
            if not file_path.is_file() or file_path.suffix.lower() not in {".txt", ".md"}:
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("[AIMemoHandler] Failed to read diary file %s: %s", file_path, exc)
                continue
            result.append({
                "name": file_path.name,
                "content": content,
                "tokens": self._estimate_tokens(content),
            })
        return result

    def _split_files_into_batches(self, files: list[dict]) -> list[list[dict]]:
        max_tokens = int(self.config["max_tokens_per_batch"]) - 10000
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        current_tokens = 0
        for file_info in files:
            tokens = int(file_info.get("tokens") or 0)
            if not current_batch or current_tokens + tokens <= max_tokens:
                current_batch.append(file_info)
                current_tokens += tokens
                continue
            batches.append(current_batch)
            current_batch = [file_info]
            current_tokens = tokens
        if current_batch:
            batches.append(current_batch)
        return batches or [files]

    def _combine_files(self, files: list[dict]) -> str:
        chunks: list[str] = []
        for file_info in files:
            prefix = f"=== {file_info['db_name']}日记本 ===\n" if file_info.get("db_name") else ""
            chunks.append(prefix + str(file_info.get("content") or ""))
        return "\n\n---\n\n".join(chunks)

    def _merge_batch_results(self, results: list[str]) -> str:
        valid_results = [
            result for result in results
            if result and "[[未找到相关记忆]]" not in result and "[[知识库为空]]" not in result
        ]
        if not valid_results:
            return "这是我获取的所有相关知识/记忆[[未找到相关记忆]]"
        all_blocks: list[str] = []
        for result in valid_results:
            all_blocks.extend(self._extract_memory_blocks(result))
        if not all_blocks:
            return "这是我获取的所有相关知识/记忆[[未找到相关记忆]]"
        unique_blocks = list(dict.fromkeys(all_blocks))
        return "这是我获取的所有相关知识/记忆" + "".join(unique_blocks)

    def _extract_memory_blocks(self, text: str) -> list[str]:
        return [f"[[{match.group(1)}]]" for match in re.finditer(r"\[\[([\s\S]*?)\]\]", text)]

    def _build_prompt(self, knowledge_base: str, user_content: str, ai_content: str) -> str:
        timezone_name = str(getattr(self.engine, "config", {}).get("timezone") or os.environ.get("DEFAULT_TIMEZONE", "Asia/Shanghai"))
        now = datetime.now(ZoneInfo(timezone_name))
        prompt = self.prompt_template
        prompt = prompt.replace("{{knowledge_base}}", knowledge_base)
        prompt = prompt.replace("{{current_user_prompt}}", user_content or "")
        prompt = prompt.replace("{{last_assistant_response}}", ai_content or "[无AI回复]")
        prompt = prompt.replace("{{Date}}", now.strftime("%Y-%m-%d"))
        prompt = prompt.replace("{{Time}}", now.strftime("%H:%M:%S"))
        return prompt

    async def _call_ai_model(self, prompt: str) -> str | None:
        endpoint = str(self.config.get("url") or "")
        if not endpoint:
            return None
        if "/chat/completions" not in endpoint:
            endpoint = f"{endpoint.rstrip('/')}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.config.get('api_key')}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.get("model"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 40000,
        }

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                if response.status_code in {500, 503} and attempt < 3:
                    await asyncio.sleep(2)
                    continue
                response.raise_for_status()
                content = (((response.json().get("choices") or [{}])[0].get("message") or {}).get("content"))
                if not content:
                    return None
                return self._handle_repetitive_output(str(content))
            except Exception as exc:
                if attempt >= 3:
                    logger.warning("[AIMemoHandler] AI call failed: %s", exc)
                    return None
                await asyncio.sleep(2)
        return None

    def _extract_memories(self, ai_response: str) -> str:
        if not ai_response:
            return "[AI未返回有效响应]"
        standard_match = re.search(r"这是我获取的所有相关知识/记忆(\[\[[\s\S]*?\]\])+", ai_response)
        if standard_match:
            return standard_match.group(0)
        memory_blocks = self._extract_memory_blocks(ai_response)
        if memory_blocks:
            return "这是我获取的所有相关知识/记忆" + "".join(memory_blocks)
        return f"这是我获取的所有相关知识/记忆[[{ai_response}]]"

    def _estimate_tokens(self, text: str) -> int:
        chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", text or ""))
        other_chars = len(text or "") - chinese_chars
        return int((chinese_chars * 1.5 + other_chars * 0.25) + 0.999999)

    def _handle_repetitive_output(self, text: str) -> str:
        lines = [line for line in text.split("\n") if line.strip()]
        if len(lines) < 10:
            return text
        repetition_found = False
        first_occurrence_end_index = -1
        for unit_size in range(2, len(lines) // 2 + 1):
            last_unit = "\n".join(lines[len(lines) - unit_size:])
            second_last_unit = "\n".join(lines[len(lines) - 2 * unit_size:len(lines) - unit_size])
            if last_unit != second_last_unit:
                continue
            for i in range(0, len(lines) - 2 * unit_size + 1):
                current_slice = "\n".join(lines[i:i + unit_size])
                if current_slice != last_unit:
                    continue
                next_slice = "\n".join(lines[i + unit_size:i + 2 * unit_size])
                if next_slice == last_unit:
                    repetition_found = True
                    first_occurrence_end_index = i + unit_size
                    break
            if repetition_found:
                break
        return "\n".join(lines[:first_occurrence_end_index]) if repetition_found else text