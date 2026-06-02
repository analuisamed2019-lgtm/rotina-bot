import logging
from datetime import datetime, date, timedelta

import pytz

from calendar_client import format_events_for_prompt, get_events
from claude_client import get_response
from config import TELEGRAM_CHAT_ID, TIMEZONE
from state import (
    fmt_brl,
    format_state_for_prompt,
    get_financial_summary,
    get_monthly_summary_data,
    get_week_so_far_data,
    get_weekly_summary_data,
    load_state,
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
    22: "📊 Lembrete: hoje é dia de fazer seu balanço financeiro mensal.",
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
            "Monte o planejamento do dia de hoje e crie no Google Calendar todos os eventos "
            "de rotina que ainda não existirem: ☀️ Acordar, ☕ Café da manhã, 🐾 Passeio com Frodo, "
            "🚗 Deslocamentos (antes de cada saída de casa), 🍽️ Almoço. "
            "Inclua também todos os compromissos existentes com horários, blocos de estudo e atividades físicas. "
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

    # ── Resumo financeiro ─────────────────────────────────────────────────────
    try:
        fin = get_financial_summary(today=now.date())
        fin_line = (
            f"💸 Financeiro: Ontem {fmt_brl(fin['yesterday_total'])} | "
            f"Ciclo {fmt_brl(fin['total_cycle'])} ({fin['pct_used']}%) | "
        )
        if fin["is_negative"]:
            fin_line += f"🚨 Negativo {fmt_brl(abs(fin['remaining']))}"
        else:
            fin_line += f"Disponível {fmt_brl(fin['remaining'])}"
        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=fin_line)
    except Exception as e:
        logger.warning(f"Erro no resumo financeiro: {e}")

    # ── Lembrete mensal ───────────────────────────────────────────────────────
    if now.day in MONTHLY_REMINDERS:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=MONTHLY_REMINDERS[now.day],
        )

    # ── Pergunta fatura no início do mês ─────────────────────────────────────
    if now.day == 1:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                "💳 Início do mês! Qual é o valor da fatura do cartão este mês?\n"
                "Responda com: *fatura + valor*\n"
                "Exemplo: `fatura 3.500`"
            ),
            parse_mode="Markdown",
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

    # ── Resumo mensal (último dia do mês) ─────────────────────────────────────
    import calendar as cal_mod
    last_day = cal_mod.monthrange(now.year, now.month)[1]
    if now.day == last_day:
        m_counts = get_monthly_summary_data(now.year, now.month)
        await _send_monthly_summary(context, m_counts, now.year, now.month)


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


async def _send_monthly_summary(context, counts: dict, year: int, month: int):
    import calendar as cal_mod
    month_name = [
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ][month]
    days_in_month = cal_mod.monthrange(year, month)[1]
    registered = counts["dias_registrados"]

    def pct(count, goal_per_week=None, total_possible=None):
        if total_possible and total_possible > 0:
            p = round(count / total_possible * 100)
            return f"{count}/{total_possible} dias ({p}%)"
        return f"{count} dia(s)"

    # Metas mensais: academia 2×/semana ~8 dias, yoga 3×/semana ~12 dias, estudo 3×/semana ~12 dias
    weeks_in_month = days_in_month / 7
    goal_academia = round(ACTIVITY_GOALS["academia"] * weeks_in_month)
    goal_yoga     = round(ACTIVITY_GOALS["yoga"]     * weeks_in_month)
    goal_estudo   = round(ACTIVITY_GOALS["estudo"]   * weeks_in_month)

    def bar_monthly(count, goal):
        p = round(count / goal * 100) if goal > 0 else 0
        status = "✅" if count >= goal else ("🔶" if p >= 70 else "❌")
        return f"{status} {count}/{goal} dias ({p}%)"

    msg = (
        f"📅 Resumo de {month_name}/{year}\n"
        f"Dias registrados: {registered}/{days_in_month}\n\n"
        f"🏋️ Academia:  {bar_monthly(counts['academia'], goal_academia)}\n"
        f"🧘 Yoga:      {bar_monthly(counts['yoga'], goal_yoga)}\n"
        f"📚 Estudo:    {bar_monthly(counts['estudo'], goal_estudo)}\n"
    )

    total_goals = sum(1 for a, g in [
        ("academia", goal_academia), ("yoga", goal_yoga), ("estudo", goal_estudo)
    ] if counts[a] >= g)

    if registered < days_in_month // 2:
        msg += f"\n⚠️ Poucos dias registrados ({registered}/{days_in_month}) — os dados podem estar incompletos."

    if total_goals == 3:
        msg += "\n\nMês completo — todas as metas batidas! 🎉"
    elif total_goals == 2:
        msg += "\n\nQuase lá — 2 de 3 metas mensais batidas."
    else:
        msg += "\n\nMês difícil — mas o próximo começa do zero. 💪"

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
