import subprocess, json, os, glob

# 1. Kill local SSH processes
subprocess.run(["pwsh", "-NoProfile", "-Command",
    "Get-Process -Name ssh -ErrorAction SilentlyContinue | Stop-Process -Force"],
    capture_output=True, text=True, timeout=10)

# 2. Kill remote codearts
hosts = [
    ("nathan@192.168.178.50", "bridge-p5"),
    ("root@192.168.5.15", "bridge-p6"),
    ("nathan@192.168.178.52", "bridge-p4"),
    ("nathan@192.168.178.51", "bridge-p7"),
]
for host, pattern in hosts:
    cmd = f"ps -eo pid,cmd | grep 'codearts run.*{pattern}' | grep -v grep | awk '{{print $1}}'"
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", host, cmd], capture_output=True, text=True, timeout=15)
    pids = [p.strip() for p in r.stdout.strip().split("\n") if p.strip()]
    if pids:
        subprocess.run(["ssh", "-o", "BatchMode=yes", host, "kill " + " ".join(pids) + " 2>/dev/null"], capture_output=True, timeout=10)
        print(f"{host}: killed {pids}")

# 3. Reset state and clean leases/locks
base = r"E:\Obsidian\codex-glm\tasks"
leases = r"E:\Obsidian\codex-glm\runtime\leases"
dirs = [
    "bridge-p4-commit-capture-w01-20260909",
    "bridge-p5-bundle-digest-w02-20260909",
    "bridge-p6-finalizer-w03-20260909",
    "bridge-p7-cloudsite-profile-w04-20260909",
]
for d in dirs:
    sp = os.path.join(base, d, "state.json")
    j = json.load(open(sp))
    j["status"] = "READY"
    j["attempt"] = 0
    j["updatedAt"] = ""
    j["message"] = "Reset - architect reviewing project state"
    j["processId"] = None
    j["exitCode"] = None
    j["processStartTime"] = None
    j["lastHeartbeat"] = None
    json.dump(j, open(sp, "w"), indent=2)
    lp = os.path.join(leases, d + ".json")
    if os.path.exists(lp): os.remove(lp)

for f in glob.glob(os.path.join(r"E:\Obsidian\codex-glm\runtime\locks", "workdir-*.lock")):
    try: os.remove(f)
    except: pass

print("All workers stopped, state reset")