import engine.gcalendar.gcal_handlers as gcal

TG_HELP = \
    """
Управление доступом к Google Calendar

Команды:
/start - вызов кнопочного меню
/help - показать справку
/show_calendars - показать календари
/show_share <calendar> - показать, у кого есть доступ к просмотру календаря
/add_share <calendar> <e-mail> <role> - добавить доступ e-mail на чтение календаря calendar
/delete_share <calendar> <e-mail> - отозвать доступ e-mail на чтение календаря calendar
/revoke_authz - отозвать авторизацию бота на доступ к Google Calendar 
"""

TG_UNKNOWN = "Команда не зарегистрирована"
TG_KEYBOARD_ACTIVE = "Другая клавиатура всё ещё активна"
TG_INVALID_ARG_NUM = "Неверное число аргументов, должно быть {num}"
TG_INVALID_ARG_FMT = "Неверный тип аргумента №{position}"
TG_AUTHZ_URL = "Для авторизации gcalbot в Google Calendar пройдите, пожалуйста, по ссылке: {url}"
TG_AUTH_COMPLETE = "Авторизация выполнена успешно"
TG_AUTH_FAILED = "Доступ к календарю не разрешён пользователем"
TG_CALENDAR_NOT_FOUND = "Календарь не найден: {details}"
TG_USER_ADDED = "Пользователь {email} получил доступ '{access_type}' к календарю {calendar}"
TG_USER_DELETED = "Отозван доступ пользователя {email} к календарю {calendar}"
TG_EMAIL_INVALID = "Неверный формат e-mail"
TG_ROLE_INVALID = "Неверная роль, допустимые значения: {values}"
TG_REVOKE_AUTHZ = "Авторизация бота отозвана. Для возобновления работы вызовите /start, чтобы получить ссылку для " \
                  "авторизации"

BUTTON_START = "В начало"
BUTTON_BACK = "Назад"
BUTTON_FINISH = "Завершить"
BUTTON_SHOW_SHARE = "Показать доступ"
BUTTON_ADD_SHARE = "Добавить доступ"
BUTTON_DEL_SHARE = "Отозвать доступ"
BUTTON_REVOKE_AUTHZ = "Отозвать авторизацию"
BUTTON_FREE_BUSY = "Доступ на чтение (только занято/свободно)"
BUTTON_READER = "Доступ на чтение"
BUTTON_WRITER = "Доступ на запись"

PROMPT_INITIAL_MENU = "Выберите каледарь"
PROMPT_SHARE_EMAIL = "Введите e-mail, которому нужно предоставить доступ к календарю {calendar}"
PROMPT_NOT_EMAIL = "Нужно ввести e-mail в качестве параметра"
PROMPT_DELETE_EMAIL = "Введите e-mail, доступ к календарю {calendar} которого нужно отозвать"
PROMPT_CHOOSE_ACTION = "Выберите действие для календаря {calendar}"
PROMPT_CHOOSE_ROLE = "Выберите уровень доступа пользователя {email} к календарю {calendar}"

GCAL_MAP = {
    gcal.FREE_BUSY_READER: "только занято/свободно",
    gcal.READER: "чтение",
    gcal.WRITER: "запись"
}
GCAL_ENTRY = "{email}: {access}"
