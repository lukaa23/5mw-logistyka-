import os, threading, webbrowser
from http.server import ThreadingHTTPServer
from server import Handler

PORT=int(os.environ.get('PORT','8765'))
if __name__=='__main__':
    url=f'http://127.0.0.1:{PORT}'
    http=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    threading.Timer(1,lambda:webbrowser.open(url)).start()
    print('Program działa lokalnie:',url)
    print('Aby zakończyć, zamknij okno lub naciśnij Ctrl+C.')
    try: http.serve_forever()
    except KeyboardInterrupt: http.server_close()
