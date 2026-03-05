#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv


@dataclass
class Stats:
    total: int = 0
    processed: int = 0
    fixed: int = 0
    generated: int = 0
    skipped: int = 0
    errors: int = 0


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


def is_tag_format_valid(tag_line: str) -> bool:
    line = tag_line.strip()
    if not line.startswith("Tag: "):
        return False
    if re.search(r"[，：、]", line):
        return False
    body = line[5:]
    if "," in body and (", " not in body or re.search(r",\S|,\s{2,}", body)):
        return False
    return True


def extract_tag_from_ai_response(text: str) -> str | None:
    m = re.search(r"\[\[Tag:\s*(.+?)\]\]", text, flags=re.I | re.S)
    if not m:
        return None
    return "Tag: " + m.group(1).strip()


async def generate_tags_with_ai(content: str, *, api_url: str, api_key: str, model: str, prompt_file: Path, max_tokens: int) -> str | None:
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
                resp = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                if resp.status_code == 429 and attempt < 3:
                    await asyncio.sleep(5 * attempt)
                    continue
                if resp.status_code in {500, 503} and attempt < 3:
                    await asyncio.sleep(attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content_text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
                return extract_tag_from_ai_response(content_text)
            except Exception:
                if attempt >= 3:
                    return None
                await asyncio.sleep(attempt)
    return None


async def process_file(path: Path, cfg: dict, stats: Stats) -> None:
    stats.total += 1
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        stats.errors += 1
        return

    has_tag, last_line, body_wo_tag = detect_tag_line(content)
    new_tag: str | None = None
    updated = content

    if has_tag:
        if not is_tag_format_valid(last_line):
            new_tag = fix_tag_format(last_line)
            updated = body_wo_tag.rstrip("\n") + "\n" + new_tag
            stats.fixed += 1
        else:
            stats.skipped += 1
            return
    else:
        generated = await generate_tags_with_ai(
            body_wo_tag,
            api_url=cfg["api_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            prompt_file=cfg["prompt_file"],
            max_tokens=cfg["max_tokens"],
        )
        if generated:
            updated = content.rstrip("\n") + "\n" + fix_tag_format(generated)
            stats.generated += 1
        else:
            stats.skipped += 1
            return

    path.write_text(updated, encoding="utf-8")
    stats.processed += 1


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="VCP 日记批量 Tag 处理工具 (Python 对齐版)")
    parser.add_argument("target", nargs="?", default=".", help="目标目录")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / "config.env")

    cfg = {
        "model": os.environ.get("TagModel", "gpt-4o-mini"),
        "max_tokens": int(os.environ.get("TagModelMaxTokens", "40000")),
        "prompt_file": project_root / os.environ.get("TagModelPrompt", "TagMaster.txt"),
        "api_key": os.environ.get("API_Key", ""),
        "api_url": os.environ.get("API_URL", ""),
    }

    target = Path(args.target).resolve()
    files = [p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"}]

    stats = Stats()
    for p in files:
        await process_file(p, cfg, stats)

    print("[TagProcessor] done", stats)
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
