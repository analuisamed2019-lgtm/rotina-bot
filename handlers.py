import logging
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from calendar_client import format_events_for_prompt, get_events
from claude_client import get_response
from config import TELEGRAM_CHAT_ID, TIMEZONE
from state import format_state_for_prompt, load_state, update_state

logger = logging.getLogger(__name__)


def _authorized(update: Update) -> bool:
    return update.effective_chat.id == TELEGRAM_CHAT_ID


def _build_context() -> tuple[str, str, str]:
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    state = load_state()
    events = get_events(days=7)
    return (
        format_state_for_prompt(state),
        format_events_for_prompt(events),
        now.strftime("%A, %d/%m/%Y %H:%M (Brasília)"),
    )


async def _reply(update: Update, context, text: str, inject_message: str = None):
    state = load_state()
    state_str, cal_str, dt_str = _build_context()
    history = state.get("conversation_history", [])

    user_msg = inject_message or text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    response, updated_history = get_response(
        user_message=user_msg,
        conversation_history=history,
        state_str=state_str,
        calendar_events=cal_str,
        current_datetime=dt_str,
    )

    update_state({"conversation_history": updated_history})

    for chunk in _split_message(response):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "Olá, Ana Luísa! Sou seu assistente de rotina médica.\n\n"
        "Comandos disponíveis:\n"
        "/rotina — planejamento do dia de hoje\n"
        "/semana — agenda dos próximos 7 dias\n"
        "/blocos — próximas sessões de estudo\n"
        "/revisoes — banco de revisões pendentes\n"
        "/reset — limpar histórico da conversa\n\n"
        "Ou simplesmente me escreva — posso encaixar compromissos, reagendar, registrar revisões e muito mais."
    )


async def cmd_rotina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(update, context, "", inject_message="Qual é meu planejamento completo para hoje? Liste horários, compromissos do calendário, blocos de estudo e atividades físicas.")


async def cmd_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(update, context, "", inject_message="Mostre minha agenda estruturada para os próximos 7 dias, incluindo dias de trabalho, folga e blocos de estudo programados.")


async def cmd_blocos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(update, context, "", inject_message="Mostre meu progresso em todos os blocos de estudo e as próximas sessões programadas para esta semana.")


async def cmd_revisoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(update, context, "", inject_message="Mostre meu banco de revisões completo, agrupado por área.")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    update_state({"conversation_history": []})
    await update.message.reply_text("Histórico de conversa resetado.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(update, context, update.message.text)


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
