from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from functools import partial
from typing import Dict

from dotenv import load_dotenv
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .captcha import CHALLENGE_OPTIONS, Challenge, build_challenge
from .database import Database

load_dotenv()

MANAGER_TOKEN = os.getenv("MANAGER_TOKEN")
ADMIN_CHANNEL = os.getenv("ADMIN_CHANNEL")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./tg_hosts.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("tg-multibot")

db = Database(DATABASE_PATH)
pending_challenges: Dict[str, Challenge] = {}
running_apps: Dict[str, Application] = {}
manager_app: Application | None = None

DEFAULT_MANAGER_WELCOME = """👋 欢迎来到 TGBiRelay 管理面板
➕ 通过“添加 Bot”提交 Bot Token 即可启动托管；
🗂 “我的 Bot” 可查看状态、切换私聊 / Topic、配置验证码；
✏️ “管理员欢迎语” 可自定义 /start 引导文案；
请选择下方菜单继续操作。"""

DEFAULT_CLIENT_WELCOME = """🤖 欢迎使用中继客服机器人
📨 私聊模式：所有消息将直接转交管理员；
🧵 Topic 模式：系统会为你创建独立话题追踪；
🛡 发送验证码请联系管理员使用 /uv；
请耐心等待回复，感谢理解。"""



# ------------ 通用工具 ------------
async def send_admin_log(text: str) -> None:
    if not ADMIN_CHANNEL:
        return
    app = manager_app
    if not app:
        return
    try:
        await app.bot.send_message(ADMIN_CHANNEL, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:
        logger.warning("发送管理员日志失败: %s", exc)


async def send_ephemeral_reply(message, text: str, *, delay: int = 3, **kwargs):
    """回复用户后在短暂延迟后自动撤回提示，避免聊天记录堆积系统消息。"""
    reply = await message.reply_text(text, **kwargs)

    async def _cleanup() -> None:
        await asyncio.sleep(delay)
        try:
            await reply.delete()
        except Exception:
            pass

    asyncio.create_task(_cleanup())
    return reply


def captcha_enabled(row) -> bool:
    value = row["captcha_enabled"]
    if value is None:
        return True
    return bool(value)


def resolve_captcha_pools(row):
    raw = row["captcha_topics"]
    if not raw:
        return list(CHALLENGE_OPTIONS.keys()), False
    selected = [key for key in raw.split(",") if key in CHALLENGE_OPTIONS]
    if not selected:
        return list(CHALLENGE_OPTIONS.keys()), False
    return selected, True


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('➕ 添加 Bot', callback_data='menu:add')],
            [InlineKeyboardButton('🤖 我的 Bot', callback_data='menu:list')],
            [InlineKeyboardButton('👋 管理员欢迎语', callback_data='menu:welcome')],
        ]
    )


def manager_welcome_text(owner_id: int) -> str:
    custom = db.get_owner_start_text(owner_id)
    return custom or DEFAULT_MANAGER_WELCOME


def client_welcome_text(bot_username: str) -> str:
    custom = db.get_client_start_text(bot_username)
    return custom or DEFAULT_CLIENT_WELCOME


async def send_client_welcome(message, bot_username: str) -> None:
    await message.reply_text(client_welcome_text(bot_username))


def is_reset_command(text: str) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in {'default', '/default', 'reset', '/reset'}:
        return True
    return stripped in {'恢复默认', '恢复', '重置', '默认'}

