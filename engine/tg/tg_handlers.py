from typing import Union, List, Tuple
from threading import Event, Thread
from multiprocessing import Queue
from signal import SIGABRT, SIGINT, SIGTERM, signal
from os import linesep
from io import StringIO
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, Updater, CommandHandler, Filters, MessageHandler, ConversationHandler, \
    CallbackQueryHandler, Dispatcher
from telegram.error import BadRequest
from googleapiclient.errors import HttpError
from validate_email import validate_email
from engine import global_params

import logging
import engine.tg.tg_messages as msgs
import engine.sqlite.database as db
import engine.gcalendar.gcal_handlers as gcal

"""Consts for state selection within ConversationHandler"""
(
    STATE_CALENDAR_SELECTION,
    STATE_ACTION_SELECTION,
    STATE_ADD_SHARE,
    STATE_ADD_SHARE_ROLE,
    STATE_DELETE_SHARE,
    STATE_FINISH
) = map(chr, range(0, 6))
STATE_END = ConversationHandler.END

"""Consts for session cache access"""
INITIAL_MSG_KEY = "initial_msg"
INLINE_MSG_KEY = "inline_msg"
INLINE_CALENDAR_KEY = "calendar_name"

"""Separates data from function identifier in callbacks"""
CALLBACK_DELIMITER = '#'


class CustomUpdater(Updater):
    """
        Replaces spinlock with Event(). Shuts down message queue on SIGINT.

        :param: event: stops main thread while workers are active; set by signals
        :param: ipc_queue: passes authorization token from web server to Telegram process; bool interrupts polling;
                            valid value - Dict { gcal.STATE_KEY: state string from OAuth2.0 link,
                                                    gcal.CREDENTIALS_KEY: Google API credentials as JSON string}

    """
    event: Event
    ipc_queue: Queue

    def idle(self, stop_signals: Union[List, Tuple] = (SIGINT, SIGTERM, SIGABRT)) -> None:

        self.event = Event()

        for sig in stop_signals:
            signal(sig, self._signal_handler)

        self.event.wait()

    def _signal_handler(self, signum, frame) -> None:
        super()._signal_handler(signum, frame)
        # Signal IPC worker to exit
        self.ipc_queue.put(True)
        # Unlock idle()
        self.event.set()


