#!/usr/bin/env python3
"""Split index.html <script> into multiple JS files (non-ESM, global scope)."""
import re
from pathlib import Path

web = Path(__file__).resolve().parent.parent / "src" / "bridge" / "web"
html = (web / "index.html").read_text(encoding="utf-8")

script_match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
js = script_match.group(1)

# Define function groups → target files
groups = {
    "js/i18n.js": [
        r"let lang='zh';",
        r"const i18n=\{.*?\};",
        r"const stateMap=\{.*?\};",
        r"function t\(k\)\{.*?\}",
        r"function toggleLang\(\)\{.*?\}",
    ],
    "js/utils.js": [
        r"function mapState\(s\)\{.*?\}",
        r"function ts\(s\)\{.*?\}",
        r"function badge\(s\)\{.*?\}",
        r"function esc\(s\)\{.*?\}",
        r"function fmtElapsed\(.*?\}",
    ],
    "js/api.js": [
        r"const API='/api';",
        r"async function api\(path,opts\)\{.*?\}",
    ],
}

# Simple approach: extract by function name with balanced braces
def extract_function(js, name):
    """Extract a function (or async function) by name, handling nested braces."""
    pattern = rf"(?:async )?function {re.escape(name)}\s*\("
    m = re.search(pattern, js)
    if not m:
        return None
    start = m.start()
    # Find matching closing brace
    depth = 0
    i = js.index("{", m.end())
    depth = 1
    i += 1
    while i < len(js) and depth > 0:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
        i += 1
    return js[start:i]

# Manually assign functions to files
func_map = {
    "js/i18n.js": ["t", "toggleLang"],
    "js/utils.js": ["mapState", "ts", "badge", "esc", "fmtElapsed"],
    "js/api.js": ["api"],
    "js/pages/dashboard.js": ["loadDashboard"],
    "js/pages/projects.js": ["loadProjects", "addProject"],
    "js/pages/tasks.js": ["loadTasks", "createTask", "cancelTask"],
    "js/pages/workers.js": ["loadWorkers"],
    "js/pages/review.js": ["loadReview", "reviewPass", "reviewFix", "viewOutboxFile"],
    "js/pages/thinking.js": ["loadThinking", "initThinking", "pollLogs", "loadHistory", "tickTimers", "schedulePoll", "clearThinkingLog"],
    "js/pages/metrics.js": ["loadMetrics"],
    "js/pages/settings.js": ["loadSettings"],
}

# Extract i18n data (const i18n={...} and const stateMap={...})
i18n_match = re.search(r"const i18n=\{.*?\};", js, re.DOTALL)
state_map_match = re.search(r"const stateMap=\{.*?\};", js, re.DOTALL)
lang_match = re.search(r"let lang='zh';", js)
api_const_match = re.search(r"const API='/api';", js)

# Write i18n.js
i18n_content = ""
if lang_match:
    i18n_content += lang_match.group() + "\n"
if i18n_match:
    i18n_content += i18n_match.group() + "\n"
if state_map_match:
    i18n_content += state_map_match.group() + "\n"
for func_name in func_map["js/i18n.js"]:
    func = extract_function(js, func_name)
    if func:
        i18n_content += func + "\n"
(web / "js" / "i18n.js").write_text(i18n_content, encoding="utf-8")

# Write utils.js
utils_content = ""
for func_name in func_map["js/utils.js"]:
    func = extract_function(js, func_name)
    if func:
        utils_content += func + "\n"
(web / "js" / "utils.js").write_text(utils_content, encoding="utf-8")

# Write api.js
api_content = ""
if api_const_match:
    api_content += api_const_match.group() + "\n"
for func_name in func_map["js/api.js"]:
    func = extract_function(js, func_name)
    if func:
        api_content += func + "\n"
(web / "js" / "api.js").write_text(api_content, encoding="utf-8")

# Write page files
for filepath, func_names in func_map.items():
    if not filepath.startswith("js/pages/"):
        continue
    content = ""
    for func_name in func_names:
        func = extract_function(js, func_name)
        if func:
            content += func + "\n"
    (web / filepath).write_text(content, encoding="utf-8")

# Write app.js (navigate + pages registry + event listeners)
navigate_func = extract_function(js, "navigate")
# Extract the pages const and event listeners from the end
pages_match = re.search(r"const pages=\{.*?\};", js, re.DOTALL)
event_listeners = """
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)||'dashboard'));
window.addEventListener('load',()=>navigate(location.hash.slice(1)||'dashboard'));
"""

app_content = ""
if pages_match:
    app_content += pages_match.group() + "\n"
if navigate_func:
    app_content += navigate_func + "\n"
app_content += event_listeners
(web / "js" / "app.js").write_text(app_content, encoding="utf-8")

# Report
print("JS files created:")
for f in sorted((web / "js").rglob("*.js")):
    lines = f.read_text(encoding="utf-8").count("\n") + 1
    print(f"  {f.relative_to(web)}: {lines} lines")