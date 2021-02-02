import socket
import re
import datetime
import sys

#python3 client.py 10.10.1.100 8000 4096 1024 hh.txt hhout.txt large.txt largeout.txt 
#python3 client.py 10.10.1.100 8000 4096 1024 hh.txt hhout.txt small.txt smallout.txt

RDP_reg = re.compile(r'^((DAT|SYN|ACK|FIN|\|)+)\r\nSequence: (\d*)\r\nLength: (\d*)\r\nAcknowledgment: (-?\d*)\r\nWindow: (\d*)\r\n\r\n((\S|\s)*)')
HTTP_reg = re.compile(r'^HTTP/1.0 200 OK\r\n(((\S|\s)*?: (\d*)(\S|\s)*?)\r\n\r\n)((\S|\s)*)')

#main
def main():

    s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #creates socket, UDP connection
    try:
        s.bind(('', 0)) #ip, port (that's available)
    except:
        print("Server failed to bind")
        sys.exit()

    server_dest = (sys.argv[1], int(sys.argv[2]))
    buffer_size = int(sys.argv[3])
    payload_len = int(sys.argv[4])

    #put all file requests into a list as tuples (filename, output filename)
    req = 5
    requests = []
    while req < len(sys.argv):
        requests.append((sys.argv[req], sys.argv[req+1]))
        req = req + 2
    #print(requests)
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #CONNECTION ESTABLISHMENT
    seq = 0
    ack = -1
    win = buffer_size

    s.settimeout(1)
    packet = packRDP('SYN', seq, 0, ack, win, '')
    s.sendto(bytes(packet,'utf-8'), server_dest) #sends SYN

    while True:
        try:    # to recieve a syn ack
            incoming = unpackRDP(s.recvfrom(6144)[0].decode())
            #if incoming == None:
                #RST might move to method
            break
        except socket.timeout:  #resend
            packet = packRDP('SYN', seq, 0, ack, win, '')
            s.sendto(bytes(packet,'utf-8'), server_dest) #sends SYN

    serv_seq = int(incoming[1])  #will be 0
    serv_ack = int(incoming[3])  #will be 1
    serv_win = int(incoming[4])

    seq = serv_ack
    ack = serv_ack
    #next expected server seq is serv_ack + serv_seq
    next_serv_seq = serv_ack + serv_seq

    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #SEND REQUESTS + ACK + RECEIVE
    #send all in one and subsequent ones if needed
    for x in requests:
        sent = False
        content_len = 0
        written_len = 0
        filein = x[0]
        fileout = x[1]
        while sent == False:
            outgoing = packHTTP(filein)
            outgoing = packRDP('DAT|ACK', seq, len(outgoing), ack, win, outgoing)
            s.sendto(bytes(outgoing,'utf-8'), server_dest)  #send DAT|ACK
            try:    #recv
                catch_up = True
                while catch_up: #left over extra packets from prev request
                    incoming = unpackRDP(s.recvfrom(6144)[0].decode())  #(command, seq, length, ack, win, payload)
                    if next_serv_seq == int(incoming[1]):
                        catch_up = False
                        sent = True
                        #put rst for packet size here? idk
                        #window doesn't change bc it's written before ack
                        payload_HTTP = unpackHTTP(incoming[5])  #might be buggy here if no payload but it shouldn;t
                        if payload_HTTP == None:
                            written_len = 0
                            content_len = 0
                        else:
                            writeto(payload_HTTP[0], fileout) #write to file
                            written_len = written_len + len(payload_HTTP[0])
                            content_len = int(payload_HTTP[1])
                        seq = int(incoming[3])
                        ack = int(incoming[1]) + int(incoming[2])
                        send_ack = packRDP('ACK', seq, 0, ack, win, '')
                        s.sendto(bytes(send_ack,'utf-8'), server_dest)
                        next_serv_seq = ack

                    elif next_serv_seq < int(incoming[1]):    #if incoming is larger than a packet is missing but req was sent successfully
                        catch_up = False
                        #send most recent ack
                        send_ack = packRDP('ACK', seq, 0, ack, win, '')
                        s.sendto(bytes(send_ack,'utf-8'), server_dest)
                        sent = True
                    else:
                        #if dat seq smaller then it's extra packets left over
                        #print('here')
                        continue
            except socket.timeout:
                continue

        #has successfully sent request to server at this point
        recv_all = False
        while recv_all == False:
            if written_len != content_len:
                try:    #recv
                    incoming = unpackRDP(s.recvfrom(6144)[0].decode())
                    if next_serv_seq == int(incoming[1]):
                        #window doesn't change bc it's written before ack
                        writeto(incoming[5], fileout) #write to file
                        written_len = written_len + len(incoming[5])
                        seq = int(incoming[3])
                        ack = int(incoming[1]) + int(incoming[2])
                        #content_len = payload_HTTP[1]
                        send_ack = packRDP('ACK', seq, 0, ack, win, '')
                        s.sendto(bytes(send_ack,'utf-8'), server_dest)
                        next_serv_seq = ack
                    else:
                        #send last ack
                        send_ack = packRDP('ACK', seq, 0, ack, win, '')
                        s.sendto(bytes(send_ack,'utf-8'), server_dest)
                except socket.timeout:
                    #need to wait for server to resend lost packets
                    continue
            else:
                break
                #goes to next request


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #CONNECTION CLOSE

    #try to recieve FIN|ACK if want compatibility
    clear = False
    while clear == False:
        try:
            incoming = unpackRDP(s.recvfrom(6144)[0].decode())
            if incoming[0] == 'FIN|ACK':
                clear = True
                ack = ack + 1
            else:
                continue
        except socket.timeout: 
            break 

    #send one instead or send reponse
    packet = packRDP('FIN|ACK', seq, 0, ack, win, '')
    s.sendto(bytes(packet,'utf-8'), server_dest)
    clear == False
    while clear == False:
        try:
            incoming = unpackRDP(s.recvfrom(6144)[0].decode())
            if incoming[0] == 'FIN|ACK':
                clear = True
                ack = ack + 1
                seq = int(incoming[3])
                packet = packRDP('ACK', seq, 0, ack, win, '')
                s.sendto(bytes(packet,'utf-8'), server_dest)
            else:
                break
        except socket.timeout: 
            packet = packRDP('FIN|ACK', seq, 0, ack, win, '')
            s.sendto(bytes(packet,'utf-8'), server_dest)
            clear == False

    s.close()
    sys.exit()

