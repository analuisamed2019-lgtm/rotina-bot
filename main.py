import logging
from datetime import time

import pytz
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import PORT, TELEGRAM_BOT_TOKEN, TIMEZONE, WEBHOOK_URL
from handlers import (
    cmd_blocos,
    cmd_fimtreino,
    cmd_gastos,
    cmd_mes,
    cmd_progressao,
    cmd_reset,
    cmd_revisoes,
    cmd_rotina,
    cmd_semana,
    cmd_setbloco,
    cmd_settreino,
    cmd_start,
    cmd_testcal,
    cmd_treino,
    handle_message,
)
from scheduler import send_morning_briefing, send_end_of_day_checkin

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("rotina", cmd_rotina))
    app.add_handler(CommandHandler("semana", cmd_semana))
    app.add_handler(CommandHandler("blocos", cmd_blocos))
    app.add_handler(CommandHandler("revisoes", cmd_revisoes))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("mes", cmd_mes))
    app.add_handler(CommandHandler("gastos", cmd_gastos))
    app.add_handler(CommandHandler("setbloco", cmd_setbloco))
    app.add_handler(CommandHandler("treino", cmd_treino))
    app.add_handler(CommandHandler("fimtreino", cmd_fimtreino))
    app.add_handler(CommandHandler("progressao", cmd_progressao))
    app.add_handler(CommandHandler("testcal", cmd_testcal))
    app.add_handler(CommandHandler("settreino", cmd_settreino))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    tz = pytz.timezone(TIMEZONE)
    app.job_queue.run_daily(
        send_morning_briefing,
        time=time(5, 0, 0, tzinfo=tz),
        name="morning_briefing",
    )

    app.job_queue.run_daily(
        send_end_of_day_checkin,
        time=time(20, 0, 0, tzinfo=tz),
        name="end_of_day_checkin",
    )

    logger.info(f"Starting webhook on port {PORT} → {WEBHOOK_URL}/webhook")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
