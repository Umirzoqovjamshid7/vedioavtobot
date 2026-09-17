import os
import logging
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database1 import (
    init_db,
    add_video,
    get_next_videos_for_chat,
    get_approved_chats,
    get_stats,
    reset_queue,
    register_chat,
    approve_chat,
    reject_chat,
    mark_delivered,
)


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Tashkent")
SEND_TIME = os.getenv("SEND_TIME", "09:00")
VIDEOS_PER_RUN = int(os.getenv("VIDEOS_PER_RUN", "10"))

TZ = ZoneInfo(TIMEZONE_NAME)


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ADMIN_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            "⛔ Siz ushbu bot administratori emassiz."
        )
        return

    await update.message.reply_text(
        "🎬 Video Bot ishga tushdi.\n\n"
        "Menga videolarni yuboring. Men ularni navbatga "
        "saqlayman va belgilangan vaqtda guruhga yuboraman.\n\n"
        "Buyruqlar:\n"
        "/status - navbat holati\n"
        "/sendnow - hozir navbatdagi videolarni yuborish\n"
        "/reset - barcha videolarni qayta navbatga qo'yish\n"
        "/chatid - joriy chat ID"
    )


async def save_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update):
        return

    # Video faqat bot bilan private chat orqali qabul qilinadi.
    if update.effective_chat.type != "private":
        return

    video = update.message.video

    if not video:
        return

    video_id = add_video(
        file_id=video.file_id,
        file_unique_id=video.file_unique_id,
        caption=update.message.caption,
    )

    if video_id is None:
        await update.message.reply_text(
            "⚠️ Bu video avval saqlangan."
        )
        return

    total, sent, waiting = get_stats()

    await update.message.reply_text(
        f"✅ Video #{video_id} saqlandi.\n\n"
        f"📦 Jami: {total}\n"
        f"⏳ Navbatda: {waiting}\n"
        f"✅ Yuborilgan: {sent}"
    )


async def send_videos(context: ContextTypes.DEFAULT_TYPE):
    chats = get_approved_chats()
    if not chats:
        logger.info("Tasdiqlangan guruhlar yo'q.")
        return

    for chat in chats:
        videos = get_next_videos_for_chat(chat["chat_id"], VIDEOS_PER_RUN)
        for video in videos:
            try:
                await context.bot.send_video(
                    chat_id=chat["chat_id"],
                    video=video["file_id"],
                    caption=video["caption"] or None,
                )
                mark_delivered(video["id"], chat["chat_id"])
                logger.info(
                    "Video %s yuborildi: chat=%s",
                    video["id"],
                    chat["chat_id"],
                )
            except Exception:
                logger.exception(
                    "Video yuborishda xatolik: video=%s chat=%s",
                    video["id"],
                    chat["chat_id"],
                )
                break


async def group_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member_update = update.my_chat_member
    if not member_update or member_update.chat.type not in {"group", "supergroup"}:
        return

    new_status = member_update.new_chat_member.status
    if new_status not in {"member", "administrator"}:
        return

    chat_id = member_update.chat.id
    state = register_chat(chat_id, member_update.chat.title)
    if state != "new":
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Tasdiqlash",
                callback_data=f"approve:{chat_id}",
            ),
            InlineKeyboardButton(
                "❌ Rad etish",
                callback_data=f"reject:{chat_id}",
            ),
        ]
    ])
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"Bot yangi guruhga qo'shildi: {member_update.chat.title}\n\n"
                "Shu guruhga har kuni video yuborishni tasdiqlaysizmi?"
            ),
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception(
            "Tasdiqlash xabarini admin'ga yuborib bo'lmadi. "
            "Admin avval botga /start yuborsin."
        )


async def chat_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not is_admin(update):
        return
    await query.answer()

    action, chat_id_text = query.data.split(":", 1)
    chat_id = int(chat_id_text)
    if action == "approve":
        approve_chat(chat_id)
        await query.edit_message_text(
            f"✅ Tasdiqlandi. {chat_id} guruhiga har kuni "
            f"{VIDEOS_PER_RUN} ta video yuboriladi."
        )
    else:
        reject_chat(chat_id)
        await query.edit_message_text("❌ Guruh rad etildi.")


async def send_now(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update):
        return

    await update.message.reply_text(
        "⏳ Videolar yuborilmoqda..."
    )

    await send_videos(context)

    total, sent, waiting = get_stats()

    await update.message.reply_text(
        f"✅ Jarayon tugadi.\n\n"
        f"📦 Jami: {total}\n"
        f"✅ Yuborilgan: {sent}\n"
        f"⏳ Qolgan: {waiting}"
    )


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update):
        return

    total, sent, waiting = get_stats()

    await update.message.reply_text(
        "📊 BOT HOLATI\n\n"
        f"📦 Jami videolar: {total}\n"
        f"✅ Yuborilgan: {sent}\n"
        f"⏳ Navbatda: {waiting}\n\n"
        f"🕐 Yuborish vaqti: {SEND_TIME}\n"
        f"🎬 Bir martada: {VIDEOS_PER_RUN} ta\n"
        f"🌍 Timezone: {TIMEZONE_NAME}"
    )


async def reset(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update):
        return

    reset_queue()

    await update.message.reply_text(
        "🔄 Barcha videolar qayta navbatga qo'yildi."
    )


async def chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update):
        return

    await update.message.reply_text(
        f"Chat ID: `{update.effective_chat.id}`",
        parse_mode="Markdown",
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Telegram bot xatosi:",
        exc_info=context.error,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN .env faylida ko'rsatilmagan."
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "ADMIN_ID .env faylida ko'rsatilmagan."
        )

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("sendnow", send_now))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("chatid", chat_id))
    app.add_handler(
        ChatMemberHandler(group_added, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    app.add_handler(CallbackQueryHandler(chat_approval))

    app.add_handler(
        MessageHandler(
            filters.VIDEO,
            save_video,
        )
    )

    app.add_error_handler(error_handler)

    try:
        hour, minute = map(int, SEND_TIME.split(":"))
    except ValueError:
        raise RuntimeError(
            "SEND_TIME noto'g'ri. Masalan: SEND_TIME=09:00"
        )

    app.job_queue.run_daily(
        send_videos,
        time=time(
            hour=hour,
            minute=minute,
            tzinfo=TZ,
        ),
        name="daily_video_sender",
    )

    logger.info(
        "Bot ishga tushdi. Har kuni %s da %s ta video yuboriladi.",
        SEND_TIME,
        VIDEOS_PER_RUN,
    )

    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
