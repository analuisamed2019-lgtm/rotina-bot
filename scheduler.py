import logging
from datetime import datetime

import pytz

from calendar_client import format_events_for_prompt, get_events
from claude_client import get_response
from config import TELEGRAM_CHAT_ID, TIMEZONE
from state import format_state_for_prompt, load_state

logger = logging.getLogger(__name__)


async def send_morning_briefing(context):
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    state = load_state()
    events = get_events(days=2)
    state_str = format_state_for_prompt(state)
    cal_str = format_events_for_prompt(events)
    dt_str = now.strftime("%A, %d/%m/%Y %H:%M (Brasília)")

    response, _ = get_response(
        user_message=(
            "Gere o planejamento do dia de hoje. "
            "Inclua: hora de acordar, todos os compromissos do calendário com horários, "
            "blocos de estudo previstos com os temas, atividades físicas e yoga se houver. "
            "Seja direta e use horários específicos. Formato conciso."
        ),
        conversation_history=[],
        state_str=state_str,
        calendar_events=cal_str,
        current_datetime=dt_str,
    )

    header = f"Bom dia! Planejamento de {now.strftime('%d/%m/%Y')}\n\n"
    full_message = header + response

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=full_message,
            parse_mode="Markdown",
        )
    except Exception:
        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=full_message)
