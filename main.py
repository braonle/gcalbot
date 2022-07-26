import logging
import signal
from multiprocessing import Process, Queue
from engine.fastapi.web import start_web
from engine.tg.tg_handlers import start_bot

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

if __name__ == '__main__':
    # Queue for communication from web process to Telegram process; bool is a poison value
    ipc_queue = Queue()

    # OAuth2 authorization code receiving process
    web_process = Process(target=start_web, args=(ipc_queue,))
    web_process.start()

    # Telegram process
    tg_process = Process(target=start_bot, args=(ipc_queue,))
    tg_process.start()

    # Allow child processes to exit gracefully on signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    web_process.join()
    tg_process.join()
