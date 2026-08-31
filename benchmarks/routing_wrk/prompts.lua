-- Lua script for wrk / wrk2 routing throughput benchmarks.

local prompts = {}
local counter = 0
local announced = false
local script_dir = debug.getinfo(1, "S").source:sub(2):match("(.*[/\\])") or "./"
local prompts_file = os.getenv("PROMPTS_FILE") or (script_dir .. "../dataset_prompts.jsonl")

for line in io.lines(prompts_file) do
    if line ~= "" then
        -- The correctness annotation is invariant per corpus row. Strip it
        -- once during script initialization so request() does no JSON work.
        local payload = line:gsub(',"x_expected_route"%s*:%s*"[^"]+"', "")
        table.insert(prompts, payload)
    end
end

if #prompts == 0 then
    error("No prompts found in " .. prompts_file .. ". Run export_prompts.py first.")
end

wrk.method = "POST"
wrk.headers["Content-Type"] = "application/json"
wrk.headers["Connection"] = "keep-alive"

setup = function(thread)
    if not announced then
        print(string.format("[Lua] Loaded %d prompts from %s", #prompts, prompts_file))
        announced = true
    end
end

request = function()
    counter = counter + 1
    local payload = prompts[((counter - 1) % #prompts) + 1]
    return wrk.format("POST", "/v1/chat/completions", nil, payload)
end

done = function(summary, latency, requests)
    io.write(string.format(
        "[Lua] latency percentiles: p50=%.2fus p95=%.2fus p99=%.2fus\n",
        latency:percentile(50.0),
        latency:percentile(95.0),
        latency:percentile(99.0)
    ))
end
