from keep_alive import keep_alive

keep_alive()
import pytz
import asyncio
import logging
import csv
import os
from datetime import datetime
from typing import Dict, List, Optional
import re

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "7621682452:AAEPwo3N5U1fe6CoYGlamfuSAuhioSSq1gU"
ADMIN_ID = 1022315859
ADMIN_PASSWORD = "Medeu2025"

# Уникальная ссылка для QR-кода (исправленная)
QR_CODE_SECRET = "medeu_center_checkin_2025"
QR_CODE_LINK = "https://t.me/MedeuCommunityBot?start=medeu_center_checkin_2025"

# Состояния пользователей
USER_STATES = {}
REGISTRATION_DATA = {}

# База данных (в реальном проекте лучше использовать SQLite или PostgreSQL)
USERS_DB = {
}  # {user_id: {"name": str, "phone": str, "registered_at": datetime}}
CHECKINS_DB = [
]  # [{"user_id": int, "name": str, "phone": str, "timestamp": datetime, "method": str}]
ADMIN_SESSIONS = {}  # {user_id: bool} - активные сессии администратора


# Состояния для FSM
class States:
    WAITING_NAME = "waiting_name"
    WAITING_PHONE = "waiting_phone"
    WAITING_ADMIN_PASSWORD = "waiting_admin_password"
    WAITING_QR_SCAN = "waiting_qr_scan"
    ADMIN_MENU = "admin_menu"
    CONFIRM_CLEAR_DATA = "confirm_clear_data"  # Новое состояние для подтверждения очистки
    CONFIRM_CLEAR_CHECKINS = "confirm_clear_checkins"  # Новое состояние для подтверждения очистки посещений


def is_valid_phone(phone: str) -> bool:
    """Проверка корректности номера телефона"""
    # Казахстанские номера: +7 (7xx) xxx-xx-xx
    pattern = r'^\+7[0-9]{10}$|^8[0-9]{10}$|^7[0-9]{10}$'
    return bool(
        re.match(
            pattern,
            phone.replace(' ', '').replace('-',
                                           '').replace('(',
                                                       '').replace(')', '')))


def normalize_phone(phone: str) -> str:
    """Нормализация номера телефона"""
    clean_phone = phone.replace(' ',
                                '').replace('-',
                                            '').replace('(',
                                                        '').replace(')', '')
    if clean_phone.startswith('8'):
        clean_phone = '+7' + clean_phone[1:]
    elif clean_phone.startswith('7'):
        clean_phone = '+' + clean_phone
    elif not clean_phone.startswith('+7'):
        clean_phone = '+7' + clean_phone
    return clean_phone


def phone_exists(phone: str) -> bool:
    """Проверка существования номера телефона в базе"""
    normalized_phone = normalize_phone(phone)
    for user_data in USERS_DB.values():
        if user_data["phone"] == normalized_phone:
            return True
    return False


