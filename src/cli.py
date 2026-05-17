"""Command-line entrypoint for ios-test."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
sys.path = [p for p in sys.path if p != str(SRC_DIR)]
sys.path.insert(0, str(SRC_DIR))

from agent_runner import run_agent
from codegen_detox import generate
from coverage_map import write as write_coverage
from env_loader import load_dotenv
from explorer import explore
from flow_extractor import GBrainUnavailable, extract_flows, index_source
from gbrain_source import GBrainSourceError, prepare_app_source
from idb_wrapper import IdbWrapper
from runner import replay
from trace import Trace


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="ios-test",
        description="gbrain-directed autonomous integration testing for RN iOS apps",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    explore_cmd = sub.add_parser("explore", help="extract flows, drive simulator, and record a trace")
    explore_cmd.add_argument("app_path")
    explore_cmd.add_argument("--udid", required=True)
    explore_cmd.add_argument("--bundle-id", required=True)
    explore_cmd.add_argument("--trace-dir", default="traces/latest")
    explore_cmd.add_argument("--out", default="trace.json")
    explore_cmd.add_argument(
        "--allow-local-fallback",
        action="store_true",
        help="smoke-test without gbrain; trace is marked LOCAL_FALLBACK",
    )
    _add_gbrain_source_args(explore_cmd)

    plan_cmd = sub.add_parser("gbrain-plan", help="ask gbrain for flow evidence")
    plan_cmd.add_argument("app_path")
    plan_cmd.add_argument(
        "--allow-local-fallback",
        action="store_true",
        help="show the fallback plan if gbrain is unavailable",
    )
    _add_gbrain_source_args(plan_cmd)

    index_cmd = sub.add_parser("gbrain-index", help="index app source into gbrain pages")
    index_cmd.add_argument("app_path")
    _add_gbrain_source_args(index_cmd)

    check = sub.add_parser("check-trace", help="validate and summarize a trace file")
    check.add_argument("trace")

    codegen = sub.add_parser("codegen-detox", help="emit a Detox test from a trace")
    codegen.add_argument("trace")
    codegen.add_argument("--out", default="generated.ios-test.e2e.js")

    coverage = sub.add_parser("coverage", help="emit coverage/coverage.json from a trace")
    coverage.add_argument("trace")
    coverage.add_argument("--out", default="coverage/coverage.json")

    replay_cmd = sub.add_parser("replay", help="replay a trace and print visible assertions")
    replay_cmd.add_argument("trace")
    replay_cmd.add_argument("--udid", required=True)
    replay_cmd.add_argument("--bundle-id", required=True)
    replay_cmd.add_argument("--trace-dir", default="traces/replay")

    agent_cmd = sub.add_parser(
        "agent-run",
        help="run the OpenAI + gbrain agent TUI against a simulator app",
    )
    agent_cmd.add_argument("app_path")
    agent_cmd.add_argument("--udid", required=True)
    agent_cmd.add_argument("--bundle-id", required=True)
    agent_cmd.add_argument("--trace-dir", default="traces/agent-run")
    agent_cmd.add_argument("--out", default="traces/agent-run/trace.json")
    agent_cmd.add_argument("--proxy-log", help="HAR or JSONL proxy/network event log")
    agent_cmd.add_argument(
        "--live-proxy",
        action="store_true",
        help="start mitmdump and stream network events into the TUI",
    )
    agent_cmd.add_argument("--live-proxy-port", type=int, default=9090)
    agent_cmd.add_argument(
        "--live-proxy-out",
        help="JSONL path for live proxy events; defaults to <trace-dir>/network.jsonl",
    )
    agent_cmd.add_argument("--live-proxy-binary", help="mitmdump binary override")
    agent_cmd.add_argument("--model", help="OpenAI model override")
    agent_cmd.add_argument(
        "--allow-local-fallback",
        action="store_true",
        help="allow source parsing only when gbrain is unavailable",
    )
    _add_gbrain_source_args(agent_cmd)

    args = parser.parse_args()

    if args.command == "gbrain-plan":
        if not _prepare_source(args):
            return 2
        try:
            specs = extract_flows(
                args.app_path, allow_local_fallback=args.allow_local_fallback
            )
        except GBrainUnavailable as e:
            print(str(e), file=sys.stderr)
            return 2
        for spec in specs:
            print(f"{spec.flow}:")
            print(f"  symbols: {', '.join(spec.gbrain_symbols)}")
            print(f"  hints: {', '.join(spec.hints)}")
            for hit in spec.gbrain_evidence:
                print(f"  gbrain: {hit}")
        return 0

    if args.command == "gbrain-index":
        if not _prepare_source(args, sync=False):
            return 2
        slugs = index_source(args.app_path)
        print(f"indexed {len(slugs)} source file(s)")
        for slug in slugs:
            print(slug)
        return 0

    if args.command == "explore":
        if not _prepare_source(args):
            return 2
        try:
            specs = extract_flows(
                args.app_path, allow_local_fallback=args.allow_local_fallback
            )
        except GBrainUnavailable as e:
            print(str(e), file=sys.stderr)
            return 2
        idb = IdbWrapper(args.udid, args.trace_dir, bundle_id=args.bundle_id)
        trace = explore(args.app_path, specs, idb)
        out = Path(args.out)
        out.write_text(trace.to_json(), encoding="utf-8")
        steps = sum(len(flow.steps) for flow in trace.flows)
        print(f"wrote {out} flows={len(trace.flows)} steps={steps}")
        for flow in trace.flows:
            detail = f" failure={flow.failure}" if flow.failure else ""
            print(f"{flow.name}: {flow.status} steps={len(flow.steps)}{detail}")
        return 0

    if args.command == "agent-run":
        if not _prepare_source(args):
            return 2
        return run_agent(
            app_path=args.app_path,
            udid=args.udid,
            bundle_id=args.bundle_id,
            trace_dir=args.trace_dir,
            out=args.out,
            proxy_log=args.proxy_log,
            live_proxy=args.live_proxy,
            live_proxy_port=args.live_proxy_port,
            live_proxy_out=args.live_proxy_out,
            live_proxy_binary=args.live_proxy_binary,
            allow_local_fallback=args.allow_local_fallback,
            model=args.model,
        )

    trace = Trace.load(args.trace)
    if args.command == "check-trace":
        steps = sum(len(flow.steps) for flow in trace.flows)
        print(
            f"trace schema={trace.schema_version} flows={len(trace.flows)} "
            f"steps={steps} app={trace.app_path}"
        )
        return 0

    if args.command == "codegen-detox":
        out = Path(args.out)
        out.write_text(generate(trace), encoding="utf-8")
        print(f"wrote {out}")
        return 0

    if args.command == "coverage":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_coverage(trace, out)
        print(f"wrote {out}")
        return 0

    if args.command == "replay":
        idb = IdbWrapper(args.udid, args.trace_dir, bundle_id=args.bundle_id)
        results = replay(trace, idb)
        failed = 0
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            if not result.passed:
                failed += 1
            print(
                f"{status} {result.kind} selector={result.selector!r} "
                f"expected={result.expected!r} actual={result.actual!r}"
            )
        print(f"assertions={len(results)} failed={failed}")
        return 1 if failed else 0

    parser.error(f"unknown command {args.command}")
    return 2


def _add_gbrain_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--gbrain-source",
        help="gbrain source id for this app; defaults to a stable id derived from app_path",
    )
    parser.add_argument(
        "--fresh-gbrain",
        action="store_true",
        help="remove and re-sync this app's gbrain source before planning",
    )
    parser.add_argument(
        "--skip-gbrain-sync",
        action="store_true",
        help="reuse the current app source without running gbrain sync",
    )


def _prepare_source(args: argparse.Namespace, sync: bool = True) -> bool:
    try:
        source = prepare_app_source(
            args.app_path,
            source_id=args.gbrain_source,
            fresh=args.fresh_gbrain,
            sync=sync and not args.skip_gbrain_sync,
        )
    except (GBrainSourceError, TimeoutError) as e:
        print(f"gbrain source setup failed: {e}", file=sys.stderr)
        return False
    print(f"gbrain source: {source}", file=sys.stderr)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
