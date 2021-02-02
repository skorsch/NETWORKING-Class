import socket
import threading
import re
import datetime
import sys

#h1: python3 rdp2.py 192.168.1.100 8000 test.txt testout.txt
#h2: cat fifo | nc -u -l 8888 > fifo

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#WRITE TO OUTPUT

def write_to(payload, filename):
    file = open(filename, 'a')
    file.write(payload)
    file.close()
    
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#START
    
data_reg = re.compile(r'^(DAT)\r\n(Sequence: (\d*))\r\n(Length: (\d*))\r\n\r\n((\S|\s)*)')
search_reg = re.compile(r'((\S|\s)*?)(DAT)\r\n(Sequence: (\d*))\r\n(Length: (\d*))\r\n\r\n((\S|\s)*)')
ack_reg = re.compile(r'^(ACK)\r\n(Acknowledgment: (\d*))\r\n(Window: (\d*))\r\n\r\n((\S|\s)*)')

s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #creates socket, UDP connection

#not in the specs but it's a nice precaution
try:
    s.bind((sys.argv[1], int(sys.argv[2]))) #ip, port
except:
    ("Server failed to bind")
    sys.exit()

file_in = sys.argv[3]
file_out = sys.argv[4]
seq = 0
ack = 1
length = 0
win = 5120
r_win = 5120

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#CONNECTION ESTABLISHMENT