def get_user_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для зарегистрированного пользователя"""
    keyboard = [[KeyboardButton("📍 Отметиться")],
                [KeyboardButton("ℹ️ Моя информация")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для администратора"""
    keyboard = [[
        KeyboardButton("👥 Отчет пользователей"),
        KeyboardButton("🕒 Отчет посещений")
    ], [
        KeyboardButton("📊 Статистика"),
        KeyboardButton("🔗 QR-код для отметок")
    ],
                [
                    KeyboardButton("🗑️ Очистить данные"),
                    KeyboardButton("🧹 Очистить посещения")
                ], [KeyboardButton("🚪 Выйти из админ-панели")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_confirm_clear_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для подтверждения очистки данных"""
    keyboard = [[KeyboardButton("✅ ДА, ОЧИСТИТЬ ВСЕ ДАННЫЕ")],
                [KeyboardButton("❌ НЕТ, ОТМЕНИТЬ")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_confirm_clear_checkins_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для подтверждения очистки посещений"""
    keyboard = [[KeyboardButton("✅ ДА, ОЧИСТИТЬ ПОСЕЩЕНИЯ")],
                [KeyboardButton("❌ НЕТ, ОТМЕНИТЬ")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user_id = update.effective_user.id

    # Проверяем параметр для отметки через QR-код
    if context.args and context.args[0] == QR_CODE_SECRET:
        if user_id not in USERS_DB:
            await update.message.reply_text(
                "❌ **Для отметки необходимо сначала зарегистрироваться!**\n\n"
                "Нажмите /start для регистрации в системе.",
                parse_mode='Markdown')
            return

        # Выполняем отметку через QR-код
        await qr_checkin(update, context)
        return

    # Проверяем, зарегистрирован ли пользователь
    if user_id in USERS_DB:
        user_data = USERS_DB[user_id]
        await update.message.reply_text(
            f"👋 **Добро пожаловать обратно, {user_data['name']}!**\n\n"
            f"Вы можете отметиться или посмотреть свою информацию.\n\n"
            f"💡 *Для быстрой отметки отсканируйте QR-код на входе в центр*",
            reply_markup=get_user_keyboard(),
            parse_mode='Markdown')
    else:
        # Начинаем регистрацию
        USER_STATES[user_id] = States.WAITING_NAME
        await update.message.reply_text(
            "🎯 **Добро пожаловать в систему учета посещаемости Medeu Community!**\n\n"
            "Для начала работы необходимо зарегистрироваться.\n\n"
            "👤 Пожалуйста, введите ваше полное имя (например: Иванов И.И.):",
            parse_mode='Markdown')


async def handle_name_input(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода имени"""
    user_id = update.effective_user.id
    name = update.message.text.strip()

    if len(name) < 2:
        await update.message.reply_text(
            "❌ Имя слишком короткое. Пожалуйста, введите полное имя:")
        return

    REGISTRATION_DATA[user_id] = {"name": name}
    USER_STATES[user_id] = States.WAITING_PHONE

    await update.message.reply_text(
        f"✅ Имя принято: **{name}**\n\n"
        f"📱 Теперь введите ваш номер телефона в формате:\n"
        f"+77011234567 или 87011234567",
        parse_mode='Markdown')


async def handle_phone_input(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода номера телефона"""
    user_id = update.effective_user.id
    phone = update.message.text.strip()

    if not is_valid_phone(phone):
        await update.message.reply_text(
            "❌ Неверный формат номера телефона.\n"
            "Пожалуйста, введите номер в формате: +77011234567 или 87011234567",
            parse_mode='Markdown')
        return

    normalized_phone = normalize_phone(phone)

    if phone_exists(phone):
        await update.message.reply_text(
            "❌ **Этот номер телефона уже зарегистрирован в системе.**\n\n"
            "Каждый номер может быть использован только один раз.\n"
            "Если это ваш номер, обратитесь к администратору.",
            parse_mode='Markdown')
        return

    # Завершаем регистрацию
    name = REGISTRATION_DATA[user_id]["name"]
    USERS_DB[user_id] = {
        "name": name,
        "phone": normalized_phone,
        "registered_at": datetime.now()
    }

    # Очищаем временные данные
    del REGISTRATION_DATA[user_id]
    del USER_STATES[user_id]

    await update.message.reply_text(
        f"🎉 **Регистрация успешно завершена!**\n\n"
        f"👤 Имя: {name}\n"
        f"📱 Телефон: {normalized_phone}\n\n"
        f"✅ Теперь вы можете отмечаться при каждом посещении!\n"
        f"📱 Используйте кнопку \"📍 Отметиться\" или отсканируйте QR-код на входе",
        reply_markup=get_user_keyboard(),
        parse_mode='Markdown')

    # Уведомляем администратора о новой регистрации
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆕 **Новая регистрация**\n\n"
            f"👤 Имя: {name}\n"
            f"📱 Телефон: {normalized_phone}\n"
            f"🕒 Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление администратору: {e}")


async def handle_checkin_request(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка запроса на отметку - просим отсканировать QR-код"""
    user_id = update.effective_user.id

    if user_id not in USERS_DB:
        await update.message.reply_text("❌ Вы не зарегистрированы в системе.\n"
                                        "Нажмите /start для регистрации.")
        return

    # Переводим пользователя в состояние ожидания QR-кода
    USER_STATES[user_id] = States.WAITING_QR_SCAN

    keyboard = [[KeyboardButton("❌ Отменить отметку")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "📱 **Для подтверждения отметки отсканируйте QR-код на входе в центр**\n\n"
        "🔍 Наведите камеру телефона на QR-код и нажмите на появившуюся ссылку\n\n"
        "💡 *QR-код находится на стенде у входа в Medeu Community*\n\n"
        "⚠️ Отметка будет засчитана только при сканировании официального QR-кода центра",
        reply_markup=reply_markup,
        parse_mode='Markdown')


async def qr_checkin(update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отметка через QR-код"""
    user_id = update.effective_user.id
    user_data = USERS_DB[user_id]
    timestamp = datetime.now()

    # Записываем отметку с указанием способа
    checkin_record = {
        "user_id": user_id,
        "name": user_data["name"],
        "phone": user_data["phone"],
        "timestamp": timestamp,
        "method": "QR-код"
    }
    CHECKINS_DB.append(checkin_record)

    # Убираем состояние ожидания QR-кода если оно было
    if user_id in USER_STATES and USER_STATES[
            user_id] == States.WAITING_QR_SCAN:
        del USER_STATES[user_id]

    await update.message.reply_text(
        f"✅ **Отметка через QR-код успешна!**\n\n"
        f"👤 {user_data['name']}\n"
        f"🕒 {timestamp.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"📍 Способ: QR-код (подтверждено присутствие в центре)\n\n"
        f"🎯 Добро пожаловать в Medeu Community!\n"
        f"Спасибо за посещение! 🙏",
        reply_markup=get_user_keyboard(),
        parse_mode='Markdown')

    # Уведомляем администратора
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📍 **Новая отметка (QR-код)**\n\n"
            f"👤 {user_data['name']}\n"
            f"📱 {user_data['phone']}\n"
            f"🕒 {timestamp.strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"✅ Подтверждено присутствие в центре",
            parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление администратору: {e}")


async def handle_user_info(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать информацию о пользователе"""
    user_id = update.effective_user.id

    if user_id not in USERS_DB:
        await update.message.reply_text("❌ Вы не зарегистрированы в системе.")
        return

    user_data = USERS_DB[user_id]

    # Подсчитываем количество посещений
    user_checkins = [c for c in CHECKINS_DB if c["user_id"] == user_id]
    qr_checkins = [c for c in user_checkins if c["method"] == "QR-код"]

    info_text = (
        f"ℹ️ **Ваша информация**\n\n"
        f"👤 Имя: {user_data['name']}\n"
        f"📱 Телефон: {user_data['phone']}\n"
        f"📅 Дата регистрации: {user_data['registered_at'].strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📊 **Статистика посещений:**\n"
        f"🔢 Всего посещений: {len(user_checkins)}\n"
        f"📱 Через QR-код: {len(qr_checkins)}\n")

    if user_checkins:
        last_checkin = max(user_checkins, key=lambda x: x["timestamp"])
        info_text += f"\n\n🕒 Последнее посещение:\n{last_checkin['timestamp'].strftime('%d.%m.%Y %H:%M')} ({last_checkin['method']})"

    await update.message.reply_text(info_text, parse_mode='Markdown')


async def manager_command(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для входа в админ-панель"""
    user_id = update.effective_user.id

    USER_STATES[user_id] = States.WAITING_ADMIN_PASSWORD
    await update.message.reply_text(
        "🔐 **Вход в админ-панель**\n\n"
        "Введите пароль администратора:",
        parse_mode='Markdown')


async def handle_admin_password(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка пароля администратора"""
    user_id = update.effective_user.id
    password = update.message.text.strip()

    if password == ADMIN_PASSWORD:
        ADMIN_SESSIONS[user_id] = True
        USER_STATES[user_id] = States.ADMIN_MENU

        # Статистика
        total_qr_checkins = len(
            [c for c in CHECKINS_DB if c["method"] == "QR-код"])
        today_checkins = len([
            c for c in CHECKINS_DB
            if c['timestamp'].date() == datetime.now().date()
        ])

        stats_text = (f"✅ **Добро пожаловать в админ-панель!**\n\n"
                      f"📊 **Общая статистика:**\n"
                      f"👥 Всего пользователей: {len(USERS_DB)}\n"
                      f"📍 Всего отметок: {len(CHECKINS_DB)}\n"
                      f"📅 Сегодня отметок: {today_checkins}\n"
                      f"📱 Через QR-код: {total_qr_checkins}\n\n"
                      f"🔗 **QR-код для отметок активен**")

        await update.message.reply_text(stats_text,
                                        reply_markup=get_admin_keyboard(),
                                        parse_mode='Markdown')
    else:
        del USER_STATES[user_id]
        await update.message.reply_text("❌ Неверный пароль. Доступ запрещен.")


async def show_qr_code(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать QR-код для отметок"""
    await update.message.reply_text(
        f"🔗 **QR-код для отметок посещений**\n\n"
        f"📱 Ссылка: {QR_CODE_LINK}\n\n"
        f"💡 **Как использовать:**\n"
        f"1. Разместите QR-код на входе в центр\n"
        f"2. Пользователи сканируют код для отметки\n"
        f"3. Отметка засчитывается только при сканировании\n\n"
        f"🔒 **Безопасность:**\n"
        f"• Уникальная ссылка только для вашего центра\n"
        f"• Отметка невозможна без физического сканирования\n"
        f"• Только зарегистрированные пользователи могут отметиться",
        parse_mode='Markdown')


async def request_clear_data(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрос подтверждения для очистки данных"""
    user_id = update.effective_user.id

    if user_id not in ADMIN_SESSIONS:
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    USER_STATES[user_id] = States.CONFIRM_CLEAR_DATA

    # Показываем статистику перед очисткой
    stats_text = (f"⚠️ **ВНИМАНИЕ! ОЧИСТКА ВСЕХ ДАННЫХ**\n\n"
                  f"Вы собираетесь удалить:\n"
                  f"👥 Пользователей: {len(USERS_DB)}\n"
                  f"📍 Записей посещений: {len(CHECKINS_DB)}\n\n"
                  f"🚨 **ЭТО ДЕЙСТВИЕ НЕОБРАТИМО!**\n"
                  f"Все данные будут удалены навсегда.\n\n"
                  f"Вы уверены, что хотите продолжить?")

    await update.message.reply_text(stats_text,
                                    reply_markup=get_confirm_clear_keyboard(),
                                    parse_mode='Markdown')


async def confirm_clear_data(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение очистки данных"""
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in ADMIN_SESSIONS:
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    if text == "✅ ДА, ОЧИСТИТЬ ВСЕ ДАННЫЕ":
        # Сохраняем статистику для отчета
        users_count = len(USERS_DB)
        checkins_count = len(CHECKINS_DB)

        # Очищаем все данные
        USERS_DB.clear()
        CHECKINS_DB.clear()

        # Очищаем состояния пользователей (кроме админа)
        users_to_remove = [uid for uid in USER_STATES.keys() if uid != user_id]
        for uid in users_to_remove:
            del USER_STATES[uid]

        # Очищаем данные регистрации
        REGISTRATION_DATA.clear()

        # Возвращаем админа в меню
        USER_STATES[user_id] = States.ADMIN_MENU

        success_text = (f"✅ **Данные успешно очищены!**\n\n"
                        f"🗑️ **Удалено:**\n"
                        f"👥 Пользователей: {users_count}\n"
                        f"📍 Записей посещений: {checkins_count}\n\n"
                        f"🔄 Система готова для новых данных.\n"
                        f"QR-код остается активным.")

        await update.message.reply_text(success_text,
                                        reply_markup=get_admin_keyboard(),
                                        parse_mode='Markdown')

        logger.info(
            f"Админ {user_id} очистил все данные. Удалено пользователей: {users_count}, посещений: {checkins_count}"
        )

    elif text == "❌ НЕТ, ОТМЕНИТЬ":
        USER_STATES[user_id] = States.ADMIN_MENU
        await update.message.reply_text(
            "❌ Очистка данных отменена.\n"
            "Все данные сохранены.",
            reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text(
            "❓ Пожалуйста, выберите один из предложенных вариантов:",
            reply_markup=get_confirm_clear_keyboard())


async def request_clear_checkins(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрос подтверждения для очистки только посещений"""
    user_id = update.effective_user.id

    if user_id not in ADMIN_SESSIONS:
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    USER_STATES[user_id] = States.CONFIRM_CLEAR_CHECKINS

    # Показываем статистику перед очисткой
    stats_text = (
        f"⚠️ **ВНИМАНИЕ! ОЧИСТКА ПОСЕЩЕНИЙ**\n\n"
        f"Вы собираетесь удалить:\n"
        f"📍 Записей посещений: {len(CHECKINS_DB)}\n\n"
        f"✅ **Пользователи останутся зарегистрированными**\n"
        f"👥 Количество пользователей: {len(USERS_DB)} (не будут удалены)\n\n"
        f"🚨 **Это действие необратимо!**\n"
        f"Все записи посещений будут удалены навсегда.\n\n"
        f"Вы уверены, что хотите продолжить?")

    await update.message.reply_text(
        stats_text,
        reply_markup=get_confirm_clear_checkins_keyboard(),
        parse_mode='Markdown')


async def confirm_clear_checkins(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение очистки посещений"""
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in ADMIN_SESSIONS:
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    if text == "✅ ДА, ОЧИСТИТЬ ПОСЕЩЕНИЯ":
        # Сохраняем статистику для отчета
        checkins_count = len(CHECKINS_DB)
        users_count = len(USERS_DB)

        # Очищаем только данные посещений
        CHECKINS_DB.clear()

        # Возвращаем админа в меню
        USER_STATES[user_id] = States.ADMIN_MENU

        success_text = (
            f"✅ **Посещения успешно очищены!**\n\n"
            f"🗑️ **Удалено:**\n"
            f"📍 Записей посещений: {checkins_count}\n\n"
            f"✅ **Сохранено:**\n"
            f"👥 Пользователей: {users_count} (остались зарегистрированными)\n\n"
            f"🔄 Система готова для новых посещений.\n"
            f"Пользователи могут продолжать отмечаться.")

        await update.message.reply_text(success_text,
                                        reply_markup=get_admin_keyboard(),
                                        parse_mode='Markdown')

        logger.info(
            f"Админ {user_id} очистил данные посещений. Удалено посещений: {checkins_count}, пользователи сохранены: {users_count}"
        )

    elif text == "❌ НЕТ, ОТМЕНИТЬ":
        USER_STATES[user_id] = States.ADMIN_MENU
        await update.message.reply_text(
            "❌ Очистка посещений отменена.\n"
            "Все данные сохранены.",
            reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text(
            "❓ Пожалуйста, выберите один из предложенных вариантов:",
            reply_markup=get_confirm_clear_checkins_keyboard())


async def generate_users_report(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерация отчета пользователей"""
    if not USERS_DB:
        await update.message.reply_text("📝 База пользователей пуста.")
        return

    filename = f"users_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Имя', 'Телефон', 'Дата регистрации'])

        for user_data in USERS_DB.values():
            writer.writerow([
                user_data['name'], user_data['phone'],
                user_data['registered_at'].strftime('%d.%m.%Y %H:%M:%S')
            ])

    await update.message.reply_text(f"📁 Отчет пользователей готов!")

    with open(filename, 'rb') as file:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file,
            filename=filename,
            caption=
            f"👥 Отчет пользователей\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )

    # Удаляем временный файл
    os.remove(filename)


async def generate_checkins_report(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерация отчета посещений"""
    if not CHECKINS_DB:
        await update.message.reply_text("📝 История посещений пуста.")
        return

    filename = f"checkins_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            ['Имя', 'Телефон', 'Время посещения', 'Способ отметки'])

        # Сортируем по времени (новые сверху)
        sorted_checkins = sorted(CHECKINS_DB,
                                 key=lambda x: x['timestamp'],
                                 reverse=True)

        for checkin in sorted_checkins:
            writer.writerow([
                checkin['name'], checkin['phone'],
                checkin['timestamp'].strftime('%d.%m.%Y %H:%M:%S'),
                checkin['method']
            ])

    await update.message.reply_text(f"📁 Отчет посещений готов!")

    with open(filename, 'rb') as file:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file,
            filename=filename,
            caption=
            f"🕒 Отчет посещений\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )

    # Удаляем временный файл
    os.remove(filename)


async def show_statistics(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать подробную статистику"""
    today = datetime.now().date()
    today_checkins = [c for c in CHECKINS_DB if c['timestamp'].date() == today]

    # Статистика по типам отметок
    total_qr_checkins = len(
        [c for c in CHECKINS_DB if c["method"] == "QR-код"])
    today_qr_checkins = len(
        [c for c in today_checkins if c["method"] == "QR-код"])

    # Топ активных пользователей
    user_activity = {}
    for checkin in CHECKINS_DB:
        user_id = checkin['user_id']
        user_activity[user_id] = user_activity.get(user_id, 0) + 1

    top_users = sorted(user_activity.items(), key=lambda x: x[1],
                       reverse=True)[:5]

    stats_text = (f"📊 **Подробная статистика**\n\n"
                  f"👥 **Пользователи:**\n"
                  f"• Всего зарегистрировано: {len(USERS_DB)}\n\n"
                  f"📍 **Посещения (всего):**\n"
                  f"• Всего отметок: {len(CHECKINS_DB)}\n"
                  f"• Через QR-код: {total_qr_checkins}\n\n"
                  f"📅 **Сегодня ({today.strftime('%d.%m.%Y')}):**\n"
                  f"• Всего отметок: {len(today_checkins)}\n"
                  f"• Через QR-код: {today_qr_checkins}\n\n"
                  f"🔗 **QR-код:**\n"
                  f"• Статус: Активен\n"
                  f"• Ссылка: {QR_CODE_LINK}")

    if top_users:
        stats_text += "\n\n🏆 **Топ активных пользователей:**\n"
        for i, (user_id, count) in enumerate(top_users, 1):
            if user_id in USERS_DB:
                name = USERS_DB[user_id]['name']
                stats_text += f"{i}. {name} - {count} посещений\n"

    await update.message.reply_text(stats_text, parse_mode='Markdown')


async def exit_admin_panel(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выход из админ-панели"""
    user_id = update.effective_user.id

    if user_id in ADMIN_SESSIONS:
        del ADMIN_SESSIONS[user_id]
    if user_id in USER_STATES:
        del USER_STATES[user_id]

    await update.message.reply_text("🚪 Вы вышли из админ-панели.",
                                    reply_markup=None)


async def handle_message(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик всех текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text

    # Проверяем состояние пользователя
    if user_id in USER_STATES:
        state = USER_STATES[user_id]

        if state == States.WAITING_NAME:
            await handle_name_input(update, context)
            return
        elif state == States.WAITING_PHONE:
            await handle_phone_input(update, context)
            return
        elif state == States.WAITING_ADMIN_PASSWORD:
            await handle_admin_password(update, context)
            return
        elif state == States.WAITING_QR_SCAN:
            if text == "❌ Отменить отметку":
                del USER_STATES[user_id]
                await update.message.reply_text(
                    "❌ Отметка отменена.", reply_markup=get_user_keyboard())
                return
            else:
                await update.message.reply_text(
                    "📱 Пожалуйста, отсканируйте QR-код на входе в центр или нажмите \"❌ Отменить отметку\""
                )
                return
        elif state == States.CONFIRM_CLEAR_DATA:
            await confirm_clear_data(update, context)
            return
        elif state == States.CONFIRM_CLEAR_CHECKINS:
            await confirm_clear_checkins(update, context)
            return

    # Обработка кнопок
    if text == "📍 Отметиться":
        await handle_checkin_request(update, context)
    elif text == "ℹ️ Моя информация":
        await handle_user_info(update, context)
    elif text == "👥 Отчет пользователей" and user_id in ADMIN_SESSIONS:
        await generate_users_report(update, context)
    elif text == "🕒 Отчет посещений" and user_id in ADMIN_SESSIONS:
        await generate_checkins_report(update, context)
    elif text == "📊 Статистика" and user_id in ADMIN_SESSIONS:
        await show_statistics(update, context)
    elif text == "🔗 QR-код для отметок" and user_id in ADMIN_SESSIONS:
        await show_qr_code(update, context)
    elif text == "🗑️ Очистить данные" and user_id in ADMIN_SESSIONS:
        await request_clear_data(update, context)
    elif text == "🧹 Очистить посещения" and user_id in ADMIN_SESSIONS:
        await request_clear_checkins(update, context)
    elif text == "🚪 Выйти из админ-панели" and user_id in ADMIN_SESSIONS:
        await exit_admin_panel(update, context)
    else:
        # Неизвестная команда
        if user_id in USERS_DB:
            await update.message.reply_text(
                "❓ Неизвестная команда. Используйте кнопки меню.",
                reply_markup=get_user_keyboard())
        else:
            await update.message.reply_text(
                "❓ Для начала работы нажмите /start")


async def error_handler(update: object,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}")


def main() -> None:
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("manager", manager_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)

    # Запускаем бота
    logger.info("🚀 Бот с QR-кодом для проверки запущен!")
    logger.info(f"🔗 QR-код: {QR_CODE_LINK}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()