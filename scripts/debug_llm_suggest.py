"""诊断 LLM 兜底候选：跑一批真实调用，把模型的原始输出打出来。

用途：当 `POST /api/exercise-mappings/llm-suggest` 返回 accepted=0 时，
用它看清模型到底输出成什么样（是 JSON、是散文、还是被截断）。

**会真实调用 LLM，消耗额度**，默认只跑 3 个动作 1 批。

在容器内运行（项目根目录）：
    docker compose exec backend python scripts/debug_llm_suggest.py
    docker compose exec backend python scripts/debug_llm_suggest.py --limit 5
    docker compose exec backend python scripts/debug_llm_suggest.py --names 哑铃火箭推 扩胸开合

本脚本不写数据库、不改映射，只打印诊断信息。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.adapters import llm  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services.exercise_mapping_candidates import (  # noqa: E402
    classify_applicability,
    extract_tokens,
    generate_candidates,
)
from app.services.exercise_mapping_llm import (  # noqa: E402
    _load_movement_names,
    build_prompt,
    parse_response,
    validate_candidate,
)


def pick_targets(limit: int) -> list[str]:
    """与 _select_targets 同口径：适用力量动作里没有自动候选的。"""
    names = _load_movement_names()
    picked = [
        n
        for n in names
        if classify_applicability(n)[0] and not generate_candidates(n)
    ]
    picked.sort()
    return picked[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="取几个无候选动作（默认 3）")
    parser.add_argument("--names", nargs="*", help="手动指定动作名（覆盖 --limit）")
    parser.add_argument("--max-chars", type=int, default=3000, help="原始输出最多打印多少字符")
    parser.add_argument("--max-tokens", type=int, default=2048, help="本次调用输出上限")
    args = parser.parse_args()

    targets = args.names or pick_targets(max(1, args.limit))
    if not targets:
        print("没有找到无候选动作，无可诊断内容。")
        return 0

    print("=" * 70)
    print(f"目标动作（{len(targets)} 个）")
    for n in targets:
        t = extract_tokens(n)
        print(f"  · {n}  ｜ 部位={t['part']} 器械={t['equipment']} 动作={t['movements']}")
    print("=" * 70)

    messages = build_prompt(targets)
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    print(f"prompt: {len(messages)} 条消息，{prompt_chars} 字符（≈{prompt_chars // 2} tokens）")

    session = SessionLocal()
    try:
        provider = llm.get_default_provider(session)
        model = llm.get_selected_model(session, provider)
        has_key = bool(llm.resolve_api_key(session, provider))
        print(f"provider={provider}  model={model}  key={'已配置' if has_key else '缺失'}")
        if not has_key:
            print("\n未配置 LLM key，无法诊断。请先在「设置 → AI」里填 key 或配环境变量。")
            return 1
        print("-" * 70)

        result = llm.chat(
            messages,
            session=session,
            purpose="exercise_mapping_debug",
            max_tokens=args.max_tokens,
        )
        content = result.get("content") or ""
        print(f"completion_tokens={result.get('completion_tokens')}  "
              f"prompt_tokens={result.get('prompt_tokens')}  "
              f"content_chars={len(content)}")
        print("-" * 70)

        stripped = llm.strip_think(content)
        if len(stripped) != len(content.strip()):
            print(f"[strip_think] 剥离了 {len(content.strip()) - len(stripped)} 字符的 thinking 块")

        print(f"【原始输出（前 {args.max_chars} 字符）】")
        print(content[: args.max_chars])
        print("=" * 70)

        parsed = parse_response(content)
        print(f"parse_response → {len(parsed)} 条")
        for item in parsed:
            ok = validate_candidate(
                item["category"], item["exercise_name"] or "", catalog=None
            )
            mark = "OK " if ok else "REJ"
            print(f"  [{mark}] {item['xunji_name']} -> "
                  f"{item['category']}/{item['exercise_name'] or '(空)'}")
        if not parsed:
            print("\n解析为空。常见原因：")
            print("  1. 模型输出被 max_tokens 截断（JSON 不完整）")
            print("  2. 模型只写了散文/解释，没给 JSON 数组")
            print("  3. 模型是推理型，正文为空（内容都在 reasoning 里）")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