s.sendto(bytes("SYN\r\nSequence: 0\r\nLength: 0\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #sends SYN
print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; SYN; Sequence: " + str(seq) + "; Length: " + str(length))
resp = False

s.settimeout(1)
while resp == False:
    try:
        if s.recvfrom(1024)[0].decode()[:3] == "SYN":
            print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; SYN; Sequence: " + str(seq) + "; Length: " + str(length))
            #create ACK package here
            s.sendto(bytes("ACK\r\nAcknowledgment: 1\r\nWindow: 2048\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #sends ACK
            print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; ACK; Acknowledgment: " + str(ack) + "; Window: " + str(r_win))
            break  
    except socket.timeout:
        s.sendto(bytes("SYN\r\nSequence: 0\r\nLength: 0\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #resends SYN
        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; SYN; Sequence: " + str(seq) + "; Length: " + str(length))
        
while resp == False:
    try:
        if s.recvfrom(1024)[0].decode()[:3] == "ACK":
            print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; ACK; Acknowledgment: " + str(ack) + "; Window: " + str(r_win))
            break
    except socket.timeout:
        s.sendto(bytes("ACK\r\nAcknowledgment: 1\r\nWindow: 2048\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #resends ACK
        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; ACK; Acknowledgment: " + str(ack) + "; Window: " + str(r_win))
        #s.settimeout(3)

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#READ IN FILE

seq = seq + ack
return_file = open(file_in, "r")
send_file = return_file.read()
return_file.close()

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#PACKAGE SPLITTING AND SENDING AND RECIEVING

if len(send_file)%1024 == 0:
    packets_left = int(len(send_file)/1024) #if file length is divisible by 1024
else:
    packets_left = int((len(send_file)/1024)+1) #if it isn't

#intialize
skip = 0
send_buffer = []
buf = 0
error_ack = 1
last_ack = "ACK\r\nAcknowledgment: 1\r\nWindow: 2048\r\n\r\n"
last_log = ": Send; ACK; Acknowledgment: " + str(ack) + "; Window: " + str(5120)

while packets_left != 0 or skip == 1:
    payload = send_file[:1024]
    length = len(payload)
    win = win - length
    triple = []
    
    if win >= 0 and skip == 0: #send packets
        payload = "DAT\r\nSequence: " + str(seq) + "\r\nLength: " + str(length) + "\r\n\r\n" + payload #format packet
        send_file = send_file[1024:]    #chop file
        s.sendto(bytes(payload,'utf-8'), ('10.10.1.100', 8888)) #sends packet
        DAT_log = datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; DAT; Sequence: " + str(seq) + "; Length: " + str(length)    #logs
        print(DAT_log)  #prints log
        seq = seq + length  #increase the seq for the next one
        ex_ack = seq    #the expected ack to end the recv loop

        packets_left = packets_left - 1 #decrease packets
        if packets_left == 0: #used if there's no packets left but still need to recieve stuff
            skip = 1
        #insert packet into queue
        send_buffer.append(payload)
        buf = buf + 1

    else: #stop and wait for ack
        win = win + length  #put length back
        while True:
            try:
                arrival = s.recvfrom(6144)[0].decode()  #big enough to hold concatenated packages
                match_DAT = data_reg.match(arrival) #match for first packet
                match_ACK = ack_reg.match(arrival)  #match for concatenated packets
               
                if match_DAT: 
                    if int(error_ack) == int(match_DAT.group(3)): #if error_ack equals seq number of incoming packet, nothing was lost
                        try:
                            search_DAT = search_reg.match(match_DAT.group(6)) #try to see concats
                        except IndexError:
                            search_DAT = False
                        #deal with first packet
                        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; DAT; " + match_DAT.group(2) + "; " + match_DAT.group(4))
                        r_win = r_win - int(match_DAT.group(5)) #make window smaller
                        if search_DAT:
                            write_to(search_DAT.group(1), file_out) #write first payload
                        else:
                            write_to(match_DAT.group(6), file_out) #write only payload
                        r_win = r_win + int(match_DAT.group(5)) #make window larger
                        win = win + int(match_DAT.group(5))
                        curr_ack = str(int(match_DAT.group(3)) + int(match_DAT.group(5)))
                        s.sendto(bytes("ACK\r\nAcknowledgment: " + curr_ack + "\r\nWindow: " + str(r_win) + "\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #sends ACK packet
                        #MY WINDOWS STAY CONSTANT BECAUSE I ALWAYS WRITE TO FILE IMMEDIATELY BEFORE ACK
                        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; ACK; Acknowledgment: " + curr_ack + "; Window: " + str(r_win))
                        last_ack = "ACK\r\nAcknowledgment: " + curr_ack + "\r\nWindow: " + str(r_win) + "\r\n\r\n" #for error stuff
                        last_log = ": Send; ACK; Acknowledgment: " + curr_ack + "; Window: " + str(r_win)
                        error_ack = int(curr_ack)
                        #take out of buffer
                        send_buffer.pop(0)

                        while search_DAT:
                            #deal with subsequent packets
                            if int(error_ack) == int(search_DAT.group(5)): #if error_ack equals seq number of incoming packet, nothing was lost
                                print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; DAT; " + search_DAT.group(4) + "; " + search_DAT.group(6))
                                win = win + int(search_DAT.group(7))
                                #decrease reciever window
                                r_win = r_win - int(search_DAT.group(7))
                                curr_ack = str(int(search_DAT.group(5)) + int(search_DAT.group(7)))
                                save_DAT = search_DAT #save the search
                    
                                try: #try to search again
                                    search_DAT = search_reg.match(search_DAT.group(8))
                                except IndexError:
                                    search_DAT = False
                            
                                if search_DAT: #if search is successful 
                                    write_to(search_DAT.group(1), file_out) #write first payload
                                else:
                                    write_to(save_DAT.group(8), file_out) #write second payload
                                #increase reciver window
                                r_win = r_win + int(save_DAT.group(7))
                                s.sendto(bytes("ACK\r\nAcknowledgment: " + curr_ack + "\r\nWindow: " + str(r_win) + "\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #sends ACK packet
                                print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; ACK; Acknowledgment: " + curr_ack + "; Window: " + str(r_win))
                                last_ack = "ACK\r\nAcknowledgment: " + curr_ack + "\r\nWindow: " + str(r_win) + "\r\n\r\n" #for error stuff
                                last_log = ": Send; ACK; Acknowledgment: " + curr_ack + "; Window: " + str(r_win)
                                
                                error_ack = int(curr_ack)
                                #take out of buffer
                                send_buffer.pop(0)
                        
                            else:
                                print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; DAT; " + search_DAT.group(4) + "; " + search_DAT.group(6))
                                #resend last ack
                                s.sendto(bytes(last_ack, 'utf-8'), ('10.10.1.100', 8888))
                                print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + last_log)
                                
                                try: #try to search again for concat
                                    search_DAT = search_reg.match(search_DAT.group(8))
                                except IndexError:
                                    search_DAT = False
                        
                    else:
                        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; DAT; " + match_DAT.group(2) + "; " + match_DAT.group(4))
                        #resend last ack
                        s.sendto(bytes(last_ack, 'utf-8'), ('10.10.1.100', 8888))
                        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + last_log)
                          
                elif match_ACK:
                    while match_ACK:
                        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; ACK; " + match_ACK.group(2) + "; " + match_ACK.group(4)) #print recieved ack
                        skip = 0
                        
                        #TRIPLE ACK
                        if len(triple) == 0 or match_ACK.group(2) == triple[-1]:
                            #insert into list
                            triple.append(match_ACK.group(2)) 
                        else:
                            triple = []
                        #if triple, resend packets   
                        if len(triple) == 3:
                            #print('TRIPLE ACK')
                            #resend packets
                            for packets in send_buffer:
                                s.sendto(bytes(packets, 'utf-8'), ('10.10.1.100', 8888))
                                destruct = packets.split("\r\n") #NEED TO CHANGE WITH \r\n
                                print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; DAT; " + destruct[1] + "; " + destruct[2])
                            triple = []
                        
                        save_ACK = match_ACK #save prev match_ACK
                        try:
                            match_ACK = ack_reg.match(match_ACK.group(6))
                        except IndexError:
                            match_ACK = False
                        
                    if int(ex_ack) != int(save_ACK.group(3)):
                        continue
                    else:
                        send_buffer = [] #empty list
                        buf = 0
                        break
                else:
                    #breaks on unexpected packet
                    #send RST packet and log it
                    s.sendto(bytes("RST\r\n\r\n", 'utf-8'), ('10.10.1.100', 8888))
                    print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; RST;")
                    sys.exit()

            except socket.timeout:
                #for packets in queue, resend with logs
                triple = []
                if not send_buffer: #resend last ack
                    s.sendto(bytes(last_ack, 'utf-8'), ('10.10.1.100', 8888))
                    print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + last_log)
                else:
                    for packets in send_buffer:
                        s.sendto(bytes(packets, 'utf-8'), ('10.10.1.100', 8888))
                        destruct = packets.split("\r\n") #NEED TO CHANGE WITH \r\n
                        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; DAT; " + destruct[1] + "; " + destruct[2])
                
        
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#CLOSING CONNECTION

#send FIN package
s.sendto(bytes("FIN\r\nSequence: " + str(seq) + "\r\nLength: " + str(length) + "\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #sends FIN
print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; FIN; Sequence: " + str(seq) + "; Length: " + str(length))
resp = False

while resp == False:
    try:
        if s.recvfrom(1024)[0].decode()[:3] == "FIN":
            print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; FIN; Sequence: " + str(seq) + "; Length: " + str(length))
            #ACK package here
            s.sendto(bytes("ACK\r\nAcknowledgment: " + str(seq+1) + "\r\nWindow: " + str(r_win) + "\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #sends ACK
            print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; ACK; Acknowledgment: " + str(seq+1) + "; Window: " + str(r_win))
            break  
    except socket.timeout:
        s.sendto(bytes("FIN\r\nSequence: " + str(seq) + "\r\nLength: " + str(length) + "\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #resends SYN
        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; FIN; Sequence: " + str(seq) + "; Length: " + str(length))
        
while resp == False:
    try:
        if s.recvfrom(1024)[0].decode()[:3] == "ACK":
            print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Receive; ACK; Acknowledgment: " + str(seq+1) + "; Window: " + str(r_win))
            break
    except socket.timeout:
        s.sendto(bytes("ACK\r\nAcknowledgment: " + str(seq+1) + "\r\nWindow: " + str(r_win) + "\r\n\r\n",'utf-8'), ('10.10.1.100', 8888)) #resends ACK
        print(datetime.datetime.now().astimezone().strftime("%a %b %-d %X %Z %Y") + ": Send; ACK; Acknowledgment: " + str(seq+1) + "; Window: " + str(r_win))

s.close()
sys.exit()