def format_bot_info(row) -> str:
    mode = '🔐 私聊' if row['mode'] == 'direct' else '🏷️ Topic'
    forum = row['forum_group_id'] or '未设置'
    welcome = '自定义' if row['client_start_text'] else '默认'
    enabled = captcha_enabled(row)
    pools, custom = resolve_captcha_pools(row)
    if enabled:
        pool_text = '默认题库' if not custom else '、'.join(CHALLENGE_OPTIONS[k] for k in pools)
        captcha_line = f"🛡️ 验证：开启（{pool_text}）"
    else:
        captcha_line = '🛡️ 验证：关闭'
    lines = [
        f"🤖 <b>@{row['bot_username']}</b>",
        f"👤 Owner: <code>{row['owner_id']}</code>",
        f"⚙ 当前模式: {mode}",
        f"🏷️ Topic 群 ID: {forum}",
        f"👋 成员欢迎语: {welcome}",
        captcha_line,
        f"🕒 创建时间: {row['created_at']}",
    ]
    return chr(10).join(lines)

def bot_detail_keyboard(row) -> InlineKeyboardMarkup:
    bot_username = row['bot_username']
    captcha_status = "开启" if captcha_enabled(row) else "关闭"
    target_mode = 'forum' if row['mode'] == 'direct' else 'direct'
    mode_label = '切换为 Topic 模式' if target_mode == 'forum' else '切换为私聊模式'
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f'🔄 {mode_label}', callback_data=f"mode:{bot_username}:{target_mode}")],
            [InlineKeyboardButton('🏷️ 绑定 Topic 群', callback_data=f"forum:{bot_username}")],
            [InlineKeyboardButton('🛡️ 验证开关：' + captcha_status, callback_data=f"captcha:toggle:{bot_username}")],
            [InlineKeyboardButton('🧩 题库设置', callback_data=f"captcha:topics:{bot_username}")],
            [InlineKeyboardButton('👋 设置欢迎语', callback_data=f"welcome:{bot_username}")],
            [InlineKeyboardButton('🗑️ 解除托管', callback_data=f"drop:{bot_username}")],
            [InlineKeyboardButton('◀️ 返回列表', callback_data='menu:list')],
        ]
    )


def captcha_topics_keyboard(bot_username: str, selected: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for key, label in CHALLENGE_OPTIONS.items():
        status = "✅" if key in selected else "⬜️"
        buttons.append([InlineKeyboardButton(f"{status} {label}", callback_data=f"captcha:pool:{bot_username}:{key}")])
    buttons.append([InlineKeyboardButton('恢复默认（默认启用全部）', callback_data=f"captcha:topicaction:{bot_username}:reset")])
    buttons.append([InlineKeyboardButton('⬅️ 返回', callback_data=f"bot:{bot_username}")])
    return InlineKeyboardMarkup(buttons)


async def show_captcha_topics(query, row) -> None:
    bot_username = row['bot_username']
    selected, _ = resolve_captcha_pools(row)
    text = f"""🧩 题库设置（@{bot_username}）
点击按钮可启用/停用对应题型；全部关闭将回退至默认题库。
若希望彻底关闭验证码，请使用“验证码开关”。
"""
    await query.edit_message_text(text, reply_markup=captcha_topics_keyboard(bot_username, selected))


async def show_bot_detail(query, row) -> None:
    await query.edit_message_text(
        format_bot_info(row),
        parse_mode='HTML',
        reply_markup=bot_detail_keyboard(row),
    )


def get_owned_bot(bot_username: str, owner_id: int):
    row = db.get_bot(bot_username)
    if not row or row['owner_id'] != owner_id:
        return None
    return row

# ------------ 管理端交互 ------------
async def manager_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    owner_id = user.id if user else 0
    if user:
        db.upsert_owner(owner_id, user.username)
    text = manager_welcome_text(owner_id)
    if update.message:
        await update.message.reply_text(text, reply_markup=menu_keyboard())
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=menu_keyboard())


