#!/usr/bin/env python3
"""
Test script for PyQt5 controller with raw sockets
"""
import sys
import time
import json
from raw_transport import create_raw_socket_server, create_raw_socket_client
from pyqt5_controller import create_pyqt5_controller_protocol
from raw_protocols import RawControlleeProtocol
from constants import COMMAND_SET_VAR

def test_pyqt5_controller():
    """Test PyQt5 controller with controllee"""
    print("Starting PyQt5 controller test...")

    # Start controller (server)
    print("Creating PyQt5 controller server...")
    controller_transport = create_raw_socket_server(8080, create_pyqt5_controller_protocol)

    # Start controllee (client)
    print("Creating controllee client...")
    time.sleep(0.5)  # Give server time to start
    controllee_transport = create_raw_socket_client("127.0.0.1", 8080, RawControlleeProtocol)
    
    # Wait a moment for connection to establish
    time.sleep(1)
    
    # Send config change to disable numpy mode and enable tiles
    print("Configuring controllee to use tile mode...")
    config_message = COMMAND_SET_VAR.encode('ascii')
    config_message += json.dumps({
        'variable': 'use_numpy',
        'value': False
    }).encode('ascii')
    
    if hasattr(controllee_transport, 'protocol_instance') and controllee_transport.protocol_instance:
        controllee_transport.protocol_instance.write_message(config_message)
        print("Sent config change to disable numpy mode")
    
    print("Both controller and controllee started. PyQt5 window should appear.")
    print("Press Ctrl+C to stop...")

    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
        if hasattr(controller_transport, 'stop'):
            controller_transport.stop()
        if hasattr(controllee_transport, 'stop'):
            controllee_transport.stop()

if __name__ == "__main__":
    test_pyqt5_controller()