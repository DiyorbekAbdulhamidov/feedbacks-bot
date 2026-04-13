import asyncio
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Callable, Dict, Any, Awaitable

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import database as db

bot = Bot(token=config.BOT_TOKEN)
dp  = Dispatcher()

TZ       = ZoneInfo("Asia/Tashkent")
UZ_DAYS  = ["Dush", "Sesh", "Chor", "Pay", "Jum", "Shan", "Yak"]
TIME_RE  = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")   # HH:MM validatsiya


# ==========================================
#         ANTI-SPAM MIDDLEWARE
# ==========================================
class AntiSpamMiddleware(BaseMiddleware):
    """Message va Callback uchun ham ishlaydi."""

    def __init__(self, limit_seconds: float = 1.5):
        self.limit      = limit_seconds
        self.users_time: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        # user_id ni xavfsiz olish
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        uid = user.id
        if uid in config.ADMINS:
            return await handler(event, data)

        now  = time.monotonic()
        last = self.users_time.get(uid, 0.0)
        if now - last < self.limit:
            # callback uchun "please wait" javobi
            if isinstance(event, types.CallbackQuery):
                await event.answer("⏳ Biroz kuting...", show_alert=False)
            return  # message uchun shunchaki e'tiborsiz
        self.users_time[uid] = now
        return await handler(event, data)


# ==========================================
#               HOLATLAR
# ==========================================
class RegState(StatesGroup):
    phone = State()
    name  = State()
    group = State()

class AdminState(StatesGroup):
    group_name        = State()
    group_days        = State()
    group_time        = State()
    broadcast_type    = State()
    broadcast_group_id = State()
    broadcast_text    = State()

class FeedbackState(StatesGroup):
    waiting_for_comment = State()


# ==========================================
#            KLAVIATURALAR
# ==========================================
admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Yangi guruh yaratish")],
        [KeyboardButton(text="📋 Guruhlar Boshqaruvi")],
        [KeyboardButton(text="📊 Statistika")],
        [KeyboardButton(text="📢 Xabar yuborish")],
    ],
    resize_keyboard=True,
)

student_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔄 Profilni o'zgartirish")]],
    resize_keyboard=True,
)


# ==========================================
#           YORDAMCHI FUNKSIYALAR
# ==========================================
def _days_kb(selected: list[str]) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in UZ_DAYS:
        txt = f"✅ {d}" if d in selected else d
        builder.button(text=txt, callback_data=f"day_{d}")
    builder.row(InlineKeyboardButton(text="💾 Saqlash", callback_data="save_days"))
    return builder.as_markup()


async def _notify_admins(text: str):
    for adm in config.ADMINS:
        try:
            await bot.send_message(adm, text, parse_mode="HTML")
        except Exception:
            pass


# ==========================================
#             START KOMANDASI
# ==========================================
@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()

    if message.from_user.id in config.ADMINS:
        await message.answer("Xush kelibsiz, Admin! 👋", reply_markup=admin_kb)
        return

    student = db.get_student(message.from_user.id)
    if student:
        await message.answer("Siz ro'yxatdan o'tgansiz! 😊", reply_markup=student_kb)
        return

    groups = db.get_groups()
    if not groups:
        await message.answer(
            "⚠️ Hozircha guruhlar mavjud emas.\n"
            "Iltimos, keyinroq qayta urinib ko'ring."
        )
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Raqam yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Salom! Ro'yxatdan o'tish uchun raqamingizni yuboring:",
        reply_markup=kb,
    )
    await state.set_state(RegState.phone)


@dp.message(F.text == "🔄 Profilni o'zgartirish")
async def reset_profile(message: types.Message, state: FSMContext):
    db.delete_student(message.from_user.id)
    await start_cmd(message, state)


# ==========================================
#       ADMIN: STATISTIKA
# ==========================================
@dp.message(F.text == "📊 Statistika")
async def show_stats(message: types.Message):
    if message.from_user.id not in config.ADMINS:
        return

    data   = db.get_global_stats()
    groups = data["groups"]        # (nom, jami_feedback, ortacha_baho)

    if not groups:
        await message.answer("Hali ma'lumotlar yo'q.")
        return

    lines = [f"📊 <b>Umumiy statistika</b>\n👥 Jami o'quvchilar: <b>{data['total_students']}</b>\n"]
    for g in groups:
        nom, jami, avg = g
        avg_str = f"{avg:.1f}" if avg else "—"
        lines.append(f"🔹 <b>{nom}</b>\n   Fikrlar: {jami} | O'rtacha: ⭐ {avg_str}/10\n")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.callback_query(F.data.startswith("stats_gr_"))
