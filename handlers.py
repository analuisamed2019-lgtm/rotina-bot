import logging
import re
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from calendar_client import format_events_for_prompt, get_events
from claude_client import get_response
from config import TELEGRAM_CHAT_ID, TIMEZONE
from state import fmt_brl, format_state_for_prompt, load_state, update_state

# ── Padrões de detecção financeira ───────────────────────────────────────────
# Detecta: "50", "5,90", "120,90", "1.200,50", "R$ 45,50", "50 reais"
_EXPENSE_RE = re.compile(
    r'^\s*(?:R\$\s*)?([\d.,]+)(?:\s*(?:reais?|R\$))?\s*$',
    re.IGNORECASE,
)

# Detecta: "fatura 3500", "fatura 3.500", "fatura R$ 3.500,00"
_INVOICE_RE = re.compile(
    r'^\s*fatura\s+(?:R\$\s*)?([\d.,]+)',
    re.IGNORECASE,
)


def _parse_br_number(s: str) -> float:
    """Converte número brasileiro (1.200,50 ou 3.500) para float."""
    s = s.strip()
    if '.' in s and ',' in s:
        # Formato 1.200,50 → remove ponto (mil), troca vírgula por ponto (decimal)
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    elif '.' in s:
        # 3.500 → separador de milhar BR (3 dígitos após o ponto)
        # 3.50  → decimal americano (manter como está)
        parts = s.split('.')
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace('.', '')   # 3.500 → 3500
        # else: float() trata como decimal normalmente
    return float(s)


def _parse_expense(text: str) -> float | None:
    """Retorna valor do gasto se a mensagem for apenas um valor numérico, senão None."""
    m = _EXPENSE_RE.match(text)
    if m:
        try:
            val = _parse_br_number(m.group(1))
            # Sanidade: entre R$0,01 e R$50.000
            if 0.01 <= val <= 50000:
                return val
        except ValueError:
            pass
    return None


def _parse_invoice(text: str) -> float | None:
    """Retorna valor da fatura se a mensagem começar com 'fatura X', senão None."""
    m = _INVOICE_RE.match(text)
    if m:
        try:
            return _parse_br_number(m.group(1))
        except ValueError:
            pass
    return None

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
        "/mes — resumo mensal de atividades\n"
        "/gastos — controle financeiro do ciclo\n"
        "/reset — limpar histórico\n\n"
        "Envie um valor (ex: 50 ou 120,90) para registrar gasto.\n"
        "Envie 'fatura 3500' para definir a fatura do cartão.\n"
        "Pode me escrever diretamente para encaixar compromissos, reagendar e mais."
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


async def cmd_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o resumo de atividades do mês atual."""
    if not _authorized(update):
        return
    from state import get_monthly_summary_data, ACTIVITY_GOALS
    import calendar as cal_mod

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    counts = get_monthly_summary_data(now.year, now.month)
    days_in_month = cal_mod.monthrange(now.year, now.month)[1]
    month_name = [
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ][now.month]

    weeks_in_month = days_in_month / 7
    goal_academia = round(ACTIVITY_GOALS["academia"] * weeks_in_month)
    goal_yoga     = round(ACTIVITY_GOALS["yoga"]     * weeks_in_month)
    goal_estudo   = round(ACTIVITY_GOALS["estudo"]   * weeks_in_month)

    def bar(count, goal):
        p = round(count / goal * 100) if goal > 0 else 0
        status = "✅" if count >= goal else ("🔶" if p >= 70 else "❌")
        return f"{status} {count}/{goal} dias ({p}%)"

    registered = counts["dias_registrados"]
    days_so_far = now.day

    msg = (
        f"📅 {month_name}/{now.year} — até dia {now.day}\n"
        f"Dias com check-in: {registered}/{days_so_far}\n\n"
        f"🏋️ Academia:  {bar(counts['academia'], goal_academia)}\n"
        f"🧘 Yoga:      {bar(counts['yoga'], goal_yoga)}\n"
        f"📚 Estudo:    {bar(counts['estudo'], goal_estudo)}\n\n"
        f"Meta mensal: academia {goal_academia}d · yoga {goal_yoga}d · estudo {goal_estudo}d"
    )

    if registered < days_so_far // 2:
        msg += f"\n\n⚠️ Poucos dias com check-in registrado — ative o check-in noturno para dados mais precisos."

    await update.message.reply_text(msg)


async def cmd_setbloco(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Corrige o índice de um bloco de estudo diretamente.
    Uso: /setbloco block1_cirurgia 1
    Blocos válidos: block1_cirurgia, block1_clinica, block2, block4_derma, block4_resp
    """
    if not _authorized(update):
        return
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Uso: `/setbloco <bloco> <índice>`\n\n"
            "Blocos:\n"
            "• `block1_cirurgia` — Cirurgia Geral (0–21)\n"
            "• `block1_clinica` — Clínica Médica (0–32)\n"
            "• `block2` — PSZ (0–21)\n"
            "• `block4_derma` — Emergencinsta Derma (0–3)\n"
            "• `block4_resp` — Emergencinsta Resp (0–4)",
            parse_mode="Markdown"
        )
        return

    bloco = args[0].lower()
    try:
        idx = int(args[1])
    except ValueError:
        await update.message.reply_text("O índice precisa ser um número inteiro.")
        return

    valid = {
        "block1_cirurgia": ("block1", "cirurgia_index", 22),
        "block1_clinica":  ("block1", "clinica_index",  33),
        "block2":          ("block2", "topic_index",    22),
        "block4_derma":    ("block4", "derma_index",    4),
        "block4_resp":     ("block4", "resp_index",     5),
    }
    if bloco not in valid:
        await update.message.reply_text(f"Bloco inválido: `{bloco}`", parse_mode="Markdown")
        return

    group, key, max_idx = valid[bloco]
    if not (0 <= idx <= max_idx):
        await update.message.reply_text(f"Índice fora do intervalo (0–{max_idx}).")
        return

    state = load_state()
    state["study_blocks"][group][key] = idx
    update_state({"study_blocks": state["study_blocks"]})

    # Se é cirurgia ou clínica, sincroniza specialty
    if bloco == "block1_cirurgia" and idx >= 22:
        state2 = load_state()
        state2["study_blocks"]["block1"]["current_specialty"] = "clinica"
        update_state({"study_blocks": state2["study_blocks"]})
    elif bloco == "block1_clinica":
        state2 = load_state()
        state2["study_blocks"]["block1"]["current_specialty"] = "clinica"
        update_state({"study_blocks": state2["study_blocks"]})

    # Mostra o próximo tema
    from state import CIRURGIA_TOPICS, CLINICA_TOPICS, PSZ_TOPICS, DERMA_CLASSES, RESP_CLASSES
    topic_lists = {
        "block1_cirurgia": CIRURGIA_TOPICS,
        "block1_clinica":  CLINICA_TOPICS,
        "block2":          PSZ_TOPICS,
        "block4_derma":    DERMA_CLASSES,
        "block4_resp":     RESP_CLASSES,
    }
    topics = topic_lists[bloco]
    next_topic = topics[idx] if idx < len(topics) else "✅ Módulo concluído"

    await update.message.reply_text(
        f"✅ `{bloco}` ajustado para índice {idx}.\n"
        f"Próximo tema: *{next_topic}*",
        parse_mode="Markdown"
    )


