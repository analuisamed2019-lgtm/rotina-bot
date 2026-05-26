import anthropic
from datetime import datetime

import pytz

from config import ANTHROPIC_API_KEY, TIMEZONE
from prompts import SYSTEM_PROMPT

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MAX_HISTORY = 20

TOOLS = [
    {
        "name": "list_calendar_events",
        "description": "Lista eventos do calendário. Use para buscar IDs completos antes de editar ou deletar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Quantos dias a partir de hoje (padrão 7)", "default": 7},
                "start_date": {"type": "string", "description": "Data inicial opcional no formato YYYY-MM-DD"}
            }
        }
    },
    {
        "name": "create_calendar_event",
        "description": "Cria um evento no Google Calendar. Só chame APÓS o usuário confirmar explicitamente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Título do evento"},
                "start_datetime": {"type": "string", "description": "Início ISO 8601 com offset, ex: 2026-05-26T14:00:00-03:00"},
                "end_datetime": {"type": "string", "description": "Fim ISO 8601 com offset"},
                "description": {"type": "string", "description": "Descrição opcional"},
                "recurrence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Regras RRULE, ex: ['RRULE:FREQ=WEEKLY;BYDAY=TH;INTERVAL=2'] para quinzenal"
                }
            },
            "required": ["summary", "start_datetime", "end_datetime"]
        }
    },
    {
        "name": "update_calendar_event",
        "description": "Atualiza um evento existente. Só chame APÓS o usuário confirmar. Requer o ID completo do evento.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID completo do evento obtido via list_calendar_events"},
                "summary": {"type": "string"},
                "start_datetime": {"type": "string", "description": "Novo início ISO 8601"},
                "end_datetime": {"type": "string", "description": "Novo fim ISO 8601"},
                "description": {"type": "string"}
            },
            "required": ["event_id"]
        }
    },
    {
        "name": "delete_calendar_event",
        "description": "Remove um evento. Só chame APÓS confirmação explícita do usuário.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID completo do evento"}
            },
            "required": ["event_id"]
        }
    },
    {
        "name": "advance_study_block",
        "description": "Avança o índice de um bloco de estudo após sessão concluída.",
        "input_schema": {
            "type": "object",
            "properties": {
                "block": {
                    "type": "string",
                    "enum": ["block1_cirurgia", "block1_clinica", "block2", "block4_derma", "block4_resp"],
                    "description": "Qual bloco avançar"
                },
                "steps": {"type": "integer", "description": "Sessões concluídas (normalmente 1)", "default": 1}
            },
            "required": ["block"]
        }
    },
    {
        "name": "manage_revision_bank",
        "description": "Adiciona ou remove item do banco de revisões pendentes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove"]},
                "area": {"type": "string", "description": "Área médica, ex: Cardiologia"},
                "topic": {"type": "string", "description": "Tema específico a revisar"}
            },
            "required": ["action", "area", "topic"]
        }
    },
    {
        "name": "record_daily_activities",
        "description": "Registra quais atividades foram realizadas em um dia. Chamar quando a usuária relatar as atividades do dia (após o check-in noturno ou espontaneamente).",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Data no formato YYYY-MM-DD"},
                "academia": {"type": "boolean", "description": "Foi à academia?"},
                "yoga": {"type": "boolean", "description": "Foi ao yoga?"},
                "estudo": {"type": "boolean", "description": "Estudou?"}
            },
            "required": ["date", "academia", "yoga", "estudo"]
        }
    }
]


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

    while True:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system,
            tools=TOOLS,
            messages=history,
        )

        history.append({"role": "assistant", "content": _serialize_content(response.content)})

        if response.stop_reason == "end_turn":
            text = next((b.text for b in response.content if hasattr(b, "text")), "")
            return text, history

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = _execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Erro: {str(e)}",
                        "is_error": True,
                    })
            history.append({"role": "user", "content": tool_results})
        else:
            text = next((b.text for b in response.content if hasattr(b, "text")), "")
            return text, history


def _serialize_content(content) -> list:
    """Convert Anthropic SDK content blocks to plain dicts for JSON storage."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    result = []
    for block in content:
        if hasattr(block, "type"):
            if block.type == "text":
                result.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        else:
            result.append(block)
    return result


def _execute_tool(name: str, inp: dict) -> str:
    import calendar_client as cal
    import state as st

    tz = pytz.timezone(TIMEZONE)

    if name == "list_calendar_events":
        days = inp.get("days", 7)
        start_date = None
        if "start_date" in inp:
            d = datetime.strptime(inp["start_date"], "%Y-%m-%d")
            start_date = tz.localize(d)
        events = cal.get_events(start_date=start_date, days=days)
        return cal.format_events_for_prompt(events, full_ids=True)

    elif name == "create_calendar_event":
        start_dt = datetime.fromisoformat(inp["start_datetime"])
        end_dt = datetime.fromisoformat(inp["end_datetime"])
        event = cal.create_event(
            summary=inp["summary"],
            start_dt=start_dt,
            end_dt=end_dt,
            description=inp.get("description"),
            recurrence=inp.get("recurrence"),
        )
        return f"Evento criado com sucesso: '{event.get('summary')}' (id: {event.get('id')})"

    elif name == "update_calendar_event":
        updates = {}
        if "summary" in inp:
            updates["summary"] = inp["summary"]
        if "start_datetime" in inp:
            dt = datetime.fromisoformat(inp["start_datetime"])
            updates["start"] = {"dateTime": dt.isoformat(), "timeZone": TIMEZONE}
        if "end_datetime" in inp:
            dt = datetime.fromisoformat(inp["end_datetime"])
            updates["end"] = {"dateTime": dt.isoformat(), "timeZone": TIMEZONE}
        if "description" in inp:
            updates["description"] = inp["description"]
        event = cal.update_event(inp["event_id"], updates)
        return f"Evento atualizado: '{event.get('summary')}'"

    elif name == "delete_calendar_event":
        cal.delete_event(inp["event_id"])
        return "Evento removido com sucesso."

    elif name == "advance_study_block":
        block = inp["block"]
        steps = inp.get("steps", 1)
        st.advance_block(block, steps)
        return f"Progresso do bloco '{block}' avançado em {steps} sessão(ões)."

    elif name == "manage_revision_bank":
        area = inp["area"]
        topic = inp["topic"]
        if inp["action"] == "add":
            st.add_to_revision_bank(area, topic)
            return f"'{topic}' adicionado ao banco de revisões ({area})."
        else:
            st.remove_from_revision_bank(area, topic)
            return f"'{topic}' removido do banco de revisões."

    elif name == "record_daily_activities":
        st.record_activities(
            date_str=inp["date"],
            academia=inp["academia"],
            yoga=inp["yoga"],
            estudo=inp["estudo"],
        )
        today = datetime.fromisoformat(inp["date"]).date()
        counts = st.get_week_so_far_data(today)
        return (
            f"Atividades de {inp['date']} registradas: "
            f"academia={'sim' if inp['academia'] else 'não'}, "
            f"yoga={'sim' if inp['yoga'] else 'não'}, "
            f"estudo={'sim' if inp['estudo'] else 'não'}. "
            f"Semana até agora — academia: {counts['academia']}/2, "
            f"yoga: {counts['yoga']}/3, estudo: {counts['estudo']}/3."
        )

    else:
        raise ValueError(f"Ferramenta desconhecida: {name}")
