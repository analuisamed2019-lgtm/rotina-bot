import anthropic

from config import ANTHROPIC_API_KEY
from prompts import SYSTEM_PROMPT

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MAX_HISTORY = 20


def get_response(
    user_message: str,
    conversation_history: list,
    state_str: str,
    calendar_events: str,
    current_datetime: str,
) -> tuple[str, list]:
    system = SYSTEM_PROMPT.format(
        state=state_str,
        calendar_events=calendar_events,
        current_datetime=current_datetime,
    )

    history = conversation_history[-MAX_HISTORY:].copy()
    history.append({"role": "user", "content": user_message})

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system,
        messages=history,
    )

    assistant_text = response.content[0].text
    history.append({"role": "assistant", "content": assistant_text})

    return assistant_text, history
