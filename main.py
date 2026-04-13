import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Callable, Dict, Any, Awaitable

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import database as db

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, limit_seconds: int = 2):
        self.limit = limit_seconds
        self.users_time = {}

    async def __call__(self, handler: Callable[[types.Message, Dict[str, Any]], Awaitable[Any]], event: types.Message, data: Dict[str, Any]) -> Any:
        user_id = event.from_user.id
        if user_id in config.ADMINS:
            return await handler(event, data)
        now = time.time()
        last_time = self.users_time.get(user_id, 0)
        if now - last_time < self.limit:
            return
        else:
            self.users_time[user_id] = now
            return await handler(event, data)

# ==========================================
#               HOLATLAR
# ==========================================
class RegState(StatesGroup):
    phone = State()
    name = State()
    group = State()

class AdminState(StatesGroup):
    group_name = State()
    group_days = State()
    group_time = State()
    broadcast_text = State()

class FeedbackState(StatesGroup):
    waiting_for_comment = State() # Izoh kutish holati

# ==========================================
#               TUGMALAR
# ==========================================
admin_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="➕ Yangi guruh yaratish")],
    [KeyboardButton(text="📋 Guruhlarni ko'rish va Boshqarish")],
    [KeyboardButton(text="📢 E'lon yuborish")]
], resize_keyboard=True)

student_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔄 Profilni va Guruhni o'zgartirish")]
], resize_keyboard=True)

# Baholash klaviaturasi (0 dan 10 gacha)
def get_rating_keyboard(group_id):
    builder = InlineKeyboardBuilder()
    for i in range(11): # 0 dan 10 gacha
        builder.button(text=str(i), callback_data=f"rate_{i}_{group_id}")
    builder.adjust(5, 5, 1) # Chiroyli taxlash (5 ta, 5 ta, 1 ta)
    return builder.as_markup()

UZ_DAYS = ["Dush", "Sesh", "Chor", "Pay", "Jum", "Shan", "Yak"]

# ==========================================
#             START KOMANDASI
# ==========================================
@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in config.ADMINS:
        await message.answer("Salom Admin! Boshqaruv paneliga xush kelibsiz.", reply_markup=admin_kb)
        return

    student = db.get_student(message.from_user.id)
    if student:
        await message.answer("Siz allaqachon ro'yxatdan o'tgansiz. Darsingiz tugashini kuting! 😊", reply_markup=student_kb)
    else:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
        await message.answer("Salom! Anonim fikr qoldirish uchun ro'yxatdan o'tishingiz kerak. Raqamingizni yuboring:", reply_markup=kb)
        await state.set_state(RegState.phone)

@dp.message(F.text == "🔄 Profilni va Guruhni o'zgartirish")
async def reset_profile(message: types.Message, state: FSMContext):
    db.delete_student(message.from_user.id)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📞 Raqamni yuborish", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Eski ma'lumotlaringiz o'chirildi. Iltimos, qaytadan raqamingizni yuboring:", reply_markup=kb)
    await state.set_state(RegState.phone)

