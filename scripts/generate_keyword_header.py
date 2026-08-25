#!/usr/bin/env python3
"""Generate verifier-friendly XDP keyword policy C from a small YAML file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROUTES = {
    "coding": "XDP_KEYWORD_ROUTE_CODING",
    "math": "XDP_KEYWORD_ROUTE_MATH",
    "qa": "XDP_KEYWORD_ROUTE_QA",
    "writing": "XDP_KEYWORD_ROUTE_WRITING",
    "others": "XDP_KEYWORD_ROUTE_GENERAL",
}

LIST_KEYS = {
    "backend_refs",
    "conditions",
    "decisions",
    "keywords",
    "listeners",
    "modelCards",
    "models",
    "modelRefs",
    "routes",
}


def parse_scalar(value: str) -> object:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        body = value[1:-1].strip()
        if not body:
            return []
        return [
            parse_scalar(item)
            for item in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", body)
            if item.strip()
        ]
    if value in {"true", "false"}:
        return value == "true"
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value.strip('"\'')


def load_policy(path: Path) -> dict[str, object]:
    if path.suffix == ".json":
        with path.open() as file:
            return json.load(file)

    root: dict[str, object] = {}
    stack: list[tuple[int, object]] = [(-1, root)]

    with path.open() as file:
        for raw_line in file:
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue

            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" "))

            while stack and indent <= stack[-1][0]:
                stack.pop()

            parent = stack[-1][1]

            if stripped.startswith("- "):
                if not isinstance(parent, list):
                    raise ValueError(f"list item without list parent: {path}:{raw_line!r}")
                item_text = stripped[2:]
                if ":" not in item_text:
                    parent.append(parse_scalar(item_text))
                    continue
                key, value = item_text.split(":", 1)
                item = {key: parse_scalar(value)}
                parent.append(item)
                stack.append((indent, item))
                continue

            if ":" in stripped:
                key, value = stripped.split(":", 1)
                if not isinstance(parent, dict):
                    raise ValueError(f"mapping value without mapping parent: {path}:{raw_line!r}")
                value = value.strip()
                if value:
                    parent[key] = parse_scalar(value)
                elif key in LIST_KEYS:
                    parent[key] = []
                    stack.append((indent, parent[key]))
                else:
                    parent[key] = {}
                    stack.append((indent, parent[key]))
                continue

            raise ValueError(f"cannot parse {path}:{raw_line!r}")

    return root


def keyword_signals(policy: dict[str, object]) -> list[dict[str, object]]:
    routing = policy.get("routing")
    if isinstance(routing, dict):
        signals = routing.get("signals")
        if isinstance(signals, dict):
            keywords = signals.get("keywords")
            if isinstance(keywords, list):
                return keywords  # type: ignore[return-value]

    routes = policy.get("routes")
    if isinstance(routes, list):
        return routes  # type: ignore[return-value]

    raise ValueError("policy must define routing.signals.keywords")


def decision_keyword_routes(policy: dict[str, object]) -> tuple[dict[str, str], dict[str, int]]:
    routing = policy.get("routing")
    if not isinstance(routing, dict):
        return {}, {}
    decisions = routing.get("decisions")
    if not isinstance(decisions, list):
        return {}, {}

    routes: dict[str, str] = {}
    priorities: dict[str, int] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        decision_name = str(decision.get("name", ""))
        if decision_name not in {"coding", "math", "qa", "writing"}:
            continue
        priority = int(decision.get("priority", 0))
        rules = decision.get("rules")
        if not isinstance(rules, dict):
            continue
        conditions = rules.get("conditions")
        if not isinstance(conditions, list):
            continue
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            if str(condition.get("type", "")) != "keyword":
                continue
            signal_name = str(condition.get("name", ""))
            if signal_name:
                routes[signal_name] = decision_name
                priorities[signal_name] = priority
    return routes, priorities


def signal_route_name(signal: dict[str, object], decision_routes: dict[str, str]) -> str:
    route = signal.get("route")
    if route:
        return str(route)

    name = str(signal.get("name", ""))
    if name in decision_routes:
        return decision_routes[name]
    if name.startswith("code_") or name.startswith("coding_"):
        return "coding"
    if name.startswith("math_"):
        return "math"
    if name.startswith("qa_"):
        return "qa"
    if name.startswith("writing_"):
        return "writing"
    raise ValueError(f"keyword signal {name!r} must define route: coding|math|qa|writing")


def validate_policy(policy: dict[str, object]) -> tuple[bool, list[dict[str, object]]]:
    raw_routes = keyword_signals(policy)
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("policy must define keyword signals")

    routes = []
    seen_keywords: set[str] = set()
    global_case_sensitive: bool | None = None
    decision_routes, decision_priorities = decision_keyword_routes(policy)
    for route in raw_routes:
        if not isinstance(route, dict):
            raise ValueError("each keyword signal must be an object")
        name = signal_route_name(route, decision_routes)
        if name not in {"coding", "math", "qa", "writing"}:
            raise ValueError(f"unsupported route {name!r}; use coding, math, qa, or writing")
        signal_name = str(route.get("name", name))
        operator = str(route.get("operator", "OR")).upper()
        if operator not in {"OR", "AND", "NOR"}:
            raise ValueError(f"{signal_name}: operator must be OR, AND, or NOR")
        method = str(route.get("method", "regex")).lower()
        if method not in {"literal", "exact", "regex", "bm25", "ngram"}:
            raise ValueError(
                f"{signal_name}: unsupported method {method!r}"
            )
        case_sensitive = bool(route.get("case_sensitive", False))
        if global_case_sensitive is None:
            global_case_sensitive = case_sensitive
        elif global_case_sensitive != case_sensitive:
            raise ValueError("XDP requires the same case_sensitive value for every keyword signal")
        keywords = route.get("keywords")
        if not isinstance(keywords, list) or not keywords:
            raise ValueError(f"{signal_name}: must define keywords")

        clean_keywords = []
        for keyword in keywords:
            value = str(keyword)
            if not value:
                raise ValueError(f"{signal_name}: has an empty keyword")
            try:
                encoded = value.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError(f"{signal_name}: keyword {value!r} must be ASCII") from exc
            if any(byte < 32 or byte > 126 for byte in encoded):
                raise ValueError(f"{signal_name}: keyword {value!r} must be printable ASCII")
            if method == "regex" and re.search(r"[.^$*+?{}\\[\\]\\\\|()]", value):
                raise ValueError(
                    f"{signal_name}: regex keyword {value!r} uses regex syntax "
                    "that XDP does not reproduce; use literal-safe patterns"
                )
            normalized = value if case_sensitive else value.lower()
            if normalized in seen_keywords:
                raise ValueError(f"duplicate keyword {value!r}")
            seen_keywords.add(normalized)
            clean_keywords.append(normalized)

        routes.append(
            {
                "name": name,
                "priority": decision_priorities.get(signal_name, int(route.get("priority", 0))),
                "keywords": clean_keywords,
                "operator": operator,
                "method": method,
                "ngram_arity": int(route.get("ngram_arity", 3)),
                "ngram_threshold": route.get("ngram_threshold", 0.4),
            }
        )

    routes.sort(key=lambda item: int(item["priority"]), reverse=True)
    return bool(global_case_sensitive), routes


def macro_name(keyword: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", keyword).strip("_").upper()
    if not name or name[0].isdigit():
        name = f"KEYWORD_{name}"
    return f"XDP_KEYWORD_{name}"


def c_char(char: str) -> str:
    if char == "'":
        return "'\\''"
    if char == "\\":
        return "'\\\\'"
    return f"'{char}'"


def emit_header(policy_path: Path, case_sensitive: bool, routes: list[dict[str, object]]) -> str:
    keywords: list[tuple[str, str, str]] = []
    for route in routes:
        route_name = str(route["name"])
        for keyword in route["keywords"]:  # type: ignore[union-attr]
            keywords.append((macro_name(str(keyword)), str(keyword), route_name))

    offsets: list[int] = []
    chars = bytearray()
    for _, keyword, _ in keywords:
        offsets.append(len(chars))
        chars.extend(keyword.encode("ascii"))

    lines = [
        "/* Generated by scripts/generate_keyword_header.py. Do not edit by hand. */",
        f"/* Source: {policy_path.as_posix()} */",
        "#ifndef XDP_KEYWORD_POLICY_GENERATED_H",
        "#define XDP_KEYWORD_POLICY_GENERATED_H",
        "",
        f"#define XDP_KEYWORD_POLICY_CASE_SENSITIVE {1 if case_sensitive else 0}",
        f"#define XDP_KEYWORD_COUNT {len(keywords)}",
        f"#define XDP_KEYWORD_MAX_LEN {max(len(keyword) for _, keyword, _ in keywords)}",
        f"#define XDP_KEYWORD_CHARS_LEN {len(chars)}",
        "",
        "enum xdp_keyword_id {",
    ]

    for index, (name, _, _) in enumerate(keywords):
        lines.append(f"  {name} = {index},")
    lines.extend(["};", ""])

    def c_array(values: list[int], ctype: str) -> str:
        return f"static const {ctype}[] = {{" + ", ".join(str(value) for value in values) + "};"

    padded_offsets = offsets + [0] * (32 - len(offsets))
    padded_lens = [len(keyword) for _, keyword, _ in keywords] + [0] * (32 - len(keywords))
    padded_is_math = [0 if route_name == "coding" else 1 for _, _, route_name in keywords] + [0] * (32 - len(keywords))

    lines.extend(
        [
            c_array(padded_offsets, "__u16 xdp_keyword_offsets"),
            c_array(padded_lens, "__u8 xdp_keyword_lens"),
            c_array(padded_is_math, "__u8 xdp_keyword_is_math"),
            c_array(list(chars), "unsigned char xdp_keyword_chars"),
            f"static volatile const __u32 xdp_keyword_runtime_count = {len(keywords)};",
            "",
            "static __always_inline __u8 xdp_keyword_len(__u32 id) {",
            "  if (id >= MAX_KEYWORDS)",
            "    return 0;",
            "  return xdp_keyword_lens[id];",
            "}",
            "",
            "static __always_inline __u8 xdp_keyword_route_for_id(__u32 id) {",
            "  if (id >= MAX_KEYWORDS || id >= XDP_KEYWORD_COUNT)",
            "    return XDP_KEYWORD_ROUTE_GENERAL;",
            "  return xdp_keyword_is_math[id] ? XDP_KEYWORD_ROUTE_MATH : XDP_KEYWORD_ROUTE_CODING;",
            "}",
            "",
            "static __always_inline unsigned char xdp_keyword_char(__u32 id, __u8 pos) {",
            "  if (id >= MAX_KEYWORDS || pos >= xdp_keyword_lens[id])",
            "    return 0;",
            "  if (pos >= XDP_KEYWORD_MAX_LEN)",
            "    return 0;",
            "  __u16 offset = xdp_keyword_offsets[id];",
            "  if (offset >= XDP_KEYWORD_CHARS_LEN || offset + pos >= XDP_KEYWORD_CHARS_LEN)",
            "    return 0;",
            "  return xdp_keyword_chars[offset + pos];",
            "}",
            "",
            "struct xdp_keyword_score_ctx {",
            "  struct xdp_keyword_state *state;",
            "  unsigned char c;",
            "  __u32 count;",
            "};",
            "",
            "static long xdp_keyword_score_callback(__u32 id, void *data) {",
            "  struct xdp_keyword_score_ctx *ctx = data;",
            "  struct xdp_keyword_state *state = ctx->state;",
            "  unsigned char c = ctx->c;",
            "  __u32 idx = id & (MAX_KEYWORDS - 1);",
            "",
            "  if (idx >= ctx->count)",
            "    return 1;",
            "",
            "  __u8 len = xdp_keyword_lens[idx];",
            "  if (len == 0 || len > XDP_KEYWORD_MAX_LEN)",
            "    return 0;",
            "  __u8 pos = state->pos[idx];",
            "",
            "  if (pos < len && c == xdp_keyword_char(idx, pos)) {",
            "    pos++;",
            "    if (pos == len) {",
            "      if (xdp_keyword_is_math[idx])",
            "        state->matched_math = 1;",
            "      else",
            "        state->matched_coding = 1;",
            "      pos = 0;",
            "    }",
            "  } else {",
            "    pos = (c == xdp_keyword_char(idx, 0)) ? 1 : 0;",
            "  }",
            "",
            "  state->pos[idx] = pos;",
            "  return 0;",
            "}",
            "",
            "static __always_inline void xdp_keyword_score_generated(struct xdp_keyword_state *state, unsigned char c) {",
            "  __u32 count = xdp_keyword_runtime_count;",
            "  if (count > XDP_KEYWORD_COUNT)",
            "    count = XDP_KEYWORD_COUNT;",
            "  struct xdp_keyword_score_ctx ctx = {",
            "    .state = state,",
            "    .c = c,",
            "    .count = count,",
            "  };",
            "  bpf_loop(MAX_KEYWORDS, xdp_keyword_score_callback, &ctx, 0);",
            "}",
            "",
        ]
    )

    lines.extend(["#define XDP_KEYWORD_CLEAR_ALL(state) \\", "  do { \\"])
    for index in range(len(keywords)):
        lines.append(f"    (state)->pos[{index}] = 0; \\")
    lines.extend(["  } while (0)", ""])

    lines.extend(["#define XDP_KEYWORD_SCORE_ALL(state, c) \\", "  do { \\"])
    lines.append("    xdp_keyword_score_generated((state), (c)); \\")
    lines.extend(["  } while (0)", ""])

    lines.extend(["#define XDP_KEYWORD_ROUTE_FOR_MATCHES(state) \\"])
    seen_routes: set[str] = set()
    for route in routes:
        route_name = str(route["name"])
        if route_name in seen_routes:
            continue
        seen_routes.add(route_name)
        field = f"matched_{route_name}"
        lines.append(
            f"  if ((state)->{field}) \\"
        )
        lines.append(f"    return {ROUTES[route_name]}; \\")
    lines.append("  return XDP_KEYWORD_ROUTE_GENERAL")
    lines.extend(["", "#endif", ""])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    policy = load_policy(args.policy)
    case_sensitive, routes = validate_policy(policy)
    output = emit_header(args.policy, case_sensitive, routes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
