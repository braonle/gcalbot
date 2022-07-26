from peewee import SqliteDatabase, Model, TextField, IntegerField
from ..global_params import DB_NAME


class BaseModel(Model):
    class Meta:
        database = SqliteDatabase(DB_NAME)


class GCalendarCred(BaseModel):
    chat_id = IntegerField(unique=True)
    credentials = TextField()


def create_credentials(chat_id: int, credentials: str) -> None:
    """
        Create new credentials. No check

        :param: chat_id: ID of Telegram chat as a key in database
        :param: credentials: Google API credentials as JSON string
    """
    if not GCalendarCred.select().where(GCalendarCred.chat_id == chat_id).exists():
        GCalendarCred.create(chat_id=chat_id, credentials=credentials)


def credentials_exists(chat_id: int) -> bool:
    """
        Check if credentials for chat exist

        :param: chat_id: ID of Telegram chat as a key in database

        :return: True if exists, False otherwise
    """
    return GCalendarCred.select().where(GCalendarCred.chat_id == chat_id).exists()


def get_credentials(chat_id: int) -> str:
    """
        Retrieve credentials for chat

        :param: chat_id: ID of Telegram chat as a key in database

        :return: Google API credentials as JSON string
    """
    return GCalendarCred.get(GCalendarCred.chat_id == chat_id).credentials


def update_credentials(chat_id: int, credentials: str) -> None:
    """
        Update existing credentials for chat

        :param: chat_id: ID of Telegram chat as a key in database
        :param: credentials: Google API credentials as JSON string
    """
    record = GCalendarCred.get(GCalendarCred.chat_id == chat_id)
    record.credentials = credentials
    record.save()


def delete_credentials(chat_id: int) -> None:
    """
        Delete existing credentials for chat

        :param: chat_id: ID of Telegram chat as a key in database
    """
    GCalendarCred.delete().where(GCalendarCred.chat_id == chat_id).execute()