def default_keyboard(calendar: str) -> InlineKeyboardMarkup:
    """
        Keyboard with 3 buttons: back to calendar menu, main menu and exit conversation.
        Used while expecting input or as a result of action.

        :param: calendar: Google Calendar name

        :return: InlineKeyboardMarkup object
    """
    callback_start = start.__name__
    callback_finish = finish_conversation.__name__
    callback_back = f"{select_calendar_inline.__name__}{CALLBACK_DELIMITER}{calendar}"
    buttons = [
        [
            InlineKeyboardButton(text=msgs.BUTTON_BACK, callback_data=callback_back),
            InlineKeyboardButton(text=msgs.BUTTON_START, callback_data=callback_start)
        ],
        [
            InlineKeyboardButton(msgs.BUTTON_FINISH, callback_data=callback_finish)
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def calendar_keyboard(calendar: str) -> InlineKeyboardMarkup:
    """
        Keyboard with 5 buttons: calendar menu (3 actions), main menu and exit conversation.

        :param: calendar: Google Calendar name

        :return: InlineKeyboardMarkup object
    """
    callback_add = f"{add_share_inline.__name__}{CALLBACK_DELIMITER}{calendar}"
    callback_show = f"{show_share_inline.__name__}{CALLBACK_DELIMITER}{calendar}"
    callback_delete = f"{delete_share_inline.__name__}{CALLBACK_DELIMITER}{calendar}"
    buttons = [
        [
            InlineKeyboardButton(text=msgs.BUTTON_SHOW_SHARE, callback_data=callback_show)
        ],
        [
            InlineKeyboardButton(text=msgs.BUTTON_ADD_SHARE, callback_data=callback_add)
        ],
        [
            InlineKeyboardButton(text=msgs.BUTTON_DEL_SHARE, callback_data=callback_delete)
        ],
        [
            InlineKeyboardButton(text=msgs.BUTTON_START, callback_data=start.__name__),
            InlineKeyboardButton(msgs.BUTTON_FINISH, callback_data=finish_conversation.__name__)
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def add_share_keyboard(calendar: str, username: str) -> InlineKeyboardMarkup:
    """
        Keyboard with 6 buttons: calendar access role (3 buttons), back to calendar menu, main menu, exit conversation.

        :param: calendar: Google Calendar name
        :param: username: e-mail of the user who is to be granted access to calendar

        :return: InlineKeyboardMarkup object
    """
    callback_freebusy = f"{add_share_inline_freebusy.__name__}{CALLBACK_DELIMITER}{username}"
    callback_reader = f"{add_share_inline_reader.__name__}{CALLBACK_DELIMITER}{username}"
    callback_writer = f"{add_share_inline_writer.__name__}{CALLBACK_DELIMITER}{username}"

    callback_start = start.__name__
    callback_finish = finish_conversation.__name__
    callback_back = f"{select_calendar_inline.__name__}{CALLBACK_DELIMITER}{calendar}"

    buttons = [
        [
            InlineKeyboardButton(text=msgs.BUTTON_FREE_BUSY, callback_data=callback_freebusy)
        ],
        [
            InlineKeyboardButton(text=msgs.BUTTON_READER, callback_data=callback_reader),
            InlineKeyboardButton(text=msgs.BUTTON_WRITER, callback_data=callback_writer)
        ],
        [
            InlineKeyboardButton(text=msgs.BUTTON_BACK, callback_data=callback_back),
            InlineKeyboardButton(text=msgs.BUTTON_START, callback_data=callback_start)
        ],
        [
            InlineKeyboardButton(msgs.BUTTON_FINISH, callback_data=callback_finish)
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def start(update: Update, context: CallbackContext) -> str:
    """
        Provides user with inline keyboard: available calendars, revoke bot authorization to access Google Calendar
        and exit conversation. If no authorization is found in database, user is provided with OAuth2.0 authorization
        link for Google Calendar.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state equal to calendar action selection of exit if no authorization found
    """
    chat_id = update.effective_chat.id

    # If chat has not been authorized (credentials do not exist in DB) - send authorization link
    if not db.credentials_exists(chat_id):
        url, state = gcal.get_authz_link()
        # Save state in global cache to map credentials to correct chat
        context.bot_data[state] = chat_id
        context.bot.send_message(chat_id=chat_id, text=msgs.TG_AUTHZ_URL.format(url=url))
        return STATE_END

    credentials = gcal.str_to_credentials(chat_id=chat_id, creds=db.get_credentials(chat_id))
    calendars = gcal.get_calendars(credentials)

    keyboard = []

    for calendar in calendars:
        callback_data = f"{select_calendar_inline.__name__}{CALLBACK_DELIMITER}{calendar}"
        keyboard.append([InlineKeyboardButton(text=calendar, callback_data=callback_data)])

    keyboard.append(
        [
            InlineKeyboardButton(msgs.BUTTON_REVOKE_AUTHZ, callback_data=revoke_authz_inline.__name__),
            InlineKeyboardButton(msgs.BUTTON_FINISH, callback_data=finish_conversation.__name__)
        ]
    )

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message is not None:
        if INLINE_MSG_KEY in context.chat_data:
            # If another keyboard is active, redirect user to using it instead
            reply_to = context.chat_data[INLINE_MSG_KEY]
            context.bot.send_message(chat_id=chat_id, text=msgs.TG_KEYBOARD_ACTIVE, reply_to_message_id=reply_to)
        else:
            msg = update.message.reply_text(text=msgs.PROMPT_INITIAL_MENU, reply_markup=reply_markup,
                                            disable_notification=True)
            # Message in chat that invoked conversation
            context.chat_data[INITIAL_MSG_KEY] = update.message.message_id
            # Message in chat for user prompts and inline keyboard
            context.chat_data[INLINE_MSG_KEY] = msg.message_id
    else:
        # Command requested via button thus via callback
        update.callback_query.answer()
        # If message is not actually changed and stays the same, BadRequest is thrown
        try:
            update.callback_query.edit_message_text(text=msgs.PROMPT_INITIAL_MENU, reply_markup=reply_markup)
        except BadRequest:
            pass

    return STATE_CALENDAR_SELECTION


def help(update: Update, context: CallbackContext) -> None:
    """
        Command handler. Return help text

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
    """
    context.bot.send_message(chat_id=update.effective_chat.id, text=msgs.TG_HELP)


def unknown_cmd(update: Update, context: CallbackContext) -> None:
    """
        Command handler. Notify user that command is not known or supported

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
    """
    context.bot.send_message(chat_id=update.effective_chat.id, text=msgs.TG_UNKNOWN)


def __show_calendars(chat_id: int) -> str:
    """
        Internal function. Retrieves available Google calendars and returns a string with their names

        :param: chat_id: ID of Telegram chat as a key in database

        :return: string with calendar names available
    """
    credentials = gcal.str_to_credentials(chat_id=chat_id, creds=db.get_credentials(chat_id))
    calendars = gcal.get_calendars(credentials)

    calendar_lines = StringIO()
    for rec in calendars:
        calendar_lines.writelines(rec)
        calendar_lines.writelines(linesep)

    return calendar_lines.getvalue()


def __show_share(chat_id: int, calendar: str) -> str:
    """
        Internal function. Retrieves users who have access to calendar and returns a string with their e-mails

        :param: chat_id: ID of Telegram chat as a key in database
        :param: calendar: name of Google Calendar that is queried

        :return: string with e-mails of users and their role who have access to calendar
    """
    credentials = gcal.str_to_credentials(chat_id=chat_id, creds=db.get_credentials(chat_id))
    users_list = gcal.get_acl_users(creds=credentials, calendar=calendar)

    users = StringIO()
    for rec in users_list:
        line = msgs.GCAL_ENTRY.format(email=rec["name"], access=msgs.GCAL_MAP[rec["role"]])
        users.writelines(line)
        users.writelines(linesep)

    return users.getvalue()


def __add_share(chat_id: int, calendar: str, email: str, access_type: str) -> str:
    """
        Internal function. Grants user with an access to calendar.

        :param: chat_id: ID of Telegram chat as a key in database
        :param: calendar: name of Google Calendar that is queried
        :param: email: e-mail of the user who is granted access
        :param: access_type: Google Calendar role granted: freeBusyUser, reader, writer

        :return: report string to send to chat
    """
    credentials = gcal.str_to_credentials(chat_id=chat_id, creds=db.get_credentials(chat_id))
    gcal.add_acl_user(creds=credentials, calendar=calendar, username=email, access_type=access_type)

    return msgs.TG_USER_ADDED.format(email=email, access_type=access_type, calendar=calendar)


def __delete_share(chat_id: int, calendar: str, email: str) -> str:
    """
        Internal function. Revokes user's access to calendar.

        :param: chat_id: ID of Telegram chat as a key in database
        :param: calendar: name of Google Calendar that is queried
        :param: email: e-mail of the user whose access is revoked

        :return: report string to send to chat
    """
    credentials = gcal.str_to_credentials(chat_id=chat_id, creds=db.get_credentials(chat_id))
    gcal.delete_acl_user(creds=credentials, calendar=calendar, username=email)

    return msgs.TG_USER_DELETED.format(email=email, calendar=calendar)


def __revoke_authz(chat_id: int) -> str:
    """
        Internal function. Revokes bot's authorization to access Google Calendar on behalf of the user.

        :param: chat_id: ID of Telegram chat as a key in database

        :return: report string to send to chat
    """
    db.delete_credentials(chat_id)
    return msgs.TG_REVOKE_AUTHZ


def show_calendars(update: Update, context: CallbackContext) -> None:
    """
        Command handler. Sends list of available calendars to chat

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
    """
    chat_id = update.effective_chat.id
    text = __show_calendars(chat_id)

    context.bot.send_message(chat_id=chat_id, text=text)


def show_share(update: Update, context: CallbackContext) -> None:
    """
        Command handler. Sends list of users who have access to the specified calendar

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
    """
    chat_id = update.effective_chat.id

    # Check if the number of arguments is correct
    if len(context.args) != 1:
        response = msgs.TG_INVALID_ARG_NUM.format(num=1)
        context.bot.send_message(chat_id=chat_id, text=response)
        return

    calendar = str(context.args[0])

    try:
        text = __show_share(chat_id, calendar)
    except HttpError as e:
        context.bot.send_message(chat_id=chat_id, text=msgs.TG_CALENDAR_NOT_FOUND.format(details=str(e.error_details)))
        return

    context.bot.send_message(chat_id=chat_id, text=text)


def add_share(update: Update, context: CallbackContext) -> None:
    """
        Command handler. Provides user with specified access to the calendar.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
    """
    chat_id = update.effective_chat.id

    # Check if the number of arguments is correct
    if len(context.args) != 3:
        response = msgs.TG_INVALID_ARG_NUM.format(num=3)
        context.bot.send_message(chat_id=chat_id, text=response)
        return

    calendar = context.args[0]
    email = context.args[1]
    role = context.args[2]

    # Validate user input e-mail
    valid = validate_email(email, check_format=True, check_blacklist=False, check_dns=False, check_smtp=False)
    if not valid:
        response = msgs.TG_EMAIL_INVALID
        context.bot.send_message(chat_id=chat_id, text=response)
        return

    # Validate Google Calendar access role
    keys = msgs.GCAL_MAP.keys()
    if role not in keys:
        response = msgs.TG_ROLE_INVALID.format(values=str(list(keys)))
        context.bot.send_message(chat_id=chat_id, text=response)
        return

    try:
        text = __add_share(chat_id, calendar, email, role)
    except HttpError as e:
        context.bot.send_message(chat_id=chat_id, text=msgs.TG_CALENDAR_NOT_FOUND.format(details=str(e.error_details)))
        return

    context.bot.send_message(chat_id=chat_id, text=text)


def delete_share(update: Update, context: CallbackContext) -> None:
    """
        Command handler. Revokes user access to specified calendar

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
    """
    chat_id = update.effective_chat.id

    # Check if the number of arguments is correct
    if len(context.args) != 2:
        response = msgs.TG_INVALID_ARG_NUM.format(num=2)
        context.bot.send_message(chat_id=chat_id, text=response)
        return

    calendar = context.args[0]
    email = context.args[1]

    # Validate user input e-mail
    valid = validate_email(email, check_format=True, check_blacklist=False, check_dns=False, check_smtp=False)
    if not valid:
        response = msgs.TG_EMAIL_INVALID
        context.bot.send_message(chat_id=chat_id, text=response)
        return

    try:
        text = __delete_share(chat_id, calendar, email)
    except HttpError as e:
        context.bot.send_message(chat_id=chat_id, text=msgs.TG_CALENDAR_NOT_FOUND.format(details=str(e.error_details)))
        return

    context.bot.send_message(chat_id=chat_id, text=text)


def revoke_authz(update: Update, context: CallbackContext) -> None:
    """
        Command handler. Revoke bot authorization to access Google Calendar on behalf of the user.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
    """
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=update.effective_chat.id, text=__revoke_authz(chat_id))


def select_calendar_inline(update: Update, context: CallbackContext) -> str:
    """
        Conversation callback handler. Generates action keyboard for calendar specified in callback data.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state equal to calendar action selection
    """
    del context
    cmd, calendar = update.callback_query.data.split(CALLBACK_DELIMITER)
    markup = calendar_keyboard(calendar)
    text = msgs.PROMPT_CHOOSE_ACTION.format(calendar=calendar)
    update.callback_query.edit_message_text(text=text, reply_markup=markup)
    return STATE_ACTION_SELECTION


def show_share_inline(update: Update, context: CallbackContext) -> str:
    """
        Conversation callback handler. List users and their access roles for calendar specified in callback data.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state equal to calendar action selection
    """
    del context
    chat_id = update.effective_chat.id
    cmd, calendar = update.callback_query.data.split(CALLBACK_DELIMITER)

    markup = default_keyboard(calendar)
    update.callback_query.edit_message_text(text=__show_share(chat_id, calendar), reply_markup=markup)
    return STATE_ACTION_SELECTION


def add_share_inline(update: Update, context: CallbackContext) -> str:
    """
        Conversation callback handler. Asks for e-mail to share calendar with.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state, waiting for e-mail input to proceed with granting access to calendar.
    """
    cmd, calendar = update.callback_query.data.split(CALLBACK_DELIMITER)
    context.chat_data[INLINE_CALENDAR_KEY] = calendar

    text = msgs.PROMPT_SHARE_EMAIL.format(calendar=calendar)
    update.callback_query.edit_message_text(text=text, reply_markup=default_keyboard(calendar))
    return STATE_ADD_SHARE


def add_share_inline_email(update: Update, context: CallbackContext) -> str:
    """
        Conversation callback handler. Generates keyboard for calendar access role selection after e-mail is provided.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state for selecting share access role (if e-mail was valid) of or waiting for a
                    valid e-mail input.
    """
    chat_id = update.effective_chat.id
    message_id = context.chat_data[INLINE_MSG_KEY]
    calendar = context.chat_data[INLINE_CALENDAR_KEY]

    email = update.message.text
    context.bot.delete_message(update.effective_chat.id, update.effective_message.message_id)

    # Validate e-mail user input
    valid = validate_email(email, check_format=True, check_blacklist=False, check_dns=False, check_smtp=False)
    if not valid:
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msgs.PROMPT_NOT_EMAIL,
                                          reply_markup=default_keyboard(calendar))
        except BadRequest:
            pass

        return STATE_ADD_SHARE

    text = msgs.PROMPT_CHOOSE_ROLE.format(email=email, calendar=calendar)
    context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                  reply_markup=add_share_keyboard(calendar=calendar, username=email))

    return STATE_ADD_SHARE_ROLE


def add_share_inline_role(update: Update, context: CallbackContext, access_type: str) -> str:
    """
        Conversation callback handler. Grants user with specified access role for calendar.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)
        :param: access_type: Google Calendar role granted: freeBusyUser, reader, writer

        :return: ConversationHandler state for selecting calendar action.
    """
    chat_id = update.effective_chat.id
    message_id = context.chat_data[INLINE_MSG_KEY]
    calendar = context.chat_data.pop(INLINE_CALENDAR_KEY)
    cmd, email = update.callback_query.data.split(CALLBACK_DELIMITER)

    text = __add_share(chat_id=chat_id, calendar=calendar, email=email, access_type=access_type)

    context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                  reply_markup=default_keyboard(calendar))

    return STATE_ACTION_SELECTION


def add_share_inline_freebusy(update: Update, context: CallbackContext) -> str:
    return add_share_inline_role(update, context, gcal.FREE_BUSY_READER)


def add_share_inline_reader(update: Update, context: CallbackContext) -> str:
    return add_share_inline_role(update, context, gcal.READER)


def add_share_inline_writer(update: Update, context: CallbackContext) -> str:
    return add_share_inline_role(update, context, gcal.WRITER)


def delete_share_inline(update: Update, context: CallbackContext) -> str:
    """
        Conversation callback handler. Asks for e-mail os the user whose access is to be revoked.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state, waiting for e-mail input to proceed with revoking access to calendar.
    """
    cmd, calendar = update.callback_query.data.split(CALLBACK_DELIMITER)
    context.chat_data[INLINE_CALENDAR_KEY] = calendar

    text = msgs.PROMPT_DELETE_EMAIL.format(calendar=calendar)
    update.callback_query.edit_message_text(text=text, reply_markup=default_keyboard(calendar))
    return STATE_DELETE_SHARE


def delete_share_inline_email(update: Update, context: CallbackContext) -> str:
    """
        Conversation callback handler. Revokes specified user's access to calendar.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state for selecting calendar action.
    """
    chat_id = update.effective_chat.id
    message_id = context.chat_data[INLINE_MSG_KEY]
    calendar = context.chat_data[INLINE_CALENDAR_KEY]

    email = update.message.text
    context.bot.delete_message(update.effective_chat.id, update.effective_message.message_id)

    # Validate user input e-mail
    valid = validate_email(email, check_format=True, check_blacklist=False, check_dns=False, check_smtp=False)
    if not valid:
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msgs.PROMPT_NOT_EMAIL,
                                          reply_markup=default_keyboard(calendar))
        except BadRequest:
            pass

        return STATE_DELETE_SHARE

    text = __delete_share(chat_id=chat_id, calendar=calendar, email=email)

    context.chat_data.pop(INLINE_CALENDAR_KEY)
    context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                  reply_markup=default_keyboard(calendar))

    return STATE_ACTION_SELECTION