# ==========================================
#         ADMIN TIZIMI (E'LON VA GURUHLAR)
# ==========================================
@dp.message(F.text == "📢 E'lon yuborish")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMINS: return
    await message.answer("✍️ Barcha o'quvchilarga yuboriladigan xabar matnini kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.broadcast_text)

@dp.message(AdminState.broadcast_text)
async def broadcast_send(message: types.Message, state: FSMContext):
    text = message.text
    students = db.get_all_students()
    if not students:
        await message.answer("⚠️ Hozircha bazada o'quvchi yo'q.", reply_markup=admin_kb)
        await state.clear()
        return

    await message.answer("⏳ E'lon yuborilmoqda...")
    count = 0
    for st in students:
        try:
            await bot.send_message(st[0], f"📢 <b>E'lon:</b>\n\n{text}", parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await message.answer(f"✅ E'lon <b>{count} ta</b> o'quvchiga yetkazildi!", parse_mode="HTML", reply_markup=admin_kb)
    await state.clear()

@dp.message(F.text == "➕ Yangi guruh yaratish")
async def admin_new_group(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMINS: return
    await message.answer("Yangi guruh nomini kiriting:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.group_name)

@dp.message(AdminState.group_name)
async def admin_group_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text, selected_days=[])
    await send_days_keyboard(message, [])
    await state.set_state(AdminState.group_days)

async def send_days_keyboard(message_or_call, selected_days):
    builder = InlineKeyboardBuilder()
    for day in UZ_DAYS:
        text = f"✅ {day}" if day in selected_days else day
        builder.button(text=text, callback_data=f"day_{day}")
    builder.adjust(3, 3, 1)
    builder.row(InlineKeyboardButton(text="💾 Saqlash", callback_data="save_days"))
    text_msg = "Dars kunlarini tanlang va 'Saqlash' ni bosing:"
    if isinstance(message_or_call, types.Message):
        await message_or_call.answer(text_msg, reply_markup=builder.as_markup())
    else:
        try:
            await message_or_call.message.edit_text(text_msg, reply_markup=builder.as_markup())
        except:
            pass

@dp.callback_query(F.data.startswith("day_"), AdminState.group_days)
async def toggle_day(call: types.CallbackQuery, state: FSMContext):
    day = call.data.split("_")[1]
    data = await state.get_data()
    selected = data.get("selected_days", [])
    if day in selected: selected.remove(day)
    else: selected.append(day)
    await state.update_data(selected_days=selected)
    await send_days_keyboard(call, selected)
    await call.answer()

@dp.callback_query(F.data == "save_days", AdminState.group_days)
async def save_days(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected_days"):
        await call.answer("Iltimos, kun tanlang!", show_alert=True)
        return
    days_str = ", ".join(data["selected_days"])
    await state.update_data(final_days=days_str)
    await call.message.edit_text(f"Kunlar: {days_str}\n\nEndi tugash vaqtini kiriting (masalan: 14:30):")
    await state.set_state(AdminState.group_time)

@dp.message(AdminState.group_time)
async def admin_group_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    db.add_group(data['name'], data['final_days'], message.text)
    await message.answer(f"✅ Guruh yaratildi!", reply_markup=admin_kb)
    await state.clear()

@dp.message(F.text == "📋 Guruhlarni ko'rish va Boshqarish")
async def admin_show_groups(message: types.Message):
    if message.from_user.id not in config.ADMINS: return
    groups = db.get_all_groups()
    if not groups:
        await message.answer("Hozircha guruhlar yo'q.", reply_markup=admin_kb)
        return
    await message.answer("Barcha guruhlar ro'yxati:", reply_markup=admin_kb)
    for g in groups:
        builder = InlineKeyboardBuilder()
        builder.button(text="🗑 O'chirish", callback_data=f"del_group_{g[0]}")
        await message.answer(f"🔹 <b>{g[1]}</b>\n📅 {g[2]}\n⏰ {g[3]}", parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_group_"))
async def del_group_handler(call: types.CallbackQuery):
    group_id = int(call.data.split("_")[2])
    db.delete_group(group_id)
    await call.message.edit_text(f"❌ {call.message.text}\n<b>(O'CHIRILDI)</b>", parse_mode="HTML")

# ==========================================
#          O'QUVCHI RO'YXATDAN O'TISHI
# ==========================================
@dp.message(RegState.phone, F.contact)
async def get_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await message.answer("Ismingizni yozib yuboring:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(RegState.name)

@dp.message(RegState.name)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    groups = db.get_groups()
    if not groups:
        await message.answer("Guruhlar yo'q. /start bosib qayta urinib ko'ring.")
        await state.clear()
        return
    kb_buttons = [[KeyboardButton(text=f"Guruh: {g[1]}")] for g in groups]
    kb = ReplyKeyboardMarkup(keyboard=kb_buttons, resize_keyboard=True)
    await message.answer("Qaysi guruhda o'qiysiz?", reply_markup=kb)
    await state.set_state(RegState.group)

@dp.message(RegState.group, F.text.startswith("Guruh: "))
async def get_group(message: types.Message, state: FSMContext):
    group_name = message.text.replace("Guruh: ", "")
    groups = db.get_groups()
    group_id = next((g[0] for g in groups if g[1] == group_name), None)
    if not group_id: return
    data = await state.get_data()
    db.add_student(message.from_user.id, data['name'], data['phone'], group_id)
    await message.answer("🎉 Ro'yxatdan o'tdingiz!", reply_markup=student_kb)
    await state.clear()

# ==========================================
#          AVTOMATIK XABAR VA REYTING
# ==========================================
async def check_classes_and_send():
    now = datetime.now(ZoneInfo("Asia/Tashkent"))
    current_time = now.strftime("%H:%M")
    current_day = UZ_DAYS[now.weekday()]
    
    groups = db.get_all_groups()
    if not groups: return

    for g in groups:
        group_id, nom, kunlar, vaqt = g[0], g[1], g[2], g[3]
        if current_day in kunlar and current_time == vaqt:
            students = db.get_students_by_group(group_id)
            for st in students:
                user_id = st[0]
                try:
                    # YANGA: Endi 0-10 tugmalar jo'natiladi
                    await bot.send_message(
                        user_id, 
                        f"🔔 <b>{nom}</b> guruhi darsi o'z nihoyasiga yetdi!\n\nIltimos, bugungi darsni <b>0 dan 10 gacha</b> bo'lgan shkala bo'yicha baholang:", 
                        parse_mode="HTML",
                        reply_markup=get_rating_keyboard(group_id)
                    )
                except Exception:
                    pass

# 1-qadam: Tugma bosilganda (Baho olinadi)
@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    rating = int(parts[1])
    group_id = int(parts[2])
    
    # Xotiraga saqlaymiz va Izoh kutamiz
    await state.update_data(rating=rating, group_id=group_id)
    
    # Tugmalarni o'chirib, xabarni o'zgartiramiz
    await call.message.delete()
    
    skip_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="➡️ Izohsiz yuborish")]], resize_keyboard=True)
    await bot.send_message(
        call.from_user.id, 
        f"✅ Darsni <b>{rating} ballga</b> baholadingiz.\n\nEndi dars haqida izohingizni yozib yuboring (yoki pastdagi tugmani bosing):", 
        parse_mode="HTML",
        reply_markup=skip_kb
    )
    await state.set_state(FeedbackState.waiting_for_comment)
    await call.answer()

# 2-qadam: Izoh kelganda (Adminlarga jo'natiladi)
@dp.message(FeedbackState.waiting_for_comment)
async def process_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    group_id = data.get('group_id')
    rating = data.get('rating')
    
    if message.text == "➡️ Izohsiz yuborish":
        comment = "Izoh qoldirilmadi."
    else:
        comment = message.text

    groups = db.get_groups()
    group_name = next((g[1] for g in groups if g[0] == group_id), "Noma'lum guruh")
    
    db.add_feedback(group_id, rating, comment)
    
    admin_text = f"📩 <b>Yangi anonim fikr!</b>\n\n👥 Guruh: {group_name}\n⭐️ Baho: {rating} / 10\n💬 Fikr: {comment}"
    for admin_id in config.ADMINS:
        try:
            await bot.send_message(admin_id, admin_text, parse_mode="HTML")
        except:
            pass
            
    await message.answer("✅ Fikringiz va bahoingiz qabul qilindi. Katta rahmat!", reply_markup=student_kb)
    await state.clear()

# ==========================================
#     TUTIB OLUVCHI (Agar bot adashib qolsa)
# ==========================================
@dp.message()
async def handle_all_messages(message: types.Message, state: FSMContext):
    if message.text in ["➕ Yangi guruh yaratish", "📋 Guruhlarni ko'rish va Boshqarish", "🔄 Profilni va Guruhni o'zgartirish", "📢 E'lon yuborish"]: return

    student = db.get_student(message.from_user.id)
    if not student and message.from_user.id not in config.ADMINS:
        await message.answer("Siz ro'yxatdan o'tmagansiz. Iltimos, /start tugmasini bosing.")

# ==========================================
#             ASOSIY FUNKSIYA
# ==========================================
async def main():
    db.create_tables()
    dp.message.middleware(AntiSpamMiddleware(limit_seconds=2))
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(check_classes_and_send, 'cron', minute='*')
    scheduler.start()
    
    print("🚀 Bot ishga tushdi!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())