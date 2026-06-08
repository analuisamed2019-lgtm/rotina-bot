import logging
import re
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from calendar_client import format_events_for_prompt, get_events
from claude_client import get_response
from config import TELEGRAM_CHAT_ID, TIMEZONE
from state import (
    fmt_brl,
    format_state_for_prompt,
    get_active_gym_session,
    get_gym_progression,
    get_last_gym_session,
    GYM_PLANS,
    finish_gym_session,
    load_state,
    record_exercise_load,
    start_gym_session,
    update_state,
)

# ── Padrão de carga de exercício ─────────────────────────────────────────────
# Detecta: "1 15", "1 15kg", "1 - 15", "1: 15,5", "3 20.5kg"
_LOAD_RE = re.compile(
    r'^(\d{1,2})\s*[-:\s]+\s*([\d.,]+)\s*(?:kg)?\s*$',
    re.IGNORECASE,
)

# ── Padrão de acordar tarde ──────────────────────────────────────────────────
# Detecta: "acordei 9am", "acordei às 9h", "acordei 9:30", "acordei 10h30"
_WAKEUP_RE = re.compile(
    r'\bacordei\b.*?(\d{1,2})(?:[h:]\s*(\d{2}))?\s*(?:am|pm|h)?\b',
    re.IGNORECASE,
)

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


def _parse_expense(text: str) -> float:
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


def _parse_invoice(text: str) -> float:
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

    # Contexto: tenta buscar calendário, mas não trava se falhar
    try:
        state_str, cal_str, dt_str = _build_context()
    except Exception as e:
        logger.error(f"Erro ao buscar contexto/calendário: {e}", exc_info=True)
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        state_str = format_state_for_prompt(load_state())
        cal_str = f"(calendário indisponível — erro: {type(e).__name__}: {str(e)[:200]})"
        dt_str = now.strftime("%A, %d/%m/%Y %H:%M (Brasília)")
        # Avisa diretamente em vez de passar pelo Claude
        await update.message.reply_text(f"⚠️ Calendário: {type(e).__name__}: {str(e)[:300]}")

    try:
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
        logger.error(f"Erro na API Claude: {e}", exc_info=True)
        err_type = type(e).__name__
        update_state({"conversation_history": []})
        await update.message.reply_text(
            f"⚠️ Erro ao processar ({err_type}). Histórico resetado.\n"
            "Pode repetir sua mensagem?"
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
        "Envie 'fatura 3500' para definir a fatura do cartão.\n\n"
        "🏋️ Academia:\n"
        "/treino — exercícios do dia (A ou B)\n"
        "/fimtreino — resumo de cargas\n"
        "/progressao A ou B — histórico de progressão\n\n"
        "Pode me escrever diretamente para encaixar compromissos, reagendar e mais."
    )