async def handle_manager_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    user = message.from_user
    user_id = user.id
    user_data = context.user_data
    text_value = message.text.strip()

    if user_data.pop('await_manager_welcome', None):
        db.upsert_owner(user_id, user.username)
        if is_reset_command(text_value):
            db.set_owner_start_text(user_id, None)
            await message.reply_text('✅ 已恢复默认的管理欢迎语。')
        else:
            db.set_owner_start_text(user_id, text_value)
            await message.reply_text('✅ 管理欢迎语已更新。')
        return

    pending_client = user_data.pop('await_client_welcome', None)
    if pending_client:
        bot_username = pending_client['bot_username']
        row = db.get_bot(bot_username)
        if not row or row['owner_id'] != user_id:
            await message.reply_text('❌ 无法设置该 Bot 的欢迎语。')
            return
        if is_reset_command(text_value):
            db.set_client_start_text(bot_username, None)
            await message.reply_text(f'✅ @{bot_username} 的成员欢迎语已恢复默认。')
        else:
            db.set_client_start_text(bot_username, text_value)
            await message.reply_text(f'✅ @{bot_username} 的成员欢迎语已更新。')
        return

    if user_data.get('await_token'):
        token = text_value
        user_data.pop('await_token', None)
        await register_token_flow(message, user_id, token)
        return

    if user_data.get('await_forum'):
        info = user_data.pop('await_forum')
        await assign_forum_flow(message, info['bot_username'], text_value)
        return

async def register_token_flow(message, owner_id: int, token: str) -> None:
    try:
        bot = Bot(token=token)
        bot_info = await bot.get_me()
    except Exception as exc:
        await message.reply_text(
            f"""❌ Token 无效，请重新输入。
详情: {exc}"""
        )
        return

    bot_username = bot_info.username
    if db.get_bot(bot_username):
        await message.reply_text("⚠️ 该 Bot 已托管，无需重复添加。")
        return

    db.upsert_owner(owner_id, message.from_user.username)
    db.register_bot(owner_id, token, bot_username)
    await ensure_sub_bot(bot_info.username, token, owner_id)

    await message.reply_text(
        f"""✅ 已接管 @{bot_username}
默认模式为私聊转发，可在“我的 Bot”界面切换。"""
    )

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    await send_admin_log(
        f"""🆕 新增子 Bot
👤 <code>{owner_id}</code>
🤖 @{bot_username}
🕒 {now}"""
    )


async def assign_forum_flow(message, bot_username: str, raw_value: str) -> None:
    row = db.get_bot(bot_username)
    if not row:
        await message.reply_text("❌ 未找到该 Bot，可能已被移除。")
        return
    try:
        forum_id = int(raw_value)
    except ValueError:
        await message.reply_text("⚠️ 请输入纯数字的群 ID，例如 -100xxxx。")
        return

    db.assign_forum(bot_username, forum_id)
    await message.reply_text(f"🏷️ 已为 @{bot_username} 绑定 Topic 群 {forum_id}")

    await send_admin_log(
        f"""🏷️ @{bot_username} Topic 信息更新
群 ID: <code>{forum_id}</code>"""
    )


