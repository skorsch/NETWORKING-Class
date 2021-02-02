import socket
import threading
import re
import datetime
import sys

#python3 sws.py 10.10.1.100 8000
#cat input.txt | nc 10.10.1.100 8000
def handler(clientsocket, address):
    client_ip, client_port = address    #for log stuff
    connected = True
    
    while connected:
        clientsocket.settimeout(60)     #timeout length was unspecified so i set it to one min
        try:
            message_A = ''
            x = 3
            while True:
                message_A = message_A + clientsocket.recv(1024).decode('utf-8')
                x = x - 1
                if message_A[-2:] == '\n\n' or x == 0:  #file has to end in \n\n to work
                    break
            requests = message_A.split('\n\n')       
        
            #for loop for all requests in the file
            for curr in requests:
                alive = False
                if connected == False or curr == '':
                    break
                match_msg = msg_reg.match(curr)
           
                if match_msg:
                    try:
                        return_file = open(match_msg.group(2), "r")
                        send_file = return_file.read()
                        return_file.close()
                        log = 'HTTP/1.0 200 OK'
                    except:
                        log = 'HTTP/1.0 404 Not Found'
                    
                    k = match_msg.group(4)[11:].lower()
                    if match_msg.group(4)[:11].lower() == 'connection:' and keep_alive.match(k):   #BASED ON NGINX BEHAVIOUR
                        connected = True
                        alive = True
                    else: #non persistent
                        connected = False
                else:
                    log = 'HTTP/1.0 400 Bad Request'
                    connected = False

                date_now = datetime.datetime.now()
                if match_msg:
                    print(date_now.strftime("%a %b %d %X PDT %Y") + ": " + str(client_ip) + ":" + str(client_port) + " " + match_msg.group(1) + "; " + log)
                else:
                    first = curr.split('\n')
                    print(date_now.strftime("%a %b %d %X PDT %Y") + ": " + str(client_ip) + ":" + str(client_port) + " " + first[0] + "; " + log)
        
                clientsocket.sendall(bytes(log, 'utf-8'))  
                
                if match_msg:
                    if alive: #lowercase these if change (both group and match)
                        clientsocket.sendall(bytes('\n' + 'Connection: keep-alive', 'utf-8'))
                    else:
                        clientsocket.sendall(bytes('\n' + 'Connection: close', 'utf-8'))
                else:
                    clientsocket.sendall(bytes('\n' + 'Connection: close', 'utf-8'))

                clientsocket.sendall(bytes('\n\n', 'utf-8'))  #send blank line
                #send file if not null
                if log == 'HTTP/1.0 200 OK':
                    clientsocket.sendall(bytes(send_file, 'utf-8'))
                    
        except socket.timeout:
                #print('Socket timed out')   It was said that no log is needed for timeouts
                clientsocket.close()
                return
            
    clientsocket.close() #close if non persistent

    
#^(GET /(.*) HTTP/1.0)(\n((Connection: keep-alive)|(Connection: close)))?$
msg_reg = re.compile(r'^(GET /(.*) HTTP/1.0)(\n(.*))?')
keep_alive = re.compile(r'.*(keep-alive).*')  #BASED ON NGINX BEHAVIOUR

s=socket.socket(socket.AF_INET, socket.SOCK_STREAM) #creates socket, TCP connection

#not in the specs but it's a nice precaution
try:
    s.bind((sys.argv[1], int(sys.argv[2]))) #server, port
except:
    ("Server failed to bind")
    sys.exit()
    
s.listen(5)

while True:
    #accept connections from outside
    try:
        clientsocket, address = s.accept() #blocks until connection received
        thread = threading.Thread(target=handler, args=(clientsocket, address)) #start thread for the one client
        thread.start()
    except (KeyboardInterrupt, SystemExit):
        print('\nClosed Server')   #this wasn't specificed but it's a nice output for exiting with ^C
        sys.exit() 
        