def revoke_authz_inline(update: Update, context: CallbackContext) -> str:
    """
        Conversation callback handler. Revokes bot's access to Google Calendar on behalf of the user.

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state returned by cleanup function, should be ConversationHandler.END
    """
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=update.effective_chat.id, text=__revoke_authz(chat_id))
    return finish_conversation(update, context)


def finish_conversation(update: Update, context: CallbackContext) -> str:
    """
        Cleanup cache, keyboard and messages in chat

        :param: update: message info (prototype required by telegram-bot)
        :param: context: session info (prototype required by telegram-bot)

        :return: ConversationHandler state equal to end
    """
    chat_id = update.effective_chat.id

    # Message in chat for user prompts and inline keyboard
    inline_msg_id = context.chat_data.pop(INLINE_MSG_KEY)
    # Message in chat that invoked conversation
    initial_msg_id = context.chat_data.pop(INITIAL_MSG_KEY)
    # Remove input e-mail from cache (might be present if granting access was interrupted in the middle)
    context.chat_data.pop(INLINE_CALENDAR_KEY, None)
    # Cleanup keyboard (otherwise it is should as reply for deleted message)
    context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=inline_msg_id, reply_markup=None)
    context.bot.delete_message(update.effective_chat.id, inline_msg_id)
    context.bot.delete_message(chat_id=chat_id, message_id=initial_msg_id)
    return STATE_END


