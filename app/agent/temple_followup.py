"""Interpret otherwise-unresolved follow-ups without selecting or inventing places."""
import json

from app.gateway import llm_gateway
from app.prompts import load_prompt
from app.agent.harness.leak import register_system_prompt
from app.tools.prompt_data import data_block

SYSTEM = load_prompt('temple.followup', 'v1')
register_system_prompt('temple.followup', SYSTEM)


def interpret_followup(message: str, recent_turns: list[dict]) -> dict | None:
    if not llm_gateway.has_llm():
        return None
    material = {'recent_requests': [str(t.get('user') or '')[:300] for t in recent_turns[-3:]],
                'current_request': message[:800]}
    try:
        result = llm_gateway.chat_json(
            SYSTEM, data_block('request', json.dumps(material, ensure_ascii=False)),
            fallback={}, task='chat', timeout=4, max_tokens=80,
        )
    except Exception:
        return None
    if type(result.get('related')) is not bool or type(result.get('unrestricted')) is not bool:
        return None
    return {'related': result['related'], 'unrestricted': result['unrestricted']}