async def manager_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    owner_id = query.from_user.id

    if data == 'menu:add':
        context.user_data['await_token'] = True
        await query.edit_message_text('🆔 请发送需要托管的 Bot Token。')
        return

    if data == 'menu:list':
        bots = db.list_bots_for_owner(owner_id)
        if not bots:
            await query.edit_message_text('🤔 暂无托管 Bot，可先添加一个。', reply_markup=menu_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(f"@{row['bot_username']}", callback_data=f"bot:{row['bot_username']}")]
            for row in bots
        ]
        keyboard.append([InlineKeyboardButton('⬅️ 返回', callback_data='menu:home')])
        await query.edit_message_text('请选择需要管理的 Bot：', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == 'menu:home':
        await query.edit_message_text('📋 已返回主菜单。', reply_markup=menu_keyboard())
        return

    if data == 'menu:welcome':
        context.user_data['await_manager_welcome'] = True
        await query.edit_message_text(
            """请发送新的管理员欢迎语。
发送 /default 可恢复默认设置。""",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ 返回', callback_data='menu:home')]])
        )
        return

    if data.startswith('bot:'):
        bot_username = data.split(':', 1)[1]
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法访问该 Bot，可能已被移除。')
            return
        await show_bot_detail(query, row)
        return

    if data.startswith('mode:'):
        _, bot_username, mode = data.split(':', 2)
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 未找到对应 Bot。')
            return
        if mode == 'forum' and not row['forum_group_id']:
            await query.edit_message_text('⚠️ 切换为 Topic 模式前请先绑定 Topic 群 ID。')
            return
        db.update_mode(bot_username, mode)
        await send_admin_log(f'🔄 @{bot_username} 切换模式 -> {mode}')
        row = db.get_bot(bot_username)
        await show_bot_detail(query, row)
        return

    if data.startswith('forum:'):
        bot_username = data.split(':', 1)[1]
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法设置该 Bot 的 Topic。')
            return
        context.user_data['await_forum'] = {'bot_username': bot_username}
        await query.edit_message_text('请发送 Topic 所在群 ID（记得给 Bot 管理员权限）。')
        return

    if data.startswith('drop:'):
        bot_username = data.split(':', 1)[1]
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法解除托管。')
            return
        await shutdown_sub_bot(bot_username)
        db.remove_bot(bot_username)
        await query.edit_message_text('🗑️ 已解除托管。', reply_markup=menu_keyboard())
        await send_admin_log(f'🗑️ @{bot_username} 被 {owner_id} 移除')
        return

    if data.startswith('welcome:'):
        bot_username = data.split(':', 1)[1]
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法设置该 Bot 的欢迎语。')
            return
        context.user_data['await_client_welcome'] = {'bot_username': bot_username}
        await query.edit_message_text(
            f"""请发送 @{bot_username} 的成员欢迎语。
发送 /default 可恢复默认。""",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ 返回', callback_data=f"bot:{bot_username}")]])
        )
        return

    if data.startswith('captcha:toggle:'):
        bot_username = data.split(':', 2)[2]
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法切换验证码状态。')
            return
        new_status = not captcha_enabled(row)
        db.set_captcha_enabled(bot_username, new_status)
        row = db.get_bot(bot_username)
        await show_bot_detail(query, row)
        await query.answer('已开启' if new_status else '已关闭')
        return

    if data.startswith('captcha:topics:'):
        bot_username = data.split(':', 2)[2]
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法设置题库。')
            return
        await show_captcha_topics(query, row)
        return

    if data.startswith('captcha:pool:'):
        _, _, bot_username, key = data.split(':', 3)
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法设置题库。')
            return
        selected, _ = resolve_captcha_pools(row)
        current = set(selected)
        if key in CHALLENGE_OPTIONS:
            if key in current and len(current) > 1:
                current.remove(key)
            else:
                current.add(key)
        if not current or len(current) == len(CHALLENGE_OPTIONS):
            db.set_captcha_topics(bot_username, None)
        else:
            db.set_captcha_topics(bot_username, sorted(current))
        row = db.get_bot(bot_username)
        await show_captcha_topics(query, row)
        return

    if data.startswith('captcha:topicaction:'):
        _, bot_username, action = data.split(':', 2)
        row = get_owned_bot(bot_username, owner_id)
        if not row:
            await query.edit_message_text('⚠️ 无法设置题库。')
            return
        if action in {'all', 'reset'}:
            db.set_captcha_topics(bot_username, None)
        row = db.get_bot(bot_username)
        await show_captcha_topics(query, row)
        return
# ------------ 子 Bot 逻辑 ------------
async def subbot_start(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int, bot_username: str) -> None:
    message = update.message
    if not message:
        return
    user_id = message.from_user.id
    key = f"{bot_username}:{user_id}"

    row = db.get_bot(bot_username)
    if not row:
        await message.reply_text("⚠️ Bot 配置已失效，请联系管理员。")
        return

    if not captcha_enabled(row) or db.is_verified(bot_username, user_id):
        await send_client_welcome(message, bot_username)
        return

    pools, _ = resolve_captcha_pools(row)
    challenge = build_challenge(pools)
    pending_challenges[key] = challenge
    await message.reply_text(challenge.render(), parse_mode='HTML')


async def handle_client(update: Update, context: ContextTypes.DEFAULT_TYPE, owner_id: int, bot_username: str) -> None:
    message = update.message
    if not message:
        return
    chat = message.chat
    row = db.get_bot(bot_username)
    if not row:
        await message.reply_text("⚠️ Bot 配置已失效，请联系托管方。")
        return

    is_owner = bool(message.from_user and message.from_user.id == owner_id)
    is_command = bool(message.text and message.text.startswith("/"))
    if is_owner and is_command:
        if chat.type == ChatType.PRIVATE and chat.id == owner_id:
            await handle_owner_command(message, context, bot_username, row)
            return
        if row["mode"] == "forum" and chat.id == row["forum_group_id"]:
            await handle_owner_command(message, context, bot_username, row)
            return


    # 普通用户逻辑
    if chat.type == ChatType.PRIVATE and chat.id != owner_id:
        if db.is_blacklisted(bot_username, chat.id):
            await message.reply_text("🚫 你已被限制，请联系管理员申诉。")
            return

        if not await ensure_verified(message, context, bot_username, owner_id, row):
            return

        if row["mode"] == "direct":
            await relay_direct(message, context, owner_id, bot_username)
        else:
            await relay_forum(message, context, row, bot_username)
        return

    # Owner 在私聊中回复
    if chat.type == ChatType.PRIVATE and chat.id == owner_id:
        target = db.pop_forward_target(bot_username, message.reply_to_message.message_id) if message.reply_to_message else None
        if target:
            await context.bot.copy_message(chat_id=target, from_chat_id=owner_id, message_id=message.message_id)
            await message.reply_text("✅ 已回复用户。", quote=True)
        return

    # Topic 消息
    if row["mode"] == "forum" and chat.id == row["forum_group_id"] and getattr(message, "is_topic_message", False):
        target_uid = db.user_by_topic(bot_username, message.message_thread_id)
        if target_uid:
            await context.bot.copy_message(chat_id=target_uid, from_chat_id=chat.id, message_id=message.message_id)
        return


def challenge_key(bot_username: str, user_id: int) -> str:
    return f"{bot_username}:{user_id}"


async def ensure_verified(message, context, bot_username: str, owner_id: int, bot_row) -> bool:
    user_id = message.from_user.id
    key = challenge_key(bot_username, user_id)

    if not captcha_enabled(bot_row):
        return True

    if db.is_verified(bot_username, user_id):
        return True

    if key in pending_challenges:
        challenge = pending_challenges[key]
        if message.text and message.text.strip() == challenge.answer:
            db.verify_user(bot_username, user_id)
            pending_challenges.pop(key, None)
            await send_client_welcome(message, bot_username)
            await notify_owner_verified(context.bot, owner_id, bot_username, message.from_user)
            return False
        await message.reply_text('❌ 答案不正确，请输入 /start 重新获取题目。')
        return False

    pools, _ = resolve_captcha_pools(bot_row)
    challenge = build_challenge(pools)
    pending_challenges[key] = challenge
    await message.reply_text(challenge.render(), parse_mode='HTML')
    return False

    challenge = build_challenge()
    pending_challenges[key] = challenge
    await message.reply_text(challenge.render(), parse_mode='HTML')
    return False


async def notify_owner_verified(bot: Bot, owner_id: int, bot_username: str, user) -> None:
    text = f"""🆗 有用户通过验证
🤖 @{bot_username}
👤 {user.full_name or '访客'}
🆔 <code>{user.id}</code>"""
    try:
        await bot.send_message(owner_id, text, parse_mode='HTML')
    except Exception as exc:
        logger.warning('通知 owner 验证通过失败: %s', exc)


async def relay_direct(message, context, owner_id: int, bot_username: str) -> None:
    forwarded = await context.bot.forward_message(
        chat_id=owner_id,
        from_chat_id=message.chat_id,
        message_id=message.message_id,
    )
    db.record_forward(bot_username, forwarded.message_id, message.chat_id)
    await send_ephemeral_reply(message, '📨 已送达客服，请稍候回复。', quote=True)


async def relay_forum(message, context, row, bot_username: str) -> None:
    forum_id = row["forum_group_id"]
    if not forum_id:
        await message.reply_text("⚠️ 管理员尚未设置 Topic 模式，请稍后再试。")
        return
    topic_id = db.get_topic(bot_username, message.chat_id)
    if not topic_id:
        display = message.from_user.full_name or ("@" + message.from_user.username if message.from_user.username else "访客")
        topic = await context.bot.create_forum_topic(chat_id=forum_id, name=display[:64])
        topic_id = topic.message_thread_id
        db.upsert_topic(bot_username, message.chat_id, topic_id)
    async def _do_forward(tid: int) -> None:
        await context.bot.forward_message(
            chat_id=forum_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=tid,
        )
        await send_ephemeral_reply(message, "🗂️ 已投递到专属主题。", quote=True)

    try:
        await _do_forward(topic_id)
    except BadRequest as exc:
        hint = str(exc).lower()
        if "message thread not found" not in hint and "topic not found" not in hint:
            raise
        display = message.from_user.full_name or (f"@{message.from_user.username}" if message.from_user.username else "访客")
        topic = await context.bot.create_forum_topic(chat_id=forum_id, name=display[:64])
        topic_id = topic.message_thread_id
        db.upsert_topic(bot_username, message.chat_id, topic_id)
        await _do_forward(topic_id)


async def handle_owner_command(message, context, bot_username: str, bot_row) -> None:
    text = message.text.strip()
    chat = message.chat
    forum_thread_target: int | None = None
    forum_group_id = bot_row["forum_group_id"]
    if bot_row["mode"] == "forum" and forum_group_id and chat.id == forum_group_id:
        topic_id = getattr(message, "message_thread_id", None)
        if topic_id is None and message.reply_to_message:
            topic_id = getattr(message.reply_to_message, "message_thread_id", None)
        if topic_id:
            forum_thread_target = db.user_by_topic(bot_username, topic_id)
    if text.startswith("/bl"):
        entries = db.list_blacklist(bot_username)
        if not entries:
            await message.reply_text("👍 当前没有黑名单用户。")
            return
        lines = [f"• <code>{row['user_id']}</code> ({row['created_at']})" for row in entries[:30]]
        await message.reply_text("""🛑 黑名单：
""" + chr(10).join(lines), parse_mode="HTML")
        return

    if text.startswith("/b"):
        target = await resolve_target_id(message, bot_row, bot_username, thread_target=forum_thread_target)
        if not target:
            await message.reply_text("⚠️ 请回复用户消息或附带 ID。")
            return
        if db.add_blacklist(bot_username, target):
            await message.reply_text(f"🚫 已拉黑 {target}")
            await send_admin_log(f"🚫 @{bot_username} 拉黑 <code>{target}</code>")
        else:
            await message.reply_text("ℹ️ 用户已在黑名单。")
        return

    if text.startswith("/ub"):
        target = await resolve_target_id(message, bot_row, bot_username, thread_target=forum_thread_target)
        if not target:
            await message.reply_text("⚠️ 请回复用户消息或附带 ID。")
            return
        if db.remove_blacklist(bot_username, target):
            await message.reply_text(f"✅ 已解除 {target}")
            await send_admin_log(f"✅ @{bot_username} 解封 <code>{target}</code>")
        else:
            await message.reply_text("🙅 未找到该用户。")
        return

    if text.startswith("/uv"):
        target = await resolve_target_id(message, bot_row, bot_username, thread_target=forum_thread_target)
        if not target:
            await message.reply_text("⚠️ 请回复用户消息或附带 ID。")
            return
        if db.unverify_user(bot_username, target):
            await message.reply_text(f"♻️ 已撤销用户 {target} 验证。")
        else:
            await message.reply_text("ℹ️ 用户尚未验证。")
        return

    if text.startswith("/id"):
        target = await resolve_target_id(message, bot_row, bot_username, thread_target=forum_thread_target)
        if not target:
            await message.reply_text("⚠️ 请回复用户消息或附带 ID。")
            return
        await send_user_card(message, context, bot_username, target)
        return


async def resolve_target_id(message, bot_row, bot_username: str, thread_target: int | None = None) -> int | None:
    parts = message.text.split()
    if len(parts) == 2 and parts[1].lstrip("-").isdigit():
        return int(parts[1])
    if message.reply_to_message:
        reply = message.reply_to_message
        if bot_row["mode"] == "direct":
            forward_id = reply.message_id
            return db.get_forward_target(bot_username, forward_id)
        if bot_row["mode"] == "forum":
            if reply.forward_from:
                return reply.forward_from.id
            thread_id = getattr(reply, "message_thread_id", None)
            if thread_id:
                user_id = db.user_by_topic(bot_username, thread_id)
                if user_id:
                    return user_id
            if reply.from_user and reply.from_user.id != message.from_user.id:
                return reply.from_user.id
    if thread_target:
        return thread_target
    if bot_row["mode"] == "forum":
        topic_id = getattr(message, "message_thread_id", None)
        if topic_id:
            user_id = db.user_by_topic(bot_username, topic_id)
            if user_id:
                return user_id
    return None


async def send_user_card(message, context, bot_username: str, user_id: int) -> None:
    try:
        user = await context.bot.get_chat(user_id)
    except Exception as exc:
        await message.reply_text(f"❌ 获取用户失败：{exc}")
        return
    blocked = db.is_blacklisted(bot_username, user_id)
    verified = db.is_verified(bot_username, user_id)
    status = []
    status.append("🚫 黑名单" if blocked else "🟢 正常")
    status.append("✅ 已验证" if verified else "❓ 未验证")
    text = f"""👤 用户卡片
🆔 <code>{user.id}</code>
📛 {user.full_name or '-'}
🌐 @{user.username or '无'}
🛡️ 状态：{' | '.join(status)}"""
    await message.reply_text(text, parse_mode="HTML")


# ------------ 子 Bot 生命周期 ------------
async def ensure_sub_bot(bot_username: str, token: str, owner_id: int) -> None:
    if bot_username in running_apps:
        return
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", partial(subbot_start, owner_id=owner_id, bot_username=bot_username)))
    app.add_handler(MessageHandler(filters.ALL, partial(handle_client, owner_id=owner_id, bot_username=bot_username)))
    running_apps[bot_username] = app
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("子 Bot %s 已启动", bot_username)


async def shutdown_sub_bot(bot_username: str) -> None:
    app = running_apps.pop(bot_username, None)
    if app:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


async def spin_existing_bots() -> None:
    for row in db.iter_all_bots():
        await ensure_sub_bot(row["bot_username"], row["token"], row["owner_id"])


# ------------ 主入口 ------------
async def main() -> None:
    global manager_app
    if not MANAGER_TOKEN:
        raise RuntimeError("请在 .env 中配置 MANAGER_TOKEN")

    await spin_existing_bots()

    manager_app = Application.builder().token(MANAGER_TOKEN).build()
    running_apps["__manager__"] = manager_app
    manager_app.add_handler(CommandHandler("start", manager_start))
    manager_app.add_handler(CallbackQueryHandler(manager_callback))
    manager_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manager_text))

    await manager_app.initialize()
    await manager_app.start()
    await manager_app.updater.start_polling()
    logger.info("管理 Bot 已上线")

    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出……")
