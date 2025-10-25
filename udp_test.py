#!/usr/bin/env python3
"""
Simple UDP test script
"""
import socket
import time

def test_udp():
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 8081))

    print("UDP test server listening on port 8081")

    try:
        while True:
            data, addr = sock.recvfrom(1024)
            print(f"Received {len(data)} bytes from {addr}: {data[:50]}...")
            # Echo back
            sock.sendto(b"ACK: " + data[:10], addr)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        sock.close()

if __name__ == "__main__":
    test_udp()