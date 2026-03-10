from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class MetaThinkingManager:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.meta_thinking_chains: dict = {"chains": {}}
        self.meta_chain_theme_vectors: dict[str, list[float]] = {}
        self._config_path = Path(__file__).resolve().parent / "meta_thinking_chains.json"
        self._cache_path = Path(__file__).resolve().parent / "meta_chain_vector_cache.json"
        self._load_task = None

    async def load_config(self) -> None:
        if self._load_task is not None:
            await self._load_task
            return

        async def _load() -> None:
            try:
                self.meta_thinking_chains = json.loads(self._config_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                self.meta_thinking_chains = {"chains": {}}
                return
            except Exception as exc:
                logger.warning("[MetaThinkingManager] Failed to load config: %s", exc)
                self.meta_thinking_chains = {"chains": {}}
                return

            current_hash = self._get_file_hash(self._config_path)
            try:
                cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except Exception:
                cache = None
            if cache and cache.get("sourceHash") == current_hash:
                self.meta_chain_theme_vectors = cache.get("vectors") or {}
                return
            await self._build_and_save_meta_chain_theme_cache(current_hash)

        self._load_task = __import__("asyncio").create_task(_load())
        await self._load_task

    async def _build_and_save_meta_chain_theme_cache(self, config_hash: str | None) -> None:
        self.meta_chain_theme_vectors = {}
        for chain_name in (self.meta_thinking_chains.get("chains") or {}).keys():
            if chain_name == "default":
                continue
            vector = await self.engine.embedding_service.embed(chain_name)
            if vector:
                self.meta_chain_theme_vectors[chain_name] = vector
        self._cache_path.write_text(
            json.dumps(
                {
                    "sourceHash": config_hash,
                    "createdAt": datetime.now().isoformat(),
                    "vectors": self.meta_chain_theme_vectors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    async def process_meta_thinking_chain(
        self,
        chain_name: str,
        query_vector: list[float],
        user_content: str,
        ai_content: str,
        combined_query_for_display: str,
        k_sequence,
        use_group: bool,
        is_auto_mode: bool = False,
        auto_threshold: float = 0.65,
    ) -> str:
        if not (self.meta_thinking_chains.get("chains") or {}):
            await self.load_config()

        final_chain_name = chain_name or "default"
        if is_auto_mode:
            best_chain = "default"
            max_similarity = -1.0
            for theme_name, theme_vector in self.meta_chain_theme_vectors.items():
                similarity = self.engine._cosine_similarity(query_vector, theme_vector)
                if similarity > max_similarity:
                    max_similarity = similarity
                    best_chain = theme_name
            final_chain_name = best_chain if max_similarity >= auto_threshold else "default"

        chain_config = (self.meta_thinking_chains.get("chains") or {}).get(final_chain_name)
        if not chain_config:
            return f"[错误: 未找到\"{final_chain_name}\"思维链配置]"

        chain = list(chain_config.get("clusters") or [])
        final_k_sequence = list(k_sequence or chain_config.get("kSequence") or [])
        if not chain or not final_k_sequence or len(chain) != len(final_k_sequence):
            return f"[错误: \"{final_chain_name}\"思维链配置不完整]"

        cache_key = self.engine._generate_cache_key(
            user_content,
            ai_content or "",
            f"meta:{final_chain_name}:{'-'.join(str(k) for k in final_k_sequence)}:{int(use_group)}:{int(is_auto_mode)}:{combined_query_for_display}",
        )
        cached = self.engine._get_cached(cache_key)
        if cached and cached.get("content"):
            self._publish_vcp_info({**cached.get("vcpInfo", {}), "fromCache": True} if cached.get("vcpInfo") else None)
            return str(cached.get("content"))

        current_query_vector = query_vector
        activated_groups = None
        if use_group and self.engine.semantic_group_manager is not None:
            activated_groups = self.engine.semantic_group_manager.detect_and_activate_groups(user_content)
            if activated_groups:
                enhanced_vector = await self.engine.semantic_group_manager.get_enhanced_vector(
                    user_content,
                    activated_groups,
                    current_query_vector,
                )
                if enhanced_vector:
                    current_query_vector = enhanced_vector

        chain_results: list[dict] = []
        for index, cluster_name in enumerate(chain):
            stage_k = int(final_k_sequence[index])
            try:
                search_results = await self.engine.knowledge_base.search(cluster_name, current_query_vector, stage_k)
            except Exception as exc:
                chain_results.append({"clusterName": cluster_name, "stage": index + 1, "results": [], "k": stage_k, "error": str(exc)})
                break

            if not search_results:
                chain_results.append({"clusterName": cluster_name, "stage": index + 1, "results": [], "k": stage_k, "degraded": True})
                continue

            chain_results.append({"clusterName": cluster_name, "stage": index + 1, "results": search_results, "k": stage_k})
            if index >= len(chain) - 1:
                continue

            result_vectors: list[list[float]] = []
            for result in search_results:
                vector = result.get("vector")
                if vector is None:
                    vector = self.engine.knowledge_base.get_vector_by_text(cluster_name, result.get("text") or "")
                if vector:
                    result_vectors.append(vector)
            if not result_vectors:
                break
            average_vector = self._get_average_vector(result_vectors)
            if average_vector is None:
                break
            if self.engine.semantic_group_manager is not None:
                current_query_vector = self.engine.semantic_group_manager._weighted_average_vectors(
                    [query_vector, average_vector],
                    [0.8, 0.2],
                )
            else:
                current_query_vector = average_vector

        formatted = self._format_meta_thinking_results(chain_results, final_chain_name, activated_groups, is_auto_mode)
        vcp_info = {
            "type": "META_THINKING_CHAIN",
            "chainName": final_chain_name,
            "query": combined_query_for_display,
            "useGroup": use_group,
            "activatedGroups": list(activated_groups.keys()) if activated_groups else [],
            "stages": [
                {
                    "stage": result["stage"],
                    "clusterName": result["clusterName"],
                    "k": result.get("k"),
                    "resultCount": len(result.get("results") or []),
                    "results": [
                        {"text": item.get("text"), "score": item.get("score")}
                        for item in (result.get("results") or [])
                    ],
                }
                for result in chain_results
            ],
            "totalStages": len(chain),
            "kSequence": final_k_sequence,
        }
        self._publish_vcp_info(vcp_info)
        self.engine._set_cache(cache_key, {"content": formatted, "vcpInfo": vcp_info})
        return formatted

    def _get_average_vector(self, vectors: list[list[float]]) -> list[float] | None:
        if not vectors:
            return None
        if len(vectors) == 1:
            return vectors[0]
        dimension = len(vectors[0])
        merged = [0.0] * dimension
        for vector in vectors:
            for index, value in enumerate(vector[:dimension]):
                merged[index] += value
        for index in range(dimension):
            merged[index] /= len(vectors)
        return merged

    def _format_meta_thinking_results(self, chain_results: list[dict], chain_name: str, activated_groups, is_auto_mode: bool) -> str:
        content = f"\n[--- VCP元思考链: \"{chain_name}\" {'(Auto模式)' if is_auto_mode else ''} ---]\n"
        if activated_groups:
            group_names = [f"{name}({data['strength'] * 100:.0f}%)" for name, data in activated_groups.items()]
            content += f"[语义组增强: {', '.join(group_names)}]\n"
        if is_auto_mode:
            content += f"[自动选择主题: \"{chain_name}\"]\n"
        content += f"[推理链路径: {' → '.join(result['clusterName'] for result in chain_results)}]\n\n"
        for stage_result in chain_results:
            content += f"【阶段{stage_result['stage']}: {stage_result['clusterName']}】"
            if stage_result.get("degraded"):
                content += " [降级模式]\n"
            else:
                content += "\n"
            if stage_result.get("error"):
                content += f"  [错误: {stage_result['error']}]\n"
            elif not stage_result.get("results"):
                content += "  [未找到匹配的元逻辑模块]\n"
            else:
                content += f"  [召回 {len(stage_result['results'])} 个元逻辑模块]\n"
                for result in stage_result["results"]:
                    content += f"  * {str(result.get('text') or '').strip()}\n"
            content += "\n"
        content += "[--- 元思考链结束 ---]\n"
        return content

    def _get_file_hash(self, path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return None

    def _publish_vcp_info(self, payload: dict | None) -> None:
        if not payload:
            return
        push_vcp_info = getattr(self.engine, "push_vcp_info", None)
        if callable(push_vcp_info):
            try:
                push_vcp_info(payload)
            except Exception as exc:
                logger.warning("[MetaThinkingManager] push_vcp_info failed: %s", exc)