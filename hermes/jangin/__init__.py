"""jangin 플러그인 — Hermes 를 1인 사업 비서로 쓰는 배포판의 "사람의 손".

등록하는 것:
  - 슬래시 명령 /idea /project /stage /advance /back /inbox /ok /reject /setup, 그리고 /jangin <하위 명령>
  - pre_tool_call 훅: 에이전트의 도구 호출을 op 의 가드 규칙으로 막는다 (세션 폴더를 아는 경로)
  - jangin 스킬 (plugin:jangin) 과 짧은 시스템 프롬프트 안내
명령 본체는 commands.py 에 있다. 이 파일은 Hermes 와의 연결만 한다.
"""
import logging
import os

from . import commands

log = logging.getLogger(__name__)

PROMPT = (
    "jangin 플러그인이 켜져 있다. 사업 아이디어, 단계, 승인 대기, 발송·배포 이야기는 jangin 스킬을 따른다. "
    "승인·거절·단계 이동은 사용자만 슬래시 명령으로 한다: 승인 대기 /inbox, 승인 /ok <번호>, 거절 /reject <번호> <이유>, "
    "단계 /stage, 다음 단계 /advance, 되돌리기 /back <단계> <이유>. 너는 이 명령을 대신 입력하거나 흉내 내지 않는다. "
    "Hermes 내장 /approve 는 위험 명령 허락용이고 jangin 승인 대기와 다르다. 사용자에게는 항상 한국어로 답한다."
)


def _data_dir(ctx):
    """<HERMES_HOME>/plugin-data/jangin — `jangin setup` 마법사와 같은 위치.
    Hermes 가 주는 플러그인 폴더(plugin-data/agent-plugin-operator-<해시>)의 형제 폴더를 쓰고,
    예전에 그 해시 폴더에 둔 settings.json 이 있으면 한 번 옮긴다."""
    state = getattr(ctx, "state", None)
    given = getattr(state, "data_dir", None)
    if given:
        stable = os.path.join(os.path.dirname(str(given)), "jangin")
        new = os.path.join(stable, "settings.json")
        # 예전 위치: Hermes 해시 폴더, 예전 이름(operator) 폴더
        for old in (os.path.join(str(given), "settings.json"),
                    os.path.join(os.path.dirname(str(given)), "operator", "settings.json")):
            if os.path.isfile(old) and not os.path.exists(new):
                os.makedirs(stable, exist_ok=True)
                os.replace(old, new)
        return stable
    home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
    return os.path.join(home, "plugin-data", "jangin")


def _allowed_users():
    """게이트웨이 프로세스의 환경 변수에서만 읽는다 (에이전트가 바꿀 수 있는 파일에 두지 않는다)."""
    raw = os.environ.get("OPERATOR_ALLOWED_USERS", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


def register(ctx):
    plugin = commands.Plugin(_data_dir(ctx), allowed_users=_allowed_users())

    def make(name):
        def handler(raw_args="", source=None, platform="", **_):
            user = getattr(source, "user_id", "") or ""
            return plugin.run(name, raw_args, platform=str(platform or ""), user_id=str(user),
                              from_messenger=source is not None)
        handler.__name__ = f"operator_{name}"
        return handler

    for name in commands.NAMES + ("jangin",):
        desc = commands.HELP.get(name, "jangin 명령 (/jangin help)")
        try:
            ctx.register_command(name, make(name), description=desc.split(" — ", 1)[-1])
        except Exception as e:   # 다른 플러그인과 이름이 겹치면 /jangin <하위 명령> 으로 쓴다
            log.warning("jangin: /%s 등록 실패: %s", name, e)

    def pre_tool_call(tool_name="", args=None, **_):
        try:
            cwd = ctx.session_cwd() if hasattr(ctx, "session_cwd") else ""
            reason = plugin.guard(tool_name, args, cwd)
        except Exception as e:   # 가드가 깨지면 막는 쪽으로
            log.exception("jangin guard error")
            return {"action": "block", "message": f"[jangin 승인 게이트] 가드 오류로 막았다: {e.__class__.__name__}"}
        return {"action": "block", "message": reason} if reason else None

    ctx.register_hook("pre_tool_call", pre_tool_call)

    skill = os.path.join(commands.HERE, "skill", "SKILL.md")
    if not os.path.isfile(skill):
        skill = os.path.join(commands.HERE, "..", "..", "skills", "jangin", "SKILL.md")
    if os.path.isfile(skill) and hasattr(ctx, "register_skill"):
        try:
            ctx.register_skill("jangin", os.path.abspath(skill), description="1인 사업 운영 루프: 단계, 승인 대기, 사람만 하는 발송")
        except Exception as e:
            log.warning("jangin: 스킬 등록 실패: %s", e)
    if hasattr(ctx, "register_system_prompt_section"):
        try:
            ctx.register_system_prompt_section("jangin", PROMPT)
        except Exception as e:
            log.warning("jangin: 시스템 프롬프트 등록 실패: %s", e)