async def cmd_gastos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o resumo financeiro do ciclo atual."""
    if not _authorized(update):
        return
    from state import get_financial_summary
    s = get_financial_summary()
    msg = _format_financial_summary(s, verbose=True)
    await update.message.reply_text(msg)


def _format_financial_summary(s: dict, verbose: bool = False) -> str:
    """Formata o resumo financeiro para exibição no Telegram."""
    lines = [
        f"💸 *Controle Financeiro* — ciclo desde {s['cycle_start']}",
        f"",
        f"💳 Fatura: {fmt_brl(s['invoice'])}",
        f"🟢 Budget livre: {fmt_brl(s['available_free'])}",
        f"📊 Gasto no ciclo: {fmt_brl(s['total_cycle'])} ({s['pct_used']}%)",
        f"",
    ]
    if s["is_negative"]:
        deficit = abs(s["remaining"])
        pct_deficit = round(deficit / s["available_free"] * 100) if s["available_free"] > 0 else 0
        if pct_deficit < 10:
            lines.append(f"⚠️ Limite estourado em {fmt_brl(deficit)} — atenção!")
        elif pct_deficit < 25:
            lines.append(f"🚨 Limite estourado em {fmt_brl(deficit)}! Hora de segurar os gastos.")
        else:
            lines.append(f"🆘 SÉRIO: {fmt_brl(deficit)} acima do limite — precisa cortar urgentemente.")
    else:
        pct_remaining = 100 - s["pct_used"]
        lines.append(f"✅ Disponível: {fmt_brl(s['remaining'])} ({pct_remaining}% restante)")

    if verbose and s["yesterday_total"] > 0:
        lines.append(f"")
        lines.append(f"📅 Ontem: {fmt_brl(s['yesterday_total'])}")

    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    text = update.message.text.strip()

    # ── Detecta "fatura X" ────────────────────────────────────────────────────
    invoice_amount = _parse_invoice(text)
    if invoice_amount is not None:
        from state import get_financial_summary, set_invoice
        set_invoice(invoice_amount)
        s = get_financial_summary()
        msg = (
            f"✅ Fatura registrada: {fmt_brl(invoice_amount)}\n"
            f"Budget livre este ciclo: {fmt_brl(s['available_free'])}\n"
            f"_(Limite {fmt_brl(s['limit'])} − Fatura {fmt_brl(invoice_amount)})_"
        )
        try:
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(msg)
        return

    # ── Detecta gasto direto (ex: "50", "120,90", "R$ 45") ────────────────────
    expense_amount = _parse_expense(text)
    if expense_amount is not None:
        from state import record_expense
        s = record_expense(expense_amount)
        if s["is_negative"]:
            deficit = abs(s["remaining"])
            pct_deficit = round(deficit / s["available_free"] * 100) if s["available_free"] > 0 else 0
            if pct_deficit < 10:
                warning = f"⚠️ Limite estourado em {fmt_brl(deficit)} — atenção!"
            elif pct_deficit < 25:
                warning = f"🚨 {fmt_brl(deficit)} acima do limite! Segura os gastos."
            else:
                warning = f"🆘 SÉRIO: {fmt_brl(deficit)} acima do limite — cortar urgente!"
            msg = (
                f"💸 {fmt_brl(expense_amount)} registrado\n"
                f"Total ciclo: {fmt_brl(s['total_cycle'])} ({s['pct_used']}%)\n"
                f"{warning}"
            )
        else:
            pct_remaining = 100 - s["pct_used"]
            msg = (
                f"💸 {fmt_brl(expense_amount)} registrado\n"
                f"Total ciclo: {fmt_brl(s['total_cycle'])} ({s['pct_used']}%)\n"
                f"✅ Disponível: {fmt_brl(s['remaining'])} ({pct_remaining}% restante)"
            )
        await update.message.reply_text(msg)
        return

    await _reply(update, context, text)



def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
