#!/usr/bin/env python3
"""架构师巡检工具 — 按 5/3/3/2/2/1 递减阈值巡检 Worker，走完即硬超时。

用法:
    python3 tools/architect_inspect.py [bridge_root]

输出:
    - 每个 RUNNING 任务的累计时长、巡检次数、距下次巡检时间
    - need_inspect=YES 的任务需要架构师立即查看
    - HARD_TIMEOUT 的任务应 cancel + 架构师介入
    - 无产出的任务：架构师继续规划/干活，不傻等
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

THRESHOLDS = [5, 3, 3, 2, 2, 1]  # 分钟，递减，走完=硬超时


def parse_iso(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def inspect(bridge_root: str = ".") -> list[dict]:
    root = Path(bridge_root)
    tasks_dir = root / "tasks"
    if not tasks_dir.exists():
        return []
    now = time.time()
    results = []

    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        state_file = task_dir / "state.json"
        if not state_file.exists():
            continue
        state = json.loads(state_file.read_text())
        if state.get("status") != "RUNNING":
            continue

        task_id = task_dir.name
        started = parse_iso(state.get("startedAt") or state.get("runningAt"))
        if not started:
            continue

        hist_file = task_dir / "inspect_history.json"
        history = json.loads(hist_file.read_text()) if hist_file.exists() else {"inspections": []}
        inspect_count = len(history["inspections"])

        elapsed_min = (now - started) / 60

        if inspect_count < len(THRESHOLDS):
            cumulative_threshold = sum(THRESHOLDS[: inspect_count + 1])
            next_inspect_at = started + cumulative_threshold * 60
            time_to_next = (next_inspect_at - now) / 60
            need_inspect = now >= next_inspect_at
            is_hard_timeout = need_inspect and inspect_count == len(THRESHOLDS) - 1
            next_threshold = THRESHOLDS[inspect_count]
        else:
            need_inspect = False
            is_hard_timeout = True
            time_to_next = 0
            next_threshold = 0

        outbox = task_dir / "outbox"
        outbox_files = sorted([f.name for f in outbox.glob("*") if f.is_file()]) if outbox.exists() else []
        has_output = len(outbox_files) > 0

        results.append(
            {
                "task_id": task_id,
                "worker": state.get("assignedWorkerId", "-"),
                "elapsed_min": round(elapsed_min, 1),
                "inspect_count": inspect_count,
                "next_threshold_min": next_threshold,
                "time_to_next_min": round(time_to_next, 1),
                "need_inspect": need_inspect,
                "is_hard_timeout": is_hard_timeout,
                "has_output": has_output,
                "outbox_files": outbox_files,
            }
        )

        if need_inspect and not is_hard_timeout:
            history["inspections"].append(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "elapsed_min": round(elapsed_min, 1),
                    "had_output": has_output,
                    "outbox_files": outbox_files,
                }
            )
            hist_file.write_text(json.dumps(history, indent=2))

    return results


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    results = inspect(root)
    if not results:
        print("No RUNNING tasks.")
        return

    print(f"{'TaskID':<45} {'Worker':<12} {'Elapsed':>7} {'Chk':>3} {'Next':>5} {'In':>6} {'Inspect':>8} {'Output':>7}")
    print("-" * 100)
    for r in results:
        flag = "HARD" if r["is_hard_timeout"] else ("YES" if r["need_inspect"] else "no")
        print(
            f"{r['task_id']:<45} {r['worker']:<12} "
            f"{r['elapsed_min']:>6.1f}m {r['inspect_count']:>3} "
            f"{r['next_threshold_min']:>4}m {r['time_to_next_min']:>5.1f}m "
            f"{flag:>8} {'YES' if r['has_output'] else 'no':>7}"
        )
    print()
    need = [r for r in results if r["need_inspect"] or r["is_hard_timeout"]]
    if need:
        print(f"*** {len(need)} task(s) need inspection now ***")
        for r in need:
            if r["is_hard_timeout"]:
                print(f"  HARD TIMEOUT: {r['task_id']} — cancel + architect intervene")
            elif not r["has_output"]:
                print(f"  NO OUTPUT: {r['task_id']} — architect plan/work, don't wait")
            else:
                print(f"  HAS OUTPUT: {r['task_id']} — review outbox: {r['outbox_files']}")
    else:
        next_task = min(results, key=lambda r: r["time_to_next_min"])
        print(f"Next inspection in {next_task['time_to_next_min']:.1f}m ({next_task['task_id']})")


if __name__ == "__main__":
    main()