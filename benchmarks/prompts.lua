-- prompts.lua
-- Lua script for wrk / wrk2 to benchmark LLM routing prompts

local prompts = {}
local script_dir = debug.getinfo(1, "S").source:sub(2):match("(.*[/\\])") or "./"
local prompts_file = script_dir .. "dataset_prompts.jsonl"

-- Load prompts from file at startup
for line in io.lines(prompts_file) do
    if line ~= "" then
        table.insert(prompts, line)
    end
end

if #prompts == 0 then
    error("No prompts found in " .. prompts_file .. ". Run export_dataset_prompts.py first.")
end

print(string.format("[Lua] Loaded %d prompts from %s", #prompts, prompts_file))

local counter = 0

wrk.method = "POST"
wrk.headers["Content-Type"] = "application/json"
wrk.headers["Connection"] = "keep-alive"

request = function()
    counter = counter + 1
    local payload = prompts[(counter % #prompts) + 1]
    return wrk.format("POST", "/v1/chat/completions", nil, payload)
end
