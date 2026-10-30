"""실제 Hermes 로 플러그인을 확인한다 (수동). Hermes 코드와 사용자의 ~/.hermes 는 건드리지 않는다.

  H=$(mktemp -d)/hermes-home; mkdir -p "$H"
  sh hermes/operator/install.sh --home "$H"            # 시험용 HERMES_HOME 에 설치 + plugins enable
  HERMES_HOME="$H" hermes plugins doctor operator      # 로더·매니페스트·등록 검사
  PY=$(ls -d "$H"/installs/*/environments/*/venv/bin/python3 | head -1)   # 그 HERMES_HOME 의 Hermes 파이썬
  mkdir -p /tmp/op-projects /tmp/op-home
  HERMES_AGENT_DIR=~/.hermes/hermes-agent HOME=/tmp/op-home HERMES_HOME="$H" "$PY" hermes/check_live.py /tmp/op-projects discover.md

discover.md 는 네 섹션(문제, 고객, 제안, 성공 지표)을 채운 발견 문서. Hermes 의 플러그인 로더, 명령 디스패치
(invoke_plugin_command), pre_tool_call 훅 경로를 그대로 쓴다. 대화(모델)와 메신저 게이트웨이는 돌리지 않는다.
"""
import json, os, subprocess, sys, types
sys.path.insert(0, os.environ["HERMES_AGENT_DIR"])   # 예: ~/.hermes/hermes-agent (HOME 을 바꿔 돌리므로 절대 경로로)
from hermes_cli import plugins
from hermes_cli.plugin_command_dispatch import invoke_plugin_command

cmds = plugins.get_plugin_commands()
mine = sorted(k for k, v in cmds.items() if v.get("plugin") == "operator")
print("registered:", mine)
missing = {"idea", "project", "stage", "advance", "back", "inbox", "ok", "reject", "setup", "operator"} - set(mine)
print("missing:", sorted(missing))

def call(name, arg, source=None, platform="desktop"):
    h = plugins.get_plugin_command_handler(name)
    out = invoke_plugin_command(h, arg, source=source, session_id="s1", session_key="k1", platform=platform)
    print(f"--- /{name} {arg} [{platform}]\n{out}")
    return out

call("setup", "folder " + sys.argv[1])
call("idea", "동네 빵집 예약 페이지")
proj = os.path.join(sys.argv[1], os.listdir(sys.argv[1])[0])
open(os.path.join(proj, ".operator/stages/discover.md"), "w").write(open(sys.argv[2]).read())
call("stage", "")
call("advance", "")
print("history by:", json.load(open(os.path.join(proj, ".operator/stage.json")))["history"][-1]["by"])
op_py = os.path.join(os.environ["HERMES_HOME"], "plugins/operator/skill/scripts/op.py")
open(os.path.join(proj, "r.md"), "w").write("---\ntype: research\n---\n" + "조사 내용 " * 50 + "\nhttps://a.example https://b.example https://c.example\n")
print(subprocess.run([sys.executable, "-I", op_py, "pending", "add", "r.md"], cwd=proj, capture_output=True, text=True).stdout.strip().splitlines()[-1])
call("inbox", "")
src = types.SimpleNamespace(user_id="42", chat_id="42", platform=types.SimpleNamespace(value="telegram"))
call("ok", "0001", source=src, platform="telegram")
t = [f for f in os.listdir(os.path.join(proj, ".operator/approved"))][0]
print("decided_by:", [l for l in open(os.path.join(proj, ".operator/approved", t)) if l.startswith("decided_by")])
# terminal route is closed for this project
r = subprocess.run(["script", "-q", "/dev/null", sys.executable, "-I", op_py, "stage", "set", "operate"], cwd=proj, capture_output=True, text=True)
print("forged-tty stage set exit:", r.returncode, (r.stdout + r.stderr).strip()[-160:])
# plugin hook
d = plugins._get_pre_tool_call_directive_details("terminal", {"command": "wrangler deploy", "workdir": proj})
print("hook terminal deploy:", d.action, (d.message or "")[:80])
d = plugins._get_pre_tool_call_directive_details("terminal", {"command": "npm run build", "workdir": proj})
print("hook terminal build:", d.action)
d = plugins._get_pre_tool_call_directive_details("write_file", {"path": os.path.join(proj, ".operator/stage.json"), "content": "{}"})
print("hook write stage.json:", d.action)
