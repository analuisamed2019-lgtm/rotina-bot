import io
import logging
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from calendar_client import format_events_for_prompt, get_events
from claude_client import get_response
from config import OPENAI_API_KEY, TELEGRAM_CHAT_ID, TIMEZONE
from state import format_state_for_prompt, load_state, update_state

logger = logging.getLogger(__name__)

# Máximo de mensagens no histórico antes de truncar automaticamente
MAX_HISTORY = 16


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


def _clean_history(history: list) -> list:
    """
    Garante que o histórico está em formato válido para a API Anthropic.
    Remove entradas malformadas e trunca se necessário.
    """
    clean = []
    for msg in history:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or content is None:
            continue
        clean.append(msg)

    # Trunca mantendo as mensagens mais recentes (sempre número par)
    if len(clean) > MAX_HISTORY:
        clean = clean[-MAX_HISTORY:]
        # Garante que começa com "user"
        while clean and clean[0].get("role") != "user":
            clean = clean[1:]

    return clean


async def _reply(update: Update, context, text: str, inject_message: str = None):
    state = load_state()
    history = _clean_history(state.get("conversation_history", []))
    user_msg = inject_message or text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        state_str, cal_str, dt_str = _build_context()

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

    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}", exc_info=True)

        # Auto-reset do histórico para se recuperar
        update_state({"conversation_history": []})

        await update.message.reply_text(
            "Tive um problema interno e resetei o histórico da conversa para me recuperar. "
            "Pode repetir sua última mensagem?"
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "Olá, Ana Luísa! Sou seu assistente de rotina médica.\n\n"
        "Comandos:\n"
        "/rotina — planejamento do dia\n"
        "/semana — agenda dos próximos 7 dias\n"
        "/blocos — progresso nos estudos\n"
        "/revisoes — banco de revisões\n"
        "/reset — limpar histórico\n\n"
        "Pode me escrever diretamente para encaixar compromissos, reagendar, registrar revisões e mais."
    )


async def cmd_rotina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(
        update, context, "",
        inject_message="Qual é meu planejamento completo para hoje? Liste horários, compromissos do calendário, blocos de estudo e atividades físicas."
    )


async def cmd_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(
        update, context, "",
        inject_message="Mostre minha agenda estruturada para os próximos 7 dias, incluindo dias de trabalho, folga e blocos de estudo."
    )


async def cmd_blocos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(
        update, context, "",
        inject_message="Mostre meu progresso em todos os blocos de estudo e as próximas sessões programadas."
    )


async def cmd_revisoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(
        update, context, "",
        inject_message="Mostre meu banco de revisões completo, agrupado por área."
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    update_state({"conversation_history": []})
    await update.message.reply_text("Histórico resetado.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(update, context, update.message.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcreve mensagem de voz via Whisper e passa pelo pipeline normal."""
    if not _authorized(update):
        return

    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "Transcrição de áudio não está configurada. "
            "Adicione OPENAI_API_KEY nas variáveis do Railway para ativar essa função."
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        from openai import OpenAI
        oai = OpenAI(api_key=OPENAI_API_KEY)

        voice_file = await update.message.voice.get_file()
        buf = io.BytesIO()
        await voice_file.download_to_memory(buf)
        buf.seek(0)
        buf.name = "audio.ogg"  # Whisper precisa de extensão reconhecível

        transcription = oai.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            language="pt",
        )
        text = transcription.text.strip()

        if not text:
            await update.message.reply_text("Não consegui entender o áudio. Tente novamente.")
            return

        # Mostra o que foi entendido antes de processar
        await update.message.reply_text(f"🎙 _{text}_", parse_mode="Markdown")

        # Processa como se fosse mensagem de texto normal
        await _reply(update, context, text)

    except Exception as e:
        logger.error(f"Erro ao transcrever voz: {e}", exc_info=True)
        await update.message.reply_text(
            "Não consegui processar o áudio. Tente escrever sua mensagem."
        )


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
