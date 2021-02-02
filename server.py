import socket
import threading
import re
import datetime
import sys
import time

#python3 server.py 10.10.1.100 8000 4096 1024

#global dict
threads = {}
#declare regexes here
RDP_reg = re.compile(r'^((DAT|SYN|ACK|FIN|\|)+)\r\nSequence: (\d*)\r\nLength: (\d*)\r\nAcknowledgment: (-?\d*)\r\nWindow: (\d*)\r\n\r\n((\S|\s)*)')
HTTP_reg = re.compile(r'^GET /(.*) HTTP/1.0\r\nConnection: keep-alive\r\n\r\n((\S|\s)*)')

s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #creates socket, UDP connection
    
def main():
    
    try:
        s.bind((sys.argv[1], int(sys.argv[2]))) #ip, port
    except:
        print("Server failed to bind")
        sys.exit()

    global server_buffer
    server_buffer = int(sys.argv[3])
    global server_payload
    server_payload = int(sys.argv[4])

    while True:
        try:
            arrival = s.recvfrom(6144)  #grab any incoming messages
            key = arrival[1]
            message = arrival[0].decode()
            buffer_decrease = int(unpackRDP(message)[2])
            server_buffer = server_buffer - buffer_decrease
            #if message length is larger than we can handle send RST to the key here
            #else
            if key in threads:
                threads[key].append(message)
            else:
                threads[key] = [message]    #add list to a new key
                thread = threading.Thread(target=handler, args=(key[0], key[1])) #start thread for the one client
                thread.start()

        except socket.timeout: #get rid of this?
            continue
            #keep waiting

        except (KeyboardInterrupt, SystemExit):
            print('\nClosed Server')   #this wasn't specificed but it's a nice output for exiting with ^C
            sys.exit()

#threading, key is unique identifier for each thread
def handler(client_ip, client_port):
    key = (client_ip, client_port)
    
    global server_buffer
    global server_payload
    serv_seq = 0
    serv_ack = 1
    next_cl_ack = serv_seq + 1 #serv seq + length

    while True: #keep checking for new messages
        if len(threads[key]) != 0:  #there are messages
            curr_message = threads[key].pop(0)  #extracts and removes message from list
            incoming = unpackRDP(curr_message)  #has: command, seq, length, ack, win, payload
            server_buffer = server_buffer + len(incoming[5])

            if incoming[0] == 'SYN':
                timed_out = True
                while timed_out:
                    #send SYN|ACK
                    send_back = packRDP('SYN|ACK', serv_seq, 0, serv_ack, server_buffer, '')
                    s.sendto(bytes(send_back,'utf-8'), key)
                    serv_seq = serv_ack #is 1 at this point
                    
                    time_out = time.time() + 1
                    while time.time() < time_out:
                        if len(threads) != 0:
                            timed_out = False
                            break #got a message
                        else:
                            continue
                    #else resends

            elif incoming[0] == 'DAT|ACK':
                request = unpackHTTP(incoming[5])
                serv_ack = int(incoming[1]) + int(incoming[2])  #increment ack
                #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                #READ IN FILE
                try:
                    return_file = open(request, "r")
                    send_file = return_file.read()
                    return_file.close()
                except:
                    #return file not found
                    send_back = packHTTP(request, None, 0, client_ip, client_port)  #pack not found
                    bad_len = len(send_back)
                    send_back = packRDP('DAT|ACK', serv_seq, len(send_back), serv_ack, server_buffer, send_back) #pack RDP
                    s.sendto(bytes(send_back,'utf-8'), key) #send
                    serv_seq = serv_seq + bad_len
                    continue

                #could put RST somewhere if client buffer is less than server payload send RST?
                #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                #PACKAGE SPLITTING
                content_len = len(send_file)    #length of file
                cut = 0
                chunks = []
                #added http header then split so the length is correct
                send_file = packHTTP(request, send_file, len(send_file), client_ip, client_port)
                while len(send_file) > cut: #put chunks into a list
                    chunks.append(send_file[cut:(cut + server_payload)])
                    send_file = send_file[server_payload:]

                cl_window = int(incoming[4])
                while len(chunks) != 0: #while theres packets to send
                    send_buff = []
                    while cl_window >= server_payload and len(chunks) != 0:   #send packets until client full
                        #print('send')
                        curr = chunks.pop(0)
                        sending = packRDP('DAT|ACK', serv_seq, len(curr), serv_ack, server_buffer, curr)
                        send_buff.append(sending)
                        serv_seq = serv_seq + len(curr) #increment seq
                        cl_window = cl_window - len(curr)   #decrement window
                        s.sendto(bytes(sending,'utf-8'), key)

                    #start recieving
                    timed_out = True
                    done = False
                    while timed_out:
                        time_out = time.time() + 1 
                        while done == False: #and time left
                            if len(threads[key]) != 0:
                                curr_message = threads[key].pop(0)  #extracts and removes message from list
                                incoming = unpackRDP(curr_message)  #has: command, seq, length, ack, win, payload
                                cl_window = int(incoming[4])
                                if int(incoming[3]) == serv_seq:
                                    done = True
                                    timed_out = False
                                    break
                                while int(incoming[3]) >= int(unpackRDP(send_buff[0])[1]) + int(unpackRDP(send_buff[0])[2]): #while client ack is larger than the seq + len in buffer pop it (don't resend)
                                    send_buff.pop(0)
                                    time_out = time.time() + 1
                            if time.time() > time_out:  #resend send buffer
                                for x in send_buff:
                                    s.sendto(bytes(x,'utf-8'), key)
                                break
                    send_buff = []

            elif incoming[0] == 'ACK':
                serv_ack = int(incoming[1]) + int(incoming[2])
                #print('ACK')
                continue

            elif incoming[0] == 'FIN|ACK':
                #print('FIN|ACK')
                serv_ack = int(incoming[1]) + 1
                timed_out = True
                while timed_out:
                    #send FIN|ACK
                    send_back = packRDP('FIN|ACK', serv_seq, 0, serv_ack, server_buffer, '')
                    s.sendto(bytes(send_back,'utf-8'), key)
                    serv_seq = serv_ack #is 1 at this point
                    
                    time_out = time.time() + 1
                    while time.time() < time_out:
                        if len(threads) != 0:
                            timed_out = False
                            break #got a message
                        else:
                            continue
                    #else resends
                
                #delete key
                del threads[key]
                sys.exit()

            else:
                #rst
                #delete key
                del threads[key]
                sys.exit()
        else:
            continue
            #keep looping

