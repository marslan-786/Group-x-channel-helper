import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Set, List, Union
from telegram.ext import ContextTypes
from telegram import (
    Update, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions, MessageEntity
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

import os
import asyncio

channel_timers = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

group_settings: Dict[int, dict] = {}
action_settings: Dict[int, dict] = {}
user_state: Dict[int, dict] = {}
user_warnings: Dict[int, Dict[int, int]] = {}
admin_list: Dict[int, List[int]] = {}
user_chats: Dict[int, Dict[str, Set[int]]] = {}

def parse_duration(duration_str: str) -> timedelta:
    if not duration_str:
        return timedelta(hours=1)
    duration_str = duration_str.strip().lower()
    match = re.match(r"(\d+)\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)?", duration_str)
    if not match:
        return timedelta(hours=1)
    value = int(match.group(1))
    unit = match.group(2) or "h"
    if unit.startswith("m"):
        return timedelta(minutes=value)
    elif unit.startswith("h"):
        return timedelta(hours=value)
    elif unit.startswith("d"):
        return timedelta(days=value)
    else:
        return timedelta(hours=1)

def parse_time(time_str):
    match = re.fullmatch(r"(\d+)([smhd])", time_str.lower())
    if not match:
        return None

    value, unit = int(match.group(1)), match.group(2)
    if unit == 's':
        return value
    elif unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 60 * 60
    elif unit == 'd':
        return value * 60 * 60 * 24
    return None
    

def format_duration(duration: timedelta) -> str:
    days = duration.days
    seconds = duration.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"{days} day(s)"
    elif hours > 0:
        return f"{hours} hour(s)"
    elif minutes > 0:
        return f"{minutes} minute(s)"
    else:
        return "a few seconds"

def initialize_group_settings(chat_id: int, chat_type: str = "group", title: str = None, user_id: int = None):
    if chat_id not in group_settings:
        group_settings[chat_id] = {
            "title": title or f"Group {chat_id}",
            "block_links": False,
            "block_forwards": False,
            "block_mentions": False,
            "allowed_domains": set(),
            "chat_type": chat_type
        }

    if chat_id not in action_settings:
        action_settings[chat_id] = {
            "links": {"action": "off", "duration": "1h", "warn": True, "delete": True, "enabled": False},
            "forward": {"action": "off", "duration": "1h", "warn": True, "delete": True, "enabled": False},
            "mentions": {"action": "off", "duration": "1h", "warn": True, "delete": True, "enabled": False},
            "custom": {
                "enabled": False,
                "action": "off", "warn_count": 1,
                "duration": "1h", "messages": []
            }
        }

    if chat_id not in admin_list:
        admin_list[chat_id] = []

    if chat_id not in user_warnings:
        user_warnings[chat_id] = {}

    # ✅ Allow group to self-manage
    if user_id is not None and user_id != chat_id:
        user_chats.setdefault(user_id, {}).setdefault("groups", set()).add(chat_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if chat.type in ["group", "supergroup"]:
        initialize_group_settings(chat.id, chat.type, chat.title, user.id)
        return

    keyboard = [
        [InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{context.bot.username}?startgroup=true")],
        [InlineKeyboardButton("👥 Your Groups", callback_data="your_groups")],
        [InlineKeyboardButton("❓ Help", callback_data="help_command")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = (
        f"👋 Welcome <b>{user.first_name}</b>!\n\n"
        "I'm your group management bot. Use the buttons below to begin!"
    )

    if update.message:
        await update.message.reply_html(message_text, reply_markup=reply_markup)

    elif update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except:
            await update.callback_query.message.reply_html(message_text, reply_markup=reply_markup)

        await update.callback_query.answer()

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
🤖 *Bot Commands*:

*Admin Commands:*
/ban [duration] – Ban a user (reply to user)
/mute [duration] – Mute a user (reply to user)
/unban – Unban user
/unmute – Unmute user
/settings – Open settings

Examples:
/ban 1h – Ban for 1 hour
/mute 2d – Mute for 2 days
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def show_user_groups(query):
    user_id = query.from_user.id
    groups = user_chats.get(user_id, {}).get("groups", set())

    if not groups:
        await query.edit_message_text(
            "😕 You haven't added this bot to any group yet.\n\n"
            "🔄 Please add the bot to your group and then use /start in that group."
        )
        return

    kb = []
    for gid in groups:
        title = group_settings.get(gid, {}).get("title", f"Group {gid}")
        kb.append([InlineKeyboardButton(f"📛 {title}", callback_data=f"group_{gid}")])

    kb.append([InlineKeyboardButton("🏠 Main Menu", callback_data="force_start")])
    await query.edit_message_text("📊 Your Groups:", reply_markup=InlineKeyboardMarkup(kb))

async def show_group_settings(update_or_query: Union[Update, CallbackQuery], gid: int):
    initialize_group_settings(gid)

    kb = [
        [InlineKeyboardButton("🔗 Link Settings", callback_data=f"link_settings_{gid}")],
        [InlineKeyboardButton("↩️ Forward Settings", callback_data=f"forward_settings_{gid}")],
        [InlineKeyboardButton("🗣 Mention Settings", callback_data=f"mention_settings_{gid}")],
        [InlineKeyboardButton("📝 Custom Message Filter", callback_data=f"custom_settings_{gid}")],
        [InlineKeyboardButton("📋 Main Menu", callback_data="force_start")]  
    ]

    text = f"⚙️ *Settings for* `{gid}`\nChoose a category:"

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
    else:
        await update_or_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        
async def show_link_settings(query, gid):
    s = action_settings[gid]["links"]
    buttons = []

    buttons.append([InlineKeyboardButton(
        f"✅ Link Filtering: {'On' if s['enabled'] else 'Off'}",
        callback_data=f"toggle_links_enabled_{gid}"
    )])

    if s["enabled"]:
        current_action = s.get('action', 'off')

        buttons.append([InlineKeyboardButton(
            f"🎯 Action: {current_action.capitalize()}",
            callback_data=f"cycle_link_action_{gid}"
        )])

        if current_action == "warn":
            warn_count = s.get('warn_count', 1)
            buttons.append([InlineKeyboardButton(
                f"⚠️ Warning Count: {warn_count}",
                callback_data=f"cycle_link_warn_count_{gid}"
            )])

        buttons.append([InlineKeyboardButton(
            f"⏰ Duration: {s.get('duration', '30m')}",
            callback_data=f"change_link_duration_{gid}"
        )])

    chat_type = query.message.chat.type
    if chat_type in ["group", "supergroup"]:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="back_to_settings")])
    else:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="force_start")])

    await query.edit_message_text(
        text="🔗 *Link Settings*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def show_forward_settings(query, gid):
    s = action_settings[gid]["forward"]
    buttons = []

    buttons.append([InlineKeyboardButton(
        f"✅ Forward Filtering: {'On' if s['enabled'] else 'Off'}",
        callback_data=f"toggle_forward_enabled_{gid}"
    )])

    if s["enabled"]:
        current_action = s.get('action', 'off')

        buttons.append([InlineKeyboardButton(
            f"🎯 Action: {current_action.capitalize()}",
            callback_data=f"cycle_forward_action_{gid}"
        )])

        if current_action == "warn":
            warn_count = s.get('warn_count', 1)
            buttons.append([InlineKeyboardButton(
                f"⚠️ Warning Count: {warn_count}",
                callback_data=f"cycle_forward_warn_count_{gid}"
            )])

        buttons.append([InlineKeyboardButton(
            f"⏰ Duration: {s.get('duration', '30m')}",
            callback_data=f"change_forward_duration_{gid}"
        )])

    chat_type = query.message.chat.type
    if chat_type in ["group", "supergroup"]:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="settings_command")])
    else:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="force_start")])

    await query.edit_message_text(
        text="📤 *Forward Settings*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def show_mention_settings(query, gid):
    s = action_settings[gid]["mentions"]
    buttons = []

    buttons.append([InlineKeyboardButton(
        f"✅ Mention Filtering: {'On' if s['enabled'] else 'Off'}",
        callback_data=f"toggle_mention_enabled_{gid}"
    )])

    if s["enabled"]:
        current_action = s.get('action', 'off')

        buttons.append([InlineKeyboardButton(
            f"🎯 Action: {current_action.capitalize()}",
            callback_data=f"cycle_mention_action_{gid}"
        )])

        if current_action == "warn":
            warn_count = s.get('warn_count', 1)
            buttons.append([InlineKeyboardButton(
                f"⚠️ Warning Count: {warn_count}",
                callback_data=f"cycle_mention_warn_count_{gid}"
            )])

        buttons.append([InlineKeyboardButton(
            f"⏰ Duration: {s.get('duration', '30m')}",
            callback_data=f"change_mention_duration_{gid}"
        )])

    chat_type = query.message.chat.type
    if chat_type in ["group", "supergroup"]:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="settings_command")])
    else:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="back_to_settings")])

    await query.edit_message_text(
        text="👥 *Mention Settings*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def show_custom_settings(query, gid):
    s = action_settings[gid]["custom"]
    buttons = []

    buttons.append([InlineKeyboardButton(
        f"✅ Filtering: {'On' if s['enabled'] else 'Off'}",
        callback_data=f"toggle_custom_enabled_{gid}"
    )])

    if s["enabled"]:
        current_action = s.get('action', 'off')

        buttons.append([InlineKeyboardButton(
            f"🎯 Action: {current_action.capitalize()}",
            callback_data=f"cycle_custom_action_{gid}"
        )])

        if current_action == "warn":
            warn_count = s.get('warn_count', 1)
            buttons.append([InlineKeyboardButton(
                f"⚠️ Warning Count: {warn_count}",
                callback_data=f"cycle_custom_warn_count_{gid}"
            )])

        buttons.append([InlineKeyboardButton(
            f"⏰ Duration: {s.get('duration', '30m')}",
            callback_data=f"change_custom_duration_{gid}"
        )])

        buttons.append([InlineKeyboardButton(
            "➕ Add Custom Message",
            callback_data=f"add_custom_message_{gid}"
        )])

    chat_type = query.message.chat.type
    if chat_type in ["group", "supergroup"]:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="settings_command")])
    else:
        buttons.append([InlineKeyboardButton("📋 Main Menu", callback_data="force_start")])

    await query.edit_message_text(
        text="📝 *Custom Message Settings*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    
async def message_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    if message.chat.type not in ["group", "supergroup"]:
        return

    
    if chat_id not in group_settings or message.from_user.id == context.bot.id:
        return

    
    if message.sender_chat:
        return

    user_id = message.from_user.id

   
    if await is_admin(chat_id, user_id, context):
        return

    text = message.text or message.caption or ""
    is_forwarded = message.forward_from or message.forward_from_chat
    has_links = bool(re.search(r"https?://|t\.me|telegram\.me|www\.", text))
    has_mentions = any(e.type in [MessageEntity.MENTION, MessageEntity.TEXT_MENTION] for e in message.entities or [])

    actions = action_settings.get(chat_id, {})
    settings = group_settings.get(chat_id, {})

    try:
        
        if settings.get("block_links") and actions.get("links", {}).get("enabled") and has_links:
            return await apply_action("links", chat_id, user_id, message, context)

        
        elif settings.get("block_forwards") and actions.get("forward", {}).get("enabled") and is_forwarded:
            return await apply_action("forward", chat_id, user_id, message, context)

        
        elif settings.get("block_mentions") and actions.get("mentions", {}).get("enabled") and has_mentions:
            return await apply_action("mentions", chat_id, user_id, message, context)

        
        elif actions.get("custom", {}).get("enabled") and "custom_messages" in group_settings[chat_id]:
            for word in group_settings[chat_id]["custom_messages"]:
                if word.lower() in text.lower():
                    return await apply_action("custom", chat_id, user_id, message, context)

    except Exception as e:
        logger.error(f"[Filter Handler Error] {e}")


async def apply_action(filter_type: str, chat_id: int, user_id: int, message, context):
    s = action_settings[chat_id][filter_type]
    action = s["action"]
    duration = parse_duration(s["duration"])
    username = message.from_user.mention_html()
    reason_map = {
        "links": "Link Sending",
        "forward": "Forwarded Messages",
        "mentions": "Mentions",
        "custom": "Custom Message"
    }
    reason = reason_map.get(filter_type, "Unknown Reason")

    
    await message.delete()

    button_list = []

    if action == "mute":
        until_date = datetime.utcnow() + duration
        permissions = ChatPermissions(can_send_messages=False)
        await context.bot.restrict_chat_member(chat_id, user_id, permissions=permissions, until_date=until_date)

        button_list = [[InlineKeyboardButton("🔓 Unmute", callback_data=f"unmute_{chat_id}_{user_id}")]]
        action_text = f"🔇 User muted for {format_duration(duration)}."

    elif action == "ban":
        until_date = datetime.utcnow() + duration
        await context.bot.ban_chat_member(chat_id, user_id, until_date=until_date)

        button_list = [[InlineKeyboardButton("♻️ Unban", callback_data=f"unban_{chat_id}_{user_id}")]]
        action_text = f"🚫 User banned for {format_duration(duration)}."

    elif action == "warn":
        user_warnings.setdefault(chat_id, {})
        user_warnings[chat_id][user_id] = user_warnings[chat_id].get(user_id, 0) + 1
        warn_count = user_warnings[chat_id][user_id]
        max_warn = s.get("warn_count", 3)

        
        button_list = [
            [
                InlineKeyboardButton("➕ Increase Warning", callback_data=f"warnadd_{chat_id}_{user_id}"),
                InlineKeyboardButton("➖ Decrease Warning", callback_data=f"warndec_{chat_id}_{user_id}")
            ],
            [InlineKeyboardButton("🗑️ Reset Warnings", callback_data=f"warnreset_{chat_id}_{user_id}")]
        ]
        action_text = f"⚠️ Warning {warn_count}/{max_warn} given."

        if warn_count >= max_warn:
            post_action = s.get("post_warn_action", "mute")
            until_date = datetime.utcnow() + duration

            
            try:
                await message.delete()
            except:
                pass

            
            if post_action == "ban":
                await context.bot.ban_chat_member(chat_id, user_id, until_date=until_date)
                action_text = f"🚫 User automatically banned after {warn_count} warnings."
                button_list = [[InlineKeyboardButton("♻️ Unban", callback_data=f"unban_{chat_id}_{user_id}")]]
            else:
                permissions = ChatPermissions(can_send_messages=False)
                await context.bot.restrict_chat_member(chat_id, user_id, permissions=permissions, until_date=until_date)
                action_text = f"🔇 User automatically muted after {warn_count} warnings."
                button_list = [[InlineKeyboardButton("🔓 Unmute", callback_data=f"unmute_{chat_id}_{user_id}")]]

            
            user_warnings[chat_id][user_id] = 0

    msg = (
        f"<b>👤 User:</b> {username}\n"
        f"<b>🎯 Action:</b> {action_text}\n"
        f"<b>📌 Reason:</b> {reason}"
    )
    reply_markup = InlineKeyboardMarkup(button_list) if button_list else None
    await message.chat.send_message(msg, reply_markup=reply_markup, parse_mode="HTML")


async def custom_message_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    if user_id not in user_state:
        return

    state_info = user_state[user_id]
    if state_info["state"] != "awaiting_custom_message":
        return

    gid = state_info["gid"]
    initialize_group_settings(gid)

    if "custom_messages" not in group_settings[gid]:
        group_settings[gid]["custom_messages"] = set()

    words = text.split()
    for word in words:
        group_settings[gid]["custom_messages"].add(word.lower())

    del user_state[user_id]

    await update.message.reply_text("✅ Your custom words have been saved!")
    await start(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    chat = q.message.chat   
    await q.answer()
    
    if chat.type in ["group", "supergroup"]:
        member = await chat.get_member(uid)
        if member.status not in ["administrator", "creator"]:
            return await q.answer("❌ Only Admin Use This۔", show_alert=True)
    
    

    try:      
        if data in ["force_start", "back_to_settings"]:
            chat = q.message.chat
            user = q.from_user

            try:
                await q.message.delete()
            except:
                pass

            if chat.type in ["group", "supergroup"]:
                if await is_admin(chat.id, user.id, context):
                   return await show_group_settings(q, chat.id)
                else:
                    return await q.answer("⚠️ Only admins can access group settings.", show_alert=True)
            else:
                return await start(update, context)

        if data == "your_groups":
            return await show_user_groups(q)

        if data == "help_command":
            return await show_help(q, context)

        if data.startswith("group_"):
            gid = int(data.split("_", 1)[1])
            if await is_admin(gid, uid, context):
                return await show_group_settings(q, gid)
            return await q.answer("⚠️ Admins only!", show_alert=True)

        if data.startswith("group_settings_"):
            gid = int(data.split("_", 2)[2])
            if await is_admin(gid, uid, context):
                return await show_group_settings(q, gid)
            return await q.answer("⚠️ Admins only!", show_alert=True)

        if data.startswith("link_settings_"):
            gid = int(data.rsplit("_", 1)[1])
            return await show_link_settings(q, gid)

        if data.startswith("mention_settings_"):
            gid = int(data.rsplit("_", 1)[1])
            return await show_mention_settings(q, gid)

        if data.startswith("forward_settings_"):
            gid = int(data.rsplit("_", 1)[1])
            return await show_forward_settings(q, gid)

        if data.startswith("toggle_links_enabled_"):
            gid = int(data.rsplit("_", 1)[1])
            initialize_group_settings(gid)
            s = action_settings[gid]["links"]
            s["enabled"] = not s["enabled"]
            group_settings[gid]["block_links"] = s["enabled"]
            if not s["enabled"]:
                s["action"] = "off"
            return await show_link_settings(q, gid)

        if data.startswith("cycle_link_action_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["links"]
            options = ['off', 'mute', 'ban', 'warn']
            s['action'] = options[(options.index(s.get('action', 'off')) + 1) % len(options)]
            return await show_link_settings(q, gid)

        if data.startswith("cycle_link_warn_count_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["links"]
            count = s.get('warn_count', 1)
            s['warn_count'] = 1 if count >= 3 else count + 1
            return await show_link_settings(q, gid)

        if data.startswith("change_link_duration_"):
            gid = int(data.rsplit("_", 1)[1])
            opts = ["30m", "1h", "6h", "1d", "3d", "7d"]
            cur = action_settings[gid]["links"]["duration"]
            action_settings[gid]["links"]["duration"] = opts[(opts.index(cur) + 1) % len(opts)]
            return await show_link_settings(q, gid)

        if data.startswith("toggle_mention_enabled_"):
            gid = int(data.rsplit("_", 1)[1])
            initialize_group_settings(gid)
            s = action_settings[gid]["mentions"]
            s['enabled'] = not s['enabled']
            group_settings[gid]["block_mentions"] = s["enabled"]
            if not s["enabled"]:
                s["action"] = "off"
            return await show_mention_settings(q, gid)

        if data.startswith("cycle_mention_action_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["mentions"]
            options = ['off', 'mute', 'ban', 'warn']
            s['action'] = options[(options.index(s.get('action', 'off')) + 1) % len(options)]
            return await show_mention_settings(q, gid)

        if data.startswith("cycle_mention_warn_count_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["mentions"]
            count = s.get('warn_count', 1)
            s['warn_count'] = 1 if count >= 3 else count + 1
            return await show_mention_settings(q, gid)

        if data.startswith("change_mention_duration_"):
            gid = int(data.rsplit("_", 1)[1])
            opts = ["30m", "1h", "6h", "1d", "3d", "7d"]
            cur = action_settings[gid]["mentions"]["duration"]
            action_settings[gid]["mentions"]["duration"] = opts[(opts.index(cur) + 1) % len(opts)]
            return await show_mention_settings(q, gid)

        
        if data.startswith("toggle_forward_enabled_"):
            gid = int(data.rsplit("_", 1)[1])
            initialize_group_settings(gid)
            s = action_settings[gid]["forward"]
            s["enabled"] = not s["enabled"]
            group_settings[gid]["block_forwards"] = s["enabled"]
            if not s["enabled"]:
                s["action"] = "off"
            return await show_forward_settings(q, gid)

        if data.startswith("cycle_forward_action_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["forward"]
            options = ['off', 'mute', 'ban', 'warn']
            s['action'] = options[(options.index(s.get('action', 'off')) + 1) % len(options)]
            return await show_forward_settings(q, gid)

        if data.startswith("cycle_forward_warn_count_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["forward"]
            count = s.get('warn_count', 1)
            s['warn_count'] = 1 if count >= 3 else count + 1
            return await show_forward_settings(q, gid)

        if data.startswith("change_forward_duration_"):
            gid = int(data.rsplit("_", 1)[1])
            opts = ["30m", "1h", "6h", "1d", "3d", "7d"]
            cur = action_settings[gid]["forward"]["duration"]
            action_settings[gid]["forward"]["duration"] = opts[(opts.index(cur) + 1) % len(opts)]
            return await show_forward_settings(q, gid)

        if data.startswith("unmute_"):
            _, gid, uid = data.split("_")
            gid, uid = int(gid), int(uid)
            if not await is_admin(gid, q.from_user.id, context):
                return await q.answer("⚠️ Only admins can perform this action.", show_alert=True)
            try:
                permissions = ChatPermissions(can_send_messages=True)
                await context.bot.restrict_chat_member(gid, uid, permissions=permissions)
                await q.edit_message_text("✅ User has been unmuted.")
            except Exception as e:
                logger.error(f"Unmute error: {e}")
                await q.answer("❌ Failed to unmute.", show_alert=True)
            return

        if data.startswith("unban_"):
            _, gid, uid = data.split("_")
            gid, uid = int(gid), int(uid)
            if not await is_admin(gid, q.from_user.id, context):
                return await q.answer("⚠️ Only admins can perform this action.", show_alert=True)
            try:
                await context.bot.unban_chat_member(gid, uid)
                await q.edit_message_text("✅ User has been unbanned.")
            except Exception as e:
                logger.error(f"Unban error: {e}")
                await q.answer("❌ Failed to unban.", show_alert=True)
            return

        if data.startswith("warnadd_"):
            _, gid, uid = data.split("_")
            gid, uid = int(gid), int(uid)
            user_warnings.setdefault(gid, {})
            user_warnings[gid][uid] = user_warnings[gid].get(uid, 0) + 1
            warn_count = user_warnings[gid][uid]
            await q.answer(f"✅ Warning increased to {warn_count}.", show_alert=True)
            return

        if data.startswith("warndec_"):
            _, gid, uid = data.split("_")
            gid, uid = int(gid), int(uid)
            user_warnings.setdefault(gid, {})
            current = user_warnings[gid].get(uid, 0)
            if current > 0:
                user_warnings[gid][uid] = current - 1
            await q.answer(f"✅ Warning decreased to {user_warnings[gid][uid]}.", show_alert=True)
            return

        if data.startswith("warnreset_"):
            _, gid, uid = data.split("_")
            gid, uid = int(gid), int(uid)
            user_warnings.setdefault(gid, {})
            user_warnings[gid][uid] = 0
            await q.answer("✅ Warnings have been reset.", show_alert=True)
            return

        if data.startswith("custom_settings_"):
            gid = int(data.rsplit("_", 1)[1])
            return await show_custom_settings(q, gid)

        if data.startswith("toggle_custom_enabled_"):
            gid = int(data.rsplit("_", 1)[1])
            initialize_group_settings(gid)
            s = action_settings[gid]["custom"]
            s["enabled"] = not s["enabled"]
            return await show_custom_settings(q, gid)

        if data.startswith("cycle_custom_action_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["custom"]
            options = ['off', 'mute', 'ban', 'warn']
            s["action"] = options[(options.index(s.get("action", "off")) + 1) % len(options)]
            return await show_custom_settings(q, gid)

        if data.startswith("cycle_custom_warn_count_"):
            gid = int(data.rsplit("_", 1)[1])
            s = action_settings[gid]["custom"]
            count = s.get("warn_count", 1)
            s["warn_count"] = 1 if count >= 3 else count + 1
            return await show_custom_settings(q, gid)

        if data.startswith("change_custom_duration_"):
            gid = int(data.rsplit("_", 1)[1])
            opts = ["30m", "1h", "6h", "1d", "3d", "7d"]
            cur = action_settings[gid]["custom"]["duration"]
            action_settings[gid]["custom"]["duration"] = opts[(opts.index(cur)+1) % len(opts)]
            return await show_custom_settings(q, gid)

        if data.startswith("add_custom_message_"):
            gid = int(data.rsplit("_", 1)[1])
            user_state[uid] = {"state": "awaiting_custom_message", "gid": gid}
            await q.edit_message_text(
                "✏️ Please send your custom messages, separated by spaces like:\n\n"
                "`bio ib number`\n\n"
                "📌 Each word will be saved individually.",
                parse_mode="Markdown"
            )
            return

        await q.answer("❓ Unknown button!", show_alert=True)

    except Exception as e:
        logger.error(f"Callback Error: {e}")
        await q.edit_message_text("❌ Something went wrong, please try again.")
        
async def is_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # Allow if sender is same as the group/channel itself (e.g., via @channelusername)
    if user_id == chat_id:
        return True

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False

from datetime import datetime, timezone

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    if sender_chat and sender_chat.id == chat.id:
        is_allowed = True
    elif user:
        is_allowed = await is_admin(chat.id, user.id, context)
    else:
        is_allowed = False

    if not is_allowed:
        return await message.reply_text("❌ Only admins can use this command.")

    if not message.reply_to_message:
        return await message.reply_text("⛔ You must reply to a user's message to use this command.")

    target_id = message.reply_to_message.from_user.id
    duration = parse_duration(" ".join(context.args) if context.args else "1h")
    until_date = datetime.now(timezone.utc) + duration

    await context.bot.ban_chat_member(chat.id, target_id, until_date=until_date)
    await message.reply_text(f"🚫 User has been banned for {format_duration(duration)}.")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    # اگر چیٹ خود (group/ch) نے بھیجا ہے، تو allow کریں
    if sender_chat and sender_chat.id == chat.id:
        is_allowed = True
    elif user:
        is_allowed = await is_admin(chat.id, user.id, context)
    else:
        is_allowed = False

    if not is_allowed:
        return await message.reply_text("❌ Only admins can use this command.")

    if not message.reply_to_message:
        return await message.reply_text("⛔ You must reply to a user's message to use this command.")

    target_id = message.reply_to_message.from_user.id
    duration = parse_duration(" ".join(context.args) if context.args else "1h")
    until_date = datetime.utcnow() + duration

    permissions = ChatPermissions(can_send_messages=False)
    await context.bot.restrict_chat_member(chat.id, target_id, permissions=permissions, until_date=until_date)
    await message.reply_text(f"🔇 User has been muted for {format_duration(duration)}.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    if sender_chat and sender_chat.id == chat.id:
        is_allowed = True
    elif user:
        is_allowed = await is_admin(chat.id, user.id, context)
    else:
        is_allowed = False

    if not is_allowed:
        return await message.reply_text("❌ Only admins can use this command.")

    if not message.reply_to_message:
        return await message.reply_text("⛔ You must reply to a user's message to use this command.")

    target_id = message.reply_to_message.from_user.id
    await context.bot.unban_chat_member(chat.id, target_id)
    await message.reply_text("✅ User has been unbanned.")

from telegram import ChatPermissions

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    if sender_chat and sender_chat.id == chat.id:
        is_allowed = True
    elif user:
        is_allowed = await is_admin(chat.id, user.id, context)
    else:
        is_allowed = False

    if not is_allowed:
        return await message.reply_text("❌ Only admins can use this command.")

    if not message.reply_to_message:
        return await message.reply_text("⛔ You must reply to a user's message to use this command.")

    target_id = message.reply_to_message.from_user.id

    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_photos=True,
        can_send_documents=True
    )

    await context.bot.restrict_chat_member(chat.id, target_id, permissions=permissions)
    await message.reply_text("🔓 User has been unmuted with limited permissions (messages, photos, documents).")

user_warnings = {}

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id  # ✅ یہ لائن missing تھی
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    # اگر چیٹ خود (group/channel) نے بھیجا ہے، تو allow کریں
    if sender_chat and sender_chat.id == chat.id:
        is_allowed = True
    elif user:
        is_allowed = await is_admin(chat.id, user.id, context)
    else:
        is_allowed = False

    if not is_allowed:
        return await message.reply_text("❌ Only admins can use this command.")

    if not message.reply_to_message:
        return await message.reply_text("⛔ You must reply to a user's message to use this command.")

    target = message.reply_to_message.from_user.id

    # Warning count increase
    user_warnings.setdefault(chat_id, {})  # اگر group کا warning dict نہیں بنا، تو بنا دو
    user_warnings[chat_id][target] = user_warnings[chat_id].get(target, 0) + 1

    await message.reply_text(
        f"⚠️ {message.reply_to_message.from_user.mention_html()} has been warned!\n"
        f"Current warnings: {user_warnings[chat_id][target]}",
        parse_mode="HTML"
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message or update.edited_message
    sender_chat = message.sender_chat if message else None
    user = update.effective_user

    print(f"⚙️ settings_command called in chat_id: {chat.id} | type: {chat.type}")

    # ✅ CASE 1: If sender_chat exists and is same as chat (means group itself sent the command)
    if sender_chat and sender_chat.id == chat.id:
        print("✅ Command sent by group/channel itself — allowing access.")
        await show_group_settings(update, chat.id)
        return

    # ✅ CASE 2: If user is a real user, check if they are admin
    if user:
        user_id = user.id
        print(f"👤 Command sent by user ID: {user_id}")
        is_admin_result = await is_admin(chat.id, user_id, context)
        print(f"🔍 is_admin check result: {is_admin_result}")

        if is_admin_result:
            print("✅ Admin verified — allowing access.")
            await show_group_settings(update, chat.id)
            return
        else:
            print("🚫 User is not admin — access denied.")
            await message.reply_text("❌ This command requires admin privileges.")
            return

    # ❌ If neither sender_chat nor user matched
    print("❌ Could not verify sender — access denied.")
    await message.reply_text("❌ Unable to verify sender identity.")
    
async def back_to_settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat = query.message.chat
    user = query.from_user

    if chat.type in ["group", "supergroup"]:
        if await is_admin(chat.id, user.id, context):
            return await show_group_settings(query, chat.id)
        else:
            return await query.answer("⚠️ Only admins can access group settings.", show_alert=True)
    else:
        return await start(update, context)


# ✅ /set_timer command
async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 2:
        channel_username = context.args[0]
        time_str = context.args[1]

        seconds = parse_time(time_str)
        if seconds is None:
            await update.message.reply_text("⚠️ Invalid time format. Use like: 30s, 2m, 1h, 1d")
            return

        channel_timers[channel_username] = seconds
        await update.message.reply_text(f"✅ Timer for {channel_username} set to {time_str} ({seconds} seconds)")
    else:
        await update.message.reply_text("⚠️ Usage: /set_timer <channel_username> <time>\nExample: /set_timer @mychannel 1h")

channel_timers = {}  # key: "@channelusername", value: timer in seconds
action_settings = {}  # key: chat_id, value: dict of settings

import os
from telegram import Update
from telegram.ext import ContextTypes

async def send_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("🚨 send_backup called")  # ✅ debug line
    try:
        chat_id = update.effective_chat.id
        message = update.effective_message

        print(f"📥 Chat ID: {chat_id}, Message ID: {message.message_id}")  # ✅ debug line
        await message.reply_text("📦 Sending backup files...")

        file_path = "bot.py"

        if os.path.exists(file_path):
            print("📁 File found, sending...")  # ✅ debug line
            with open(file_path, "rb") as f:
                await context.bot.send_document(chat_id, document=f)
        else:
            print("❌ File not found!")  # ✅ debug line
            await message.reply_text("❌ bot.py file not found.")
    except Exception as e:
        print(f"❌ Error in send_backup: {e}")
        try:
            await update.effective_message.reply_text(f"⚠️ Error while sending files: {e}")
        except:
            pass

async def check_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🚨 check_words called")  # ✅ debug line
    chat_id = update.effective_chat.id

    if chat_id not in action_settings:
        print("ℹ️ Chat ID not in action_settings")  # ✅ debug line
        await update.message.reply_text("✅ No custom words set for this chat.")
        return

    if not action_settings[chat_id]["custom"]["messages"]:
        print("ℹ️ No custom messages set")  # ✅ debug line
        await update.message.reply_text("✅ No custom words set for this chat.")
        return

    words = action_settings[chat_id]["custom"]["messages"]
    word_list = "\n- ".join(words)
    print(f"📄 Word list: {word_list}")  # ✅ debug line

    await update.message.reply_text(f"🚫 Custom Words Set:\n\n- {word_list}")
    
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # اگر چینل پوسٹ ہو
    if update.channel_post:
        await handle_channel_post(update, context)

# ✅ Channel Post Handler
# ✅ Channel Post Handler (Updated)
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat_id = message.chat_id
    chat_username = update.effective_chat.username

    if not chat_username:
        print(f"⚠️ No username for chat_id {chat_id}, skipping")
        return

    key = f"@{chat_username}"
    
    # ❌ اگر اس چینل کے لیے timer سیٹ نہیں کیا گیا، تو کچھ نہ کرو
    if key not in channel_timers:
        print(f"⏩ No timer set for {key}, skipping message delete.")
        return

    timer = channel_timers[key]

    await asyncio.sleep(timer)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        print(f"🗑️ Deleted message {message.message_id} from {key} after {timer}s")
    except Exception as e:
        print(f"❌ Failed to delete message {message.message_id}: {e}")


# Start polling
if __name__ == "__main__":
    TOKEN = "..."  
    app = ApplicationBuilder().token(TOKEN).build()

    # 🔹 Priority commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", show_help))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CallbackQueryHandler(start, pattern="^force_start$"))
    app.add_handler(CommandHandler("set", set_timer))
    app.add_handler(CommandHandler("check", check_words))
    app.add_handler(CommandHandler('backup', send_backup))

    # 🔹 First priority: message filters
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, custom_message_input_handler), group=9)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_filter_handler), group=10)

    # 🔹 Buttons
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(back_to_settings_handler, pattern="^back_to_settings$"))

    # 🔹 Lowest priority: catch-all handler (last!)
    app.add_handler(MessageHandler(filters.ALL, handle_all_messages), group=20)

    print("🤖 Bot is running...")
    app.run_polling()