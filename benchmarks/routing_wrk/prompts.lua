-- prompts.lua
-- Lua script for wrk / wrk2 to benchmark LLM routing prompts

local prompts = {}
local pending = {}
local expected_by_id = {}
local backend_counts = { coding = 0, math = 0, others = 0, unknown = 0 }
local expected_counts = { coding = 0, math = 0, others = 0, unknown = 0 }
local all_threads = {}
local route_matches = 0
local route_mismatches = 0
local responses = 0
local verify_backend_markers = os.getenv("VERIFY_BACKEND_MARKERS") ~= "0"
local script_dir = debug.getinfo(1, "S").source:sub(2):match("(.*[/\\])") or "./"
local prompts_file = script_dir .. "../dataset_prompts.jsonl"

-- Load prompts from file at startup
for line in io.lines(prompts_file) do
    if line ~= "" then
        table.insert(prompts, line)
    end
end

if #prompts == 0 then
    error("No prompts found in " .. prompts_file .. ". Run export_prompts.py first.")
end

local counter = 0

wrk.method = "POST"
wrk.headers["Content-Type"] = "application/json"
wrk.headers["Connection"] = "keep-alive"

setup = function(thread)
    if #all_threads == 0 then
        print(string.format("[Lua] Loaded %d prompts from %s", #prompts, prompts_file))
    end
    table.insert(all_threads, thread)
    thread:set("route_matches", 0)
    thread:set("route_mismatches", 0)
    thread:set("responses", 0)
    thread:set("backend_coding", 0)
    thread:set("backend_math", 0)
    thread:set("backend_others", 0)
    thread:set("backend_unknown", 0)
    thread:set("expected_coding", 0)
    thread:set("expected_math", 0)
    thread:set("expected_others", 0)
    thread:set("expected_unknown", 0)
end

local function expected_route(payload)
    return payload:match('"x_expected_route"%s*:%s*"([^"]+)"') or "unknown"
end

local function backend_marker(body)
    return body:match('"backend"%s*:%s*"([^"]+)"') or "unknown"
end

local function route_seq_marker(body)
    return body:match('"x_route_seq"%s*:%s*"([^"]+)"')
end

request = function()
    counter = counter + 1
    local payload = prompts[((counter - 1) % #prompts) + 1]
    local expected = expected_route(payload)
    local route_seq = tostring(counter)
    table.insert(pending, expected)
    expected_by_id[route_seq] = expected
    payload = payload:gsub(',"x_expected_route"%s*:%s*"[^"]+"', "")
    return wrk.format("POST", "/v1/chat/completions", { ["x-route-seq"] = route_seq }, payload)
end

response = function(status, headers, body)
    local route_seq = route_seq_marker(body or "")
    local expected = route_seq and expected_by_id[route_seq] or nil
    if expected then
        expected_by_id[route_seq] = nil
    else
        expected = table.remove(pending, 1) or "unknown"
    end
    local backend = backend_marker(body or "")

    responses = responses + 1
    if expected_counts[expected] == nil then expected = "unknown" end
    if backend_counts[backend] == nil then backend = "unknown" end

    expected_counts[expected] = expected_counts[expected] + 1
    backend_counts[backend] = backend_counts[backend] + 1

    if status >= 200 and status < 300 and expected == backend then
        route_matches = route_matches + 1
    else
        route_mismatches = route_mismatches + 1
    end

    wrk.thread:set("route_matches", route_matches)
    wrk.thread:set("route_mismatches", route_mismatches)
    wrk.thread:set("responses", responses)
    wrk.thread:set("backend_coding", backend_counts.coding)
    wrk.thread:set("backend_math", backend_counts.math)
    wrk.thread:set("backend_others", backend_counts.others)
    wrk.thread:set("backend_unknown", backend_counts.unknown)
    wrk.thread:set("expected_coding", expected_counts.coding)
    wrk.thread:set("expected_math", expected_counts.math)
    wrk.thread:set("expected_others", expected_counts.others)
    wrk.thread:set("expected_unknown", expected_counts.unknown)
end

done = function(summary, latency, requests)
    io.write(string.format(
        "[Lua] latency percentiles: p50=%.2fus p95=%.2fus p99=%.2fus\n",
        latency:percentile(50.0),
        latency:percentile(95.0),
        latency:percentile(99.0)
    ))
    
    local total_backend_counts = { coding = 0, math = 0, others = 0, unknown = 0 }
    local total_expected_counts = { coding = 0, math = 0, others = 0, unknown = 0 }
    local total_matches = 0
    local total_mismatches = 0
    local total_responses = 0

    for _, thread in ipairs(all_threads) do
        total_matches = total_matches + (thread:get("route_matches") or 0)
        total_mismatches = total_mismatches + (thread:get("route_mismatches") or 0)
        total_responses = total_responses + (thread:get("responses") or 0)
        total_backend_counts.coding = total_backend_counts.coding + (thread:get("backend_coding") or 0)
        total_backend_counts.math = total_backend_counts.math + (thread:get("backend_math") or 0)
        total_backend_counts.others = total_backend_counts.others + (thread:get("backend_others") or 0)
        total_backend_counts.unknown = total_backend_counts.unknown + (thread:get("backend_unknown") or 0)
        total_expected_counts.coding = total_expected_counts.coding + (thread:get("expected_coding") or 0)
        total_expected_counts.math = total_expected_counts.math + (thread:get("expected_math") or 0)
        total_expected_counts.others = total_expected_counts.others + (thread:get("expected_others") or 0)
        total_expected_counts.unknown = total_expected_counts.unknown + (thread:get("expected_unknown") or 0)
    end

    io.write(string.format(
        "[Lua] backend markers: coding=%d math=%d others=%d unknown=%d\n",
        total_backend_counts.coding,
        total_backend_counts.math,
        total_backend_counts.others,
        total_backend_counts.unknown
    ))
    io.write(string.format(
        "[Lua] expected routes: coding=%d math=%d others=%d unknown=%d\n",
        total_expected_counts.coding,
        total_expected_counts.math,
        total_expected_counts.others,
        total_expected_counts.unknown
    ))

    if verify_backend_markers then
        local agreement = 0
        local aggregate_matches = 0
        if total_responses > 0 then
            aggregate_matches =
                math.min(total_backend_counts.coding, total_expected_counts.coding) +
                math.min(total_backend_counts.math, total_expected_counts.math) +
                math.min(total_backend_counts.others, total_expected_counts.others)
            agreement = aggregate_matches / total_responses
        end

        io.write(string.format(
            "[Lua] aggregate route agreement: %.6f (%d/%d); fifo_matches=%d fifo_mismatches=%d\n",
            agreement,
            aggregate_matches,
            total_responses,
            total_matches,
            total_mismatches
        ))
        if total_responses > 0 and agreement < 0.90 then
            io.write("[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints\n")
        end
    else
        io.write("[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection\n")
    end
end