def webauth_callback(ipc_queue: Queue, dispatcher: Dispatcher) -> None:
    """
        Receives Google Calendar credentials and reports success to user

        :param: ipc_queue: queue for communication from web process to Telegram process; bool is a poison value
                            sent by CustomUpdater._signal_handler() to signal this thread to finish
        :param: dispatcher: python-telegram-object to send report to correct user
    """
    while True:
        ipc_data = ipc_queue.get()

        # Stop listening is bool is received
        if type(ipc_data) is bool:
            break

        # Dict with keys gcal.STATE_KEY and gcal.CREDENTIALS_KEY is expected
        elif type(ipc_data) is dict:
            # State is used to map OAuth2.0 authorization URL to correct chat
            state = ipc_data[gcal.STATE_KEY]
            try:
                chat_id = dispatcher.bot_data.pop(state)
            except KeyError:
                logging.error("No state data found, likely old authorization link was used")
                continue

            # No credentials are passed in case authorization was not granted to bot by user
            try:
                credentials = ipc_data.pop(gcal.CREDENTIALS_KEY)
            except KeyError:
                logging.error(f"No authorization data received because user {chat_id} denied access")
                dispatcher.bot.send_message(chat_id=chat_id, text=msgs.TG_AUTH_FAILED)
                continue

            db.create_credentials(chat_id=chat_id, credentials=credentials)
            dispatcher.bot.send_message(chat_id=chat_id, text=msgs.TG_AUTH_COMPLETE)
        else:
            logging.error(f"Unknown type received from web process{type(ipc_data)}")


