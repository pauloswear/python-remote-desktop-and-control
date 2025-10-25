#!/usr/bin/env python3
"""
Simple UDP client test
"""
import socket
import time

def test_udp_client():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_addr = ('127.0.0.1', 8081)

    print("UDP test client sending to port 8081")

    for i in range(5):
        message = f"Hello UDP {i}!".encode()
        print(f"Sending: {message}")
        sock.sendto(message, server_addr)

        try:
            sock.settimeout(1.0)
            data, addr = sock.recvfrom(1024)
            print(f"Received: {data}")
        except socket.timeout:
            print("Timeout waiting for response")

        time.sleep(0.5)

    sock.close()

if __name__ == "__main__":
    test_udp_client()