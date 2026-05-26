import logging
from datetime import datetime, date, timedelta

import pytz

from calendar_client import format_events_for_prompt, get_events
from claude_client import get_response
from config import TELEGRAM_CHAT_ID, TIMEZONE
from state import (
    format_state_for_prompt,
    load_state,
    get_weekly_summary_data,
    get_week_so_far_data,
    ACTIVITY_GOALS,
)

logger = logging.getLogger(__name__)

# Data de renovação do Railway (30 dias a partir de 26/05/2026)
RAILWAY_RENEWAL_DATE = date(2026, 6, 25)

# Lembretes mensais: dia → texto
MONTHLY_REMINDERS = {
    1:  "💆 Lembrete: hoje é dia de pagar a terapia.",
    5:  "📋 Lembrete: hoje é dia de realizar a declaração de pagamento da Prevent.",
    6:  "📱 Lembrete: hoje é dia de pagar a fatura do celular.",
    18: "🏢 Lembrete: hoje é dia de pagar o imposto da Caveo.",
    27: "💳 Lembrete: hoje é dia de pagar a fatura do cartão.",
}


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
            "Considere os tempos de deslocamento. Seja direta e use horários específicos. Formato conciso."
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

    # ── Lembrete mensal ───────────────────────────────────────────────────────
    if now.day in MONTHLY_REMINDERS:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=MONTHLY_REMINDERS[now.day],
        )

    # ── Renovação Railway ─────────────────────────────────────────────────────
    days_until_renewal = (RAILWAY_RENEWAL_DATE - now.date()).days
    if days_until_renewal in (7, 3, 1, 0):
        if days_until_renewal == 0:
            msg = "🚨 Hoje é o dia de renovar o plano do Railway para o bot continuar funcionando! Acesse railway.app → Billing."
        else:
            msg = f"⚠️ Lembrete: o plano do Railway renova em {days_until_renewal} dia(s) ({RAILWAY_RENEWAL_DATE.strftime('%d/%m/%Y')}). Acesse railway.app → Billing."
        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

    # ── Resumo semanal (domingo) ──────────────────────────────────────────────
    if now.weekday() == 6:  # domingo
        monday = now.date() - timedelta(days=6)
        counts = get_weekly_summary_data(monday)
        await _send_weekly_summary(context, counts, monday, now.date())


async def send_end_of_day_checkin(context):
    """Enviado às 21h30 — pergunta quais atividades foram feitas hoje."""
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    counts = get_week_so_far_data(now.date())

    # Parcial da semana
    def bar(count, goal):
        filled = "●" * count
        empty = "○" * max(0, goal - count)
        status = "✅" if count >= goal else "🔄"
        return f"{status} {filled}{empty} {count}/{goal}"

    parcial = (
        f"🏋️ Academia  {bar(counts['academia'], ACTIVITY_GOALS['academia'])}\n"
        f"🧘 Yoga      {bar(counts['yoga'],     ACTIVITY_GOALS['yoga'])}\n"
        f"📚 Estudo    {bar(counts['estudo'],   ACTIVITY_GOALS['estudo'])}"
    )

    msg = (
        f"Fim de dia! 🌙 O que você fez hoje?\n"
        f"Responda com as atividades: academia, yoga, estudo — ou diga o que não conseguiu fazer.\n\n"
        f"Semana até agora:\n{parcial}"
    )

    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)


async def _send_weekly_summary(context, counts: dict, week_start, week_end):
    def status(count, goal):
        if count >= goal:
            return f"✅ {count}/{goal} — meta batida!"
        else:
            return f"❌ {count}/{goal} — faltou {goal - count} dia(s)"

    msg = (
        f"📊 Resumo da semana ({week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m')})\n\n"
        f"🏋️ Academia:  {status(counts['academia'], ACTIVITY_GOALS['academia'])}\n"
        f"🧘 Yoga:      {status(counts['yoga'],     ACTIVITY_GOALS['yoga'])}\n"
        f"📚 Estudo:    {status(counts['estudo'],   ACTIVITY_GOALS['estudo'])}\n"
    )

    total_goals = sum(1 for a, g in ACTIVITY_GOALS.items() if counts[a] >= g)
    if total_goals == 3:
        msg += "\nSemana completa! 🎉"
    elif total_goals == 2:
        msg += "\nQuase lá — 2 de 3 metas batidas."
    else:
        msg += "\nSemana difícil — mas a próxima começa do zero."

    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