def start_bot(ipc_queue: Queue) -> None:
    """
        Authenticate, authorize to Telegram; initialize handlers; start polling or webhook; start thread listening
        for Google API credentials from web process (OAuth2.0 redirect URL callback)

        :param: ipc_queue: queue for communication from web process to Telegram process; bool is a poison value
                            sent by CustomUpdater._signal_handler() to signal this thread to finish

    """
    updater = CustomUpdater(token=global_params.TOKEN, use_context=True)
    updater.ipc_queue = ipc_queue

    # Main menu handlers
    calendar_selection_handlers = [
        CallbackQueryHandler(select_calendar_inline, pattern=f"^{select_calendar_inline.__name__}"),
        CallbackQueryHandler(revoke_authz_inline, pattern=f"^{revoke_authz_inline.__name__}"),
        CallbackQueryHandler(finish_conversation, pattern=f"^{finish_conversation.__name__}$"),
    ]

    action_selection_handlers = [
        CallbackQueryHandler(show_share_inline, pattern=f"^{show_share_inline.__name__}"),
        CallbackQueryHandler(add_share_inline, pattern=f"^{add_share_inline.__name__}"),
        CallbackQueryHandler(delete_share_inline, pattern=f"^{delete_share_inline.__name__}"),
        CallbackQueryHandler(select_calendar_inline, pattern=f"^{select_calendar_inline.__name__}"),
        CallbackQueryHandler(finish_conversation, pattern=f"^{finish_conversation.__name__}$"),
        CallbackQueryHandler(start, pattern=f"^{start.__name__}$")
    ]

    add_share_handlers = [
        MessageHandler(Filters.text & ~Filters.command, add_share_inline_email),
        CallbackQueryHandler(select_calendar_inline, pattern=f"^{select_calendar_inline.__name__}"),
        CallbackQueryHandler(finish_conversation, pattern=f"^{finish_conversation.__name__}$"),
        CallbackQueryHandler(start, pattern=f"^{start.__name__}$")
    ]

    add_share_role_handlers = [
        CallbackQueryHandler(add_share_inline_freebusy, pattern=f"^{add_share_inline_freebusy.__name__}"),
        CallbackQueryHandler(add_share_inline_reader, pattern=f"^{add_share_inline_reader.__name__}"),
        CallbackQueryHandler(add_share_inline_writer, pattern=f"^{add_share_inline_writer.__name__}"),
        CallbackQueryHandler(select_calendar_inline, pattern=f"^{select_calendar_inline.__name__}"),
        CallbackQueryHandler(finish_conversation, pattern=f"^{finish_conversation.__name__}$"),
        CallbackQueryHandler(start, pattern=f"^{start.__name__}$")
    ]

    delete_share_handlers = [
        MessageHandler(Filters.text & ~Filters.command, delete_share_inline_email),
        CallbackQueryHandler(select_calendar_inline, pattern=f"^{select_calendar_inline.__name__}"),
        CallbackQueryHandler(finish_conversation, pattern=f"^{finish_conversation.__name__}$"),
        CallbackQueryHandler(start, pattern=f"^{start.__name__}$")
    ]

    # Button menu handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler(start.__name__, start)],
        states={
            STATE_CALENDAR_SELECTION: calendar_selection_handlers,
            STATE_ACTION_SELECTION: action_selection_handlers,
            STATE_ADD_SHARE: add_share_handlers,
            STATE_ADD_SHARE_ROLE: add_share_role_handlers,
            STATE_DELETE_SHARE: delete_share_handlers
        },
        fallbacks=[CommandHandler(start.__name__, start)]
    )
    updater.dispatcher.add_handler(conv_handler)

    # Generate help prompt and handlers from bot methods available for regular authorized groups
    registered_methods = (help, show_calendars, show_share, add_share, delete_share, revoke_authz)
    for m in registered_methods:
        updater.dispatcher.add_handler(CommandHandler(m.__name__, m))

    # Unknown direct command handlers
    unknown_handler = MessageHandler(Filters.command, unknown_cmd)
    updater.dispatcher.add_handler(unknown_handler)

    if global_params.POLLING_BASED:
        updater.start_polling(poll_interval=global_params.POLL_INTERVAL)
    else:
        updater.start_webhook(listen=global_params.LISTEN_IP, port=global_params.TG_PORT, url_path=global_params.TOKEN,
                          key=global_params.PRIVATE_KEY, cert=global_params.CERTIFICATE,
                          webhook_url=f'https://{global_params.DNS_NAME}:{global_params.TG_PORT}/{global_params.TOKEN}')

    callback_thread = Thread(target=webauth_callback, args=(ipc_queue, updater.dispatcher))
    callback_thread.start()
    updater.idle()
    callback_thread.join()