async def group_stats_detail(call: types.CallbackQuery):
    group_id = int(call.data.split("_")[2])
    stats    = db.get_feedback_stats(group_id)

    msg = (
        f"📊 <b>Guruh statistikasi</b>\n\n"
        f"Jami fikr: <b>{stats['count']}</b>\n"
        f"O'rtacha baho: <b>⭐ {stats['avg']}/10</b>\n\n"
    )
    if stats["last"]:
        msg += "🕐 <b>So'nggi fikrlar:</b>\n"
        for sana, baho, matn in stats["last"]:
            msg += f"• {sana} — {baho}/10 — {matn or '—'}\n"

    await call.message.answer(msg, parse_mode="HTML")
    await call.answer()


# ==========================================
#       ADMIN: XABAR YUBORISH
# ==========================================
@dp.message(F.text == "📢 Xabar yuborish")
async def broadcast_choice(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMINS:
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="🌍 Hammaga", callback_data="bc_all")
    builder.button(text="👥 Guruhga", callback_data="bc_group")
    await message.answer("Xabar kimlarga yuborilsin?", reply_markup=builder.as_markup())
    await state.set_state(AdminState.broadcast_type)


@dp.callback_query(F.data == "bc_all", AdminState.broadcast_type)
async def bc_all_selected(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(target="all")
    await call.message.edit_text("✍️ Barcha o'quvchilarga yuboriladigan xabarni yozing:")
    await state.set_state(AdminState.broadcast_text)
    await call.answer()


@dp.callback_query(F.data == "bc_group", AdminState.broadcast_type)
async def bc_group_selected(call: types.CallbackQuery, state: FSMContext):
    groups = db.get_groups()
    if not groups:
        await call.answer("Hali guruhlar yo'q!", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for g in groups:
        builder.button(text=g[1], callback_data=f"bcgroupid_{g[0]}")
    builder.adjust(1)
    await call.message.edit_text(
        "Qaysi guruhga xabar yubormoqchisiz?",
        reply_markup=builder.as_markup(),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("bcgroupid_"), AdminState.broadcast_type)
async def bc_group_id_selected(call: types.CallbackQuery, state: FSMContext):
    group_id = int(call.data.split("_")[1])
    await state.update_data(target="group", group_id=group_id)
    await call.message.edit_text("✍️ Ushbu guruh o'quvchilariga yuboriladigan xabarni yozing:")
    await state.set_state(AdminState.broadcast_text)
    await call.answer()


@dp.message(AdminState.broadcast_text)
async def bc_final_send(message: types.Message, state: FSMContext):
    data = await state.get_data()

    # Admin matn o'rniga rasm/stiker yuborsa — rad etish
    if not message.text:
        await message.answer("❌ Faqat matn xabar yuborish mumkin. Qaytadan yozing:")
        return

    # target yo'q bo'lsa — xavfsiz qaytish
    target = data.get("target")
    if not target:
        await message.answer("❌ Xatolik. Qaytadan boshlang.", reply_markup=admin_kb)
        await state.clear()
        return

    if target == "all":
        targets = db.get_all_students()
        header  = "🌍 <b>Umumiy e'lon:</b>"
    else:
        group_id = data.get("group_id")
        if group_id is None:
            await message.answer("❌ Guruh tanlanmagan.", reply_markup=admin_kb)
            await state.clear()
            return
        targets = db.get_students_by_group(group_id)
        header  = "📢 <b>Guruh uchun e'lon:</b>"

    await message.answer("🚀 Yuborilmoqda...")
    count = 0
    for t in targets:
        try:
            await bot.send_message(
                t[0],
                f"{header}\n\n{message.text}",
                parse_mode="HTML",
            )
            count += 1
            await asyncio.sleep(0.05)   # Telegram rate-limit
        except Exception:
            pass

    await message.answer(f"✅ {count} ta foydalanuvchiga yetkazildi.", reply_markup=admin_kb)
    await state.clear()


# ==========================================
#       ADMIN: GURUHLAR BOSHQARUVI
# ==========================================
@dp.message(F.text == "📋 Guruhlar Boshqaruvi")
async def admin_manage_groups(message: types.Message):
    if message.from_user.id not in config.ADMINS:
        return

    groups = db.get_all_groups()
    if not groups:
        await message.answer("Guruhlar mavjud emas.")
        return

    for g in groups:
        builder = InlineKeyboardBuilder()
        builder.button(text="👥 O'quvchilar",  callback_data=f"list_st_{g[0]}")
        builder.button(text="📊 Statistika",   callback_data=f"stats_gr_{g[0]}")
        builder.button(text="🗑 O'chirish",    callback_data=f"del_gr_{g[0]}")
        builder.adjust(2, 1)
        await message.answer(
            f"🔹 <b>{g[1]}</b>\n📅 {g[2]} | ⏰ {g[3]}",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )


@dp.callback_query(F.data.startswith("list_st_"))
async def show_students(call: types.CallbackQuery):
    group_id = int(call.data.split("_")[2])
    students = db.get_students_list(group_id)

    if not students:
        await call.answer("Bu guruhda o'quvchilar yo'q.", show_alert=True)
        return

    lines = ["👥 <b>Guruh o'quvchilari:</b>\n"]
    for i, (ism, telefon) in enumerate(students, 1):
        lines.append(f"{i}. {ism} — <code>{telefon}</code>")

    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data.startswith("del_gr_"))
async def delete_group_call(call: types.CallbackQuery):
    group_id = int(call.data.split("_")[2])
    db.delete_group(group_id)
    await call.message.edit_text("❌ Guruh va unga tegishli barcha ma'lumotlar o'chirildi.")


# ==========================================
#       ADMIN: YANGI GURUH QO'SHISH
# ==========================================
@dp.message(F.text == "➕ Yangi guruh yaratish")
async def admin_new_group(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMINS:
        return
    await message.answer("Guruh nomini kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.group_name)


@dp.message(AdminState.group_name)
async def group_name_set(message: types.Message, state: FSMContext):
    # Rasm/stiker yuborilsa message.text = None → AttributeError oldini olish
    name = (message.text or "").strip()
    if not name:
        await message.answer("❌ Nom matn bo'lishi kerak. Qaytadan kiriting:")
        return
    await state.update_data(name=name, selected_days=[])
    await message.answer("Dars kunlarini tanlang:", reply_markup=_days_kb([]))
    await state.set_state(AdminState.group_days)


@dp.callback_query(F.data.startswith("day_"), AdminState.group_days)
async def toggle_day(call: types.CallbackQuery, state: FSMContext):
    day  = call.data[4:]   # "day_" dan keyingi qism
    data = await state.get_data()
    days: list = data.get("selected_days", [])

    if day in days:
        days.remove(day)
    else:
        days.append(day)

    await state.update_data(selected_days=days)
    await call.message.edit_reply_markup(reply_markup=_days_kb(days))
    await call.answer()


@dp.callback_query(F.data == "save_days", AdminState.group_days)
async def save_days(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected_days"):
        await call.answer("⚠️ Kamida bitta kun tanlang!", show_alert=True)
        return
    await call.message.edit_text("⏰ Dars vaqtini kiriting (HH:MM, masalan: 09:30):")
    await state.set_state(AdminState.group_time)
    await call.answer()


@dp.message(AdminState.group_time)
async def group_time_set(message: types.Message, state: FSMContext):
    # Rasm/stiker yuborilsa message.text = None → xavfsiz olish
    vaqt = (message.text or "").strip()

    # ✅ Format validatsiyasi
    if not TIME_RE.match(vaqt):
        await message.answer(
            "❌ Noto'g'ri format! HH:MM ko'rinishida kiriting.\n"
            "Masalan: <code>09:30</code> yoki <code>18:00</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    db.add_group(data["name"], ", ".join(data["selected_days"]), vaqt)
    await message.answer(
        f"✅ <b>{data['name']}</b> guruhi yaratildi!\n"
        f"📅 {', '.join(data['selected_days'])} | ⏰ {vaqt}",
        parse_mode="HTML",
        reply_markup=admin_kb,
    )
    await state.clear()


# ==========================================
#        O'QUVCHI RO'YXATDAN O'TISHI
# ==========================================
@dp.message(RegState.phone, F.contact)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await message.answer("✍️ Ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(RegState.name)


@dp.message(RegState.phone)
async def reg_phone_wrong(message: types.Message):
    """Foydalanuvchi kontakt o'rniga matn yuborganda."""
    await message.answer("📞 Iltimos, tugma orqali raqamingizni yuboring.")


@dp.message(RegState.name)
async def reg_name(message: types.Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("❌ Ism bo'sh bo'lishi mumkin emas.")
        return

    await state.update_data(name=name)
    groups = db.get_groups()

    if not groups:
        await message.answer(
            "⚠️ Hozircha guruhlar mavjud emas. Admin guruh qo'shishini kuting."
        )
        await state.clear()
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=f"G: {g[1]}")] for g in groups],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer("Guruhingizni tanlang:", reply_markup=kb)
    await state.set_state(RegState.group)


@dp.message(RegState.group, F.text.startswith("G: "))
async def reg_final(message: types.Message, state: FSMContext):
    g_name = message.text[3:]   # "G: " dan keyingisi
    groups = db.get_groups()
    g_id   = next((g[0] for g in groups if g[1] == g_name), None)

    if g_id is None:
        await message.answer("❌ Guruh topilmadi. Qaytadan tanlang.")
        return

    data = await state.get_data()
    db.add_student(message.from_user.id, data["name"], data["phone"], g_id)
    await message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n"
        f"👤 {data['name']} | 👥 {g_name}",
        reply_markup=student_kb,
    )
    await state.clear()


@dp.message(RegState.group)
async def reg_group_wrong(message: types.Message):
    await message.answer("⚠️ Iltimos, ro'yxatdan guruhni tanlang.")


# ==========================================
#          BAHOLASH VA FIKR
# ==========================================
async def check_timer():
    now = datetime.now(TZ)
    cur_time = now.strftime("%H:%M")
    cur_day  = UZ_DAYS[now.weekday()]

    for g in db.get_all_groups():
        gid, nom, kunlar, vaqt = g
        if cur_day not in kunlar or cur_time != vaqt:
            continue

        students = db.get_students_by_group(gid)
        if not students:
            continue

        builder = InlineKeyboardBuilder()
        for i in range(11):
            builder.button(text=str(i), callback_data=f"r_{i}_{gid}")
        builder.adjust(5, 5, 1)
        markup = builder.as_markup()

        for (uid,) in students:
            try:
                await bot.send_message(
                    uid,
                    f"🔔 <b>{nom}</b> darsi tugadi!\n\nDarsni qanday baholaysiz? (0–10)",
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            except Exception:
                pass


@dp.callback_query(F.data.startswith("r_"))
async def rate_clicked(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")        # ["r", "val", "gid"]
    val   = parts[1]
    gid   = parts[2]

    await state.update_data(rating=val, group_id=gid)
    await call.message.delete()

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="➡️ Izohsiz")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await bot.send_message(
        call.from_user.id,
        f"⭐ {val}/10 tanladingiz.\n\nIzoh qoldirmoqchimisiz?",
        reply_markup=kb,
    )
    await state.set_state(FeedbackState.waiting_for_comment)
    await call.answer()


@dp.message(FeedbackState.waiting_for_comment)
async def comment_received(message: types.Message, state: FSMContext):
    data    = await state.get_data()
    rating  = data.get("rating", "0")
    gid     = data.get("group_id")
    comment = "Yo'q" if message.text == "➡️ Izohsiz" else (message.text or "Yo'q")

    if gid:
        db.add_feedback(gid, int(rating), comment)

    # Guruh nomini topish
    g_name = next(
        (g[1] for g in db.get_groups() if str(g[0]) == str(gid)),
        "Noma'lum",
    )
    await _notify_admins(
        f"📩 <b>Yangi fikr!</b>\n"
        f"👥 Guruh: {g_name}\n"
        f"⭐ Baho: {rating}/10\n"
        f"💬 Izoh: {comment}"
    )

    await message.answer("✅ Rahmat, fikringiz qabul qilindi!", reply_markup=student_kb)
    await state.clear()


# ==========================================
#        NOMA'LUM XABARLAR (FALLBACK)
# ==========================================
@dp.message()
async def all_msg(message: types.Message, state: FSMContext):
    # Faol holat bo'lsa — bu handler ushlamasligi kerak,
    # lekin ehtiyot uchun tekshiramiz
    current_state = await state.get_state()
    if current_state is not None:
        return

    # Faqat ro'yxatdan o'tgan o'quvchilarning xabarlarini adminga yo'naltiramiz
    st = db.get_student(message.from_user.id)
    if st and message.from_user.id not in config.ADMINS:
        g_name = next(
            (g[1] for g in db.get_groups() if g[0] == st[3]),
            "Noma'lum",
        )
        await _notify_admins(
            f"📩 <b>O'quvchidan xabar:</b>\n"
            f"👤 {st[1]} | 👥 {g_name}\n"
            f"💬 {message.text}"
        )
        await message.answer("✉️ Xabaringiz adminga yuborildi.")
    elif message.from_user.id not in config.ADMINS:
        await message.answer(
            "Salom! Ro'yxatdan o'tish uchun /start ni bosing."
        )


# ==========================================
#                MAIN
# ==========================================
async def main():
    db.create_tables()

    # Middleware — ham message, ham callback uchun
    dp.message.middleware(AntiSpamMiddleware())
    dp.callback_query.middleware(AntiSpamMiddleware())

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(check_timer, "cron", minute="*")
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())