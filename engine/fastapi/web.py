import uvicorn
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from oauthlib.oauth2 import InvalidGrantError
from multiprocessing import Queue

from engine.global_params import UVICORN_PORT, LISTEN_IP, PRIVATE_KEY, CERTIFICATE, CERT_PASS
from engine.gcalendar.gcal_handlers import get_authz_token, CREDENTIALS_KEY, STATE_KEY

# Queue for communication from web process to Telegram process; bool is a poison value
ipc_queue: Queue
app = FastAPI()


@app.get("/oauth2callback", response_class=HTMLResponse)
def oauth2callback(state: str, request: Request, error: str = None):
    # No explicit webpage needed, so page can be closed
    exit_js_script = "<script>window.close()</script>"

    if error is not None:
        ipc_data = {STATE_KEY: state}
        ipc_queue.put(obj=ipc_data, block=False)
        return exit_js_script

    try:
        credentials = get_authz_token(callback_url=str(request.url), state=state)
    except InvalidGrantError:
        logging.warning("Invalid authorization grant code received")
        return exit_js_script

    ipc_data = {CREDENTIALS_KEY: credentials, STATE_KEY: state}
    ipc_queue.put(obj=ipc_data, block=False)
    return exit_js_script


def start_web(queue: Queue) -> None:
    global ipc_queue
    ipc_queue = queue
    uvicorn.run("engine.fastapi.web:app", host=LISTEN_IP, port=UVICORN_PORT, ssl_certfile=CERTIFICATE,
                ssl_keyfile=PRIVATE_KEY)