async def cmd_rotina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await _reply(
        update, context, "",
        inject_message=(
            "Monte o planejamento completo de hoje. "
            "Busque os eventos do calendário, monte a timeline com horários reais "
            "(acordar, café, Frodo, deslocamentos, compromissos, estudo, academia, almoço) "
            "e crie no Google Calendar todos os eventos de rotina que ainda não existirem — "
            "☀️ Acordar, ☕ Café da manhã, 🐾 Passeio com Frodo, 🚗 Deslocamentos, 🍽️ Almoço."
        )
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


def _fmt_kg(w: float) -> str:
    """Formata peso: 15 → '15kg', 12.5 → '12,5kg'"""
    if w == int(w):
        return f"{int(w)}kg"
    return f"{w:.1f}kg".replace(".", ",")


def _fmt_progression(current: float, prev) -> str:
    if prev is None:
        return ""
    diff = current - prev
    if diff > 0:
        return f" ↑ +{_fmt_kg(diff)}"
    elif diff < 0:
        return f" ↓ -{_fmt_kg(abs(diff))}"
    return " ="


async def cmd_treino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra o treino do dia (A ou B) com exercícios numerados."""
    if not _authorized(update):
        return

    state = load_state()
    gym = state.get("gym", {})
    plan = gym.get("current_plan", "A")
    exercises = GYM_PLANS[plan]
    last = get_last_gym_session(plan)

    session = start_gym_session(plan)

    lines = [f"🏋️ *Treino {plan}* — {session['date']}\n"]
    for i, ex in enumerate(exercises, 1):
        last_load = ""
        if last and str(i) in last.get("loads", {}):
            last_load = f"  _(último: {_fmt_kg(last['loads'][str(i)])})_"
        lines.append(f"{i}. *{ex['name']}*{last_load}")
        lines.append(f"   {ex['sets']}")

    lines.append("\n📝 Após cada exercício, manda o número + carga:")
    lines.append("`1 15kg`  ou  `1 - 15`  ou  `1: 12,5`")
    lines.append("\n/fimtreino para ver o resumo completo.")

    try:
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("\n".join(lines))


async def cmd_fimtreino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finaliza o treino ativo e mostra resumo de cargas com progressão."""
    if not _authorized(update):
        return

    active = get_active_gym_session()
    if not active:
        await update.message.reply_text(
            "Nenhum treino ativo no momento. Use /treino para começar."
        )
        return

    session, prev = finish_gym_session()
    plan = session["plan"]
    exercises = GYM_PLANS[plan]
    loads = session.get("loads", {})
    next_plan = "B" if plan == "A" else "A"

    lines = [f"📊 *Resumo — Treino {plan}* ({session['date']})\n"]
    registered = 0
    for i, ex in enumerate(exercises, 1):
        key = str(i)
        if key in loads:
            w = loads[key]
            prev_w = prev["loads"].get(key) if prev else None
            prog = _fmt_progression(w, prev_w)
            lines.append(f"{i}. {ex['name']}: *{_fmt_kg(w)}*{prog}")
            registered += 1
        else:
            lines.append(f"{i}. {ex['name']}: —")

    lines.append(f"\n✅ {registered}/{len(exercises)} exercícios registrados")
    lines.append(f"Próximo treino: *Treino {next_plan}*")

    if not prev:
        lines.append("\n_(Primeiro treino registrado — progressão disponível a partir do próximo)_")

    try:
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("\n".join(lines))


async def cmd_progressao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra a progressão histórica de cargas por exercício."""
    if not _authorized(update):
        return

    args = context.args
    plan = (args[0].upper() if args else None)
    if plan not in ("A", "B"):
        await update.message.reply_text(
            "Uso: `/progressao A` ou `/progressao B`", parse_mode="Markdown"
        )
        return

    sessions = get_gym_progression(plan)
    if not sessions:
        await update.message.reply_text(f"Nenhum treino {plan} registrado ainda.")
        return

    exercises = GYM_PLANS[plan]
    lines = [f"📈 *Progressão — Treino {plan}*\n"]

    for i, ex in enumerate(exercises, 1):
        key = str(i)
        history = []
        for s in sessions:
            if key in s.get("loads", {}):
                history.append((s["date"][5:], s["loads"][key]))  # MM-DD, kg
        if not history:
            lines.append(f"{i}. {ex['name']}: sem dados")
            continue
        # Linha de histórico resumida
        hist_str = " → ".join(f"{_fmt_kg(w)}" for _, w in history[-5:])  # últimos 5
        trend = ""
        if len(history) >= 2:
            diff = history[-1][1] - history[0][1]
            if diff > 0:
                trend = f" _(+{_fmt_kg(diff)} total)_"
            elif diff < 0:
                trend = f" _(-{_fmt_kg(abs(diff))} total)_"
        lines.append(f"{i}. *{ex['name']}*{trend}")
        lines.append(f"   {hist_str}")

    try:
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("\n".join(lines))


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


async def cmd_testcal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnóstico do Calendar — testa token e reporta resultado."""
    if not _authorized(update):
        return
    import os
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GRequest

    # Verifica se existe .env no servidor
    env_file_info = "não encontrado"
    try:
        with open("/app/.env") as f:
            lines = [l for l in f.readlines() if "REFRESH" in l]
            if lines:
                env_file_info = f"TEM .env! Linha: {lines[0][:40]}"
            else:
                env_file_info = ".env existe mas sem REFRESH_TOKEN"
    except FileNotFoundError:
        env_file_info = "não encontrado (ok)"
    except Exception as e:
        env_file_info = f"erro: {e}"

    token = os.environ.get("GOOGLE_REFRESH_TOKEN", "NAO_DEFINIDO")
    await update.message.reply_text(
        f"🔍 Token no servidor:\n"
        f"Tamanho: {len(token)} chars\n"
        f"Início: `{token[:15]}`\n"
        f"Fim: `{token[-10:]}`\n"
        f".env: {env_file_info}"
    )
    try:
        from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        creds = Credentials(
            token=None,
            refresh_token=token.strip(),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        creds.refresh(GRequest())
        await update.message.reply_text("✅ Token válido! Calendar funcionando.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro token env:\n{e}")

    # Teste com token novo hardcoded para confirmar se Railway consegue conectar
    try:
        from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        _t = ("1//0hEUYgApn07o-CgYIARAAGBESNwF-L9IrSknNKjMoUFXncO0tA97"
              "RjW_7E8tbsCgjQVw5SaPn7NpgnFCo449LSySSNnkhO3ojMQM")
        creds2 = Credentials(
            token=None,
            refresh_token=_t,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        creds2.refresh(GRequest())
        await update.message.reply_text("✅ Token hardcoded funciona! Problema é só na env var do Railway.")
    except Exception as e:
        await update.message.reply_text(f"❌ Token hardcoded também falhou:\n{e}")


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

    # ── Detecta carga de exercício (ex: "1 15kg", "3 - 20") ──────────────────
    load_match = _LOAD_RE.match(text)
    if load_match:
        active = get_active_gym_session()
        if active:
            ex_num = int(load_match.group(1))
            plan = active["plan"]
            exercises = GYM_PLANS[plan]
            if 1 <= ex_num <= len(exercises):
                try:
                    weight = _parse_br_number(load_match.group(2))
                except ValueError:
                    weight = None
                if weight and weight > 0:
                    record_exercise_load(ex_num, weight)
                    ex_name = exercises[ex_num - 1]["name"]
                    last = get_last_gym_session(plan)
                    prev_w = last["loads"].get(str(ex_num)) if last else None
                    prog = _fmt_progression(weight, prev_w)
                    msg = f"✅ {ex_num}. {ex_name}: *{_fmt_kg(weight)}*{prog}"
                    try:
                        await update.message.reply_text(msg, parse_mode="Markdown")
                    except Exception:
                        await update.message.reply_text(msg)
                    return

    # ── Detecta "acordei Xh" e recalcula o dia ───────────────────────────────
    wakeup_match = _WAKEUP_RE.search(text)
    if wakeup_match:
        hour = int(wakeup_match.group(1))
        minutes = wakeup_match.group(2) or "00"
        wakeup_str = f"{hour:02d}h{minutes}"
        inject = (
            f"Acordei às {wakeup_str}. "
            f"Recalcula meu dia de hoje do zero a partir desse horário. "
            f"Considera: passeio com Frodo, yoga (se ainda der pelo horário — "
            f"terça/quinta têm aula às 7h ou 19h; sábado só tem 9h), "
            f"academia, blocos de estudo previstos e refeições. "
            f"Monta a timeline completa do dia com horários reais. "
            f"Cria no Google Calendar todos os eventos de rotina que ainda não existirem "
            f"(☀️ Acordar, ☕ Café da manhã, 🐾 Passeio com Frodo, 🚗 Deslocamentos, 🍽️ Almoço). "
            f"Se algo não couber, avisa o que fica de fora."
        )
        await _reply(update, context, text, inject_message=inject)
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