#packages RDP packet to be sent plus prints log for that
def packRDP(command, seq, length, ack, win, payload):
    packet = command + '\r\nSequence: ' + str(seq) + '\r\nLength: ' + str(length) + '\r\nAcknowledgment: ' + str(ack) + '\r\nWindow: ' + str(win) + '\r\n\r\n' + payload
    #print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; " + command + '; Sequence: ' + str(seq) + '; Length: ' + str(length) + '; Acknowledgment: ' + str(ack) + '; Window: ' + str(win))
    return packet

#returns a packet HTTP packet
def packHTTP(request, payload, content_len, client_ip, client_port):
    if payload == None:
        packet = 'HTTP/1.0 404 Not Found\r\nContent-Length: ' + str(content_len) + '\r\nConnection: keep-alive\r\n\r\n'
        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": " + str(client_ip) + ":" + str(client_port) + ' GET /' + request + ' HTTP/1.0; HTTP/1.0 404 Not Found')
    else:
        packet = 'HTTP/1.0 200 OK\r\nContent-Length: ' + str(content_len) + '\r\nConnection: keep-alive\r\n\r\n' + payload
        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": " + str(client_ip) + ":" + str(client_port) + ' GET /' + request + ' HTTP/1.0; HTTP/1.0 200 OK')
    return packet

#takes RDP packet and returns tuple with (command, seq, length, ack, win, payload) or None if not valid
def unpackRDP(incoming):
    match_RDP = RDP_reg.match(incoming)
    if match_RDP:
        #print log
        #print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; " + match_RDP.group(1) + '; Sequence: ' + match_RDP.group(3) + '; Length: ' + match_RDP.group(4) + '; Acknowledgment: ' + match_RDP.group(5) + '; Window: ' + match_RDP.group(6))
        values = (match_RDP.group(1), match_RDP.group(3), match_RDP.group(4), match_RDP.group(5), match_RDP.group(6), match_RDP.group(7)) #command, seq, length, ack, win, payload
        return values
    else:
        #maybe put rst here?
        return None
    
def unpackHTTP(inc):   #return requested file
    match_HTTP = HTTP_reg.match(inc)
    if match_HTTP:
        request = match_HTTP.group(1)   #file
        return request
    else:
        #rst??
        return None

def writeto(payload, filename):
    file = open(filename, 'a')
    file.write(payload)
    file.close()

if __name__ == "__main__":
    main()