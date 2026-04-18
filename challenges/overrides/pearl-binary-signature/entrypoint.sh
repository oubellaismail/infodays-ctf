#!/bin/sh
set -e
export FLAG="${FLAG:-INFODAYS{4G4D1R_ST3G4N0GR4PHY_M4ST3R_2030}}"
# Use port 1337 (standard TCP port on our platform)
export PORT=1337
exec python3 -c "
import os, socket

SECRET_CODE = 'a25fd3c8373'
FLAG = os.environ['FLAG']
PORT = int(os.environ.get('PORT', 1337))

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('0.0.0.0', PORT))
srv.listen(5)
print(f'Listening on port {PORT}...', flush=True)

while True:
    conn, _ = srv.accept()
    conn.sendall(b'--- Agadir Stadium Access Control ---\n')
    conn.sendall(b'Enter the 11-hex Architect Signature: ')
    data = conn.recv(1024).decode().strip()
    if data == SECRET_CODE:
        conn.sendall(f'\n[+] Access Granted! Here is your flag: {FLAG}\n'.encode())
    else:
        conn.sendall(b'\n[!] Access Denied. Wrong signature.\n')
    conn.close()
"
