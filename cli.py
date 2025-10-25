from transport import get_transport
from twisted.internet import reactor
import argparse
import sys

parser = argparse.ArgumentParser(description='Starts a control session. You can choose to be controlled, or to control someone, and you need to specify who is server and who is client')
parser.add_argument('mode', choices=['controller', 'controllee'], help='Controller: You are the one who controls other computer. Controllee: You are the one being controlled')
parser.add_argument('--host', help='Enter hostname here (or ip address). If you specify this then this means that you are client (you will initiate tcp connection as client). If not specified, you will host a server')
parser.add_argument('--port', type=int, default=5005, help='Which port to use when connecting/starting the server. Default is 5005')
parser.add_argument('--raw-sockets', action='store_true', default=True, help='Use raw sockets for maximum performance (default: True)')
parser.add_argument('--twisted', action='store_true', help='Use Twisted reactor instead of raw sockets')
parser.add_argument('--pyqt5', action='store_true', help='Use PyQt5 interface instead of tkinter (modern UI)')
parsed = parser.parse_args()

controller = parsed.mode == 'controller'

# Determine transport type
use_raw_sockets = not parsed.twisted  # Default to raw sockets unless --twisted is specified
use_pyqt5 = parsed.pyqt5

if len(sys.argv) < 3:
    sys.argv.append(None)

factory = get_transport(parsed.host, controller, parsed.port, use_raw_sockets, use_pyqt5)
print("Starting", factory)

if use_raw_sockets:
    # Raw sockets mode
    if controller:
        # Controller main loop - depends on UI framework
        try:
            if use_pyqt5:
                # PyQt5 main loop
                if hasattr(factory, 'protocol_instance'):
                    protocol = factory.protocol_instance
                    if hasattr(protocol, 'run'):
                        protocol.run()
                    else:
                        # Fallback
                        while True:
                            import time
                            time.sleep(1)
                else:
                    print("Error: PyQt5 protocol not found")
            else:
                # Tkinter main loop
                if hasattr(factory, 'tk_root'):
                    factory.tk_root.mainloop()
                elif hasattr(factory, 'protocol_instance') and hasattr(factory.protocol_instance, 'tk_root'):
                    factory.protocol_instance.tk_root.mainloop()
                else:
                    # Fallback: keep main thread alive
                    while True:
                        import time
                        time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
            if hasattr(factory, 'stop'):
                factory.stop()
    else:
        # Controllee - keep main thread alive
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
            if hasattr(factory, 'stop'):
                factory.stop()
else:
    # Twisted mode
    reactor.run()