#packages RDP packet to be sent plus prints log for that
def packRDP(command, seq, length, ack, win, payload):
    packet = command + '\r\nSequence: ' + str(seq) + '\r\nLength: ' + str(length) + '\r\nAcknowledgment: ' + str(ack) + '\r\nWindow: ' + str(win) + '\r\n\r\n' + payload
    print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; " + command + '; Sequence: ' + str(seq) + '; Length: ' + str(length) + '; Acknowledgment: ' + str(ack) + '; Window: ' + str(win))
    return packet

def packHTTP(filename):
    packet = 'GET /' + filename + ' HTTP/1.0\r\nConnection: keep-alive\r\n\r\n'
    return packet

#takes RDP packet and returns tuple with (command, seq, length, ack, win, payload) or None if not valid
def unpackRDP(incoming):
    match_RDP = RDP_reg.match(incoming)
    if match_RDP:
        #print log
        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; " + match_RDP.group(1) + '; Sequence: ' + match_RDP.group(3) + '; Length: ' + match_RDP.group(4) + '; Acknowledgment: ' + match_RDP.group(5) + '; Window: ' + match_RDP.group(6))
        values = (match_RDP.group(1), match_RDP.group(3), match_RDP.group(4), match_RDP.group(5), match_RDP.group(6), match_RDP.group(7)) #command, seq, length, ack, win, payload
        return values
    else:
        #maybe put rst here?
        return None
    
def unpackHTTP(incoming):
    match_HTTP = HTTP_reg.match(incoming)
    if match_HTTP:
        payload_and_len = (match_HTTP.group(6), match_HTTP.group(4))    #payload, content length
        return payload_and_len
    elif incoming[:21] == 'HTTP/1.0 404 Not Found':
        return None
    else:
        #rst??
        return None

def writeto(payload, filename):
    file = open(filename, 'a')
    file.write(payload)
    file.close()

if __name__ == "__main__":
